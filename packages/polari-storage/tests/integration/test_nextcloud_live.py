"""``NextcloudStorage`` against the real Nextcloud test account.

Every session works in its own ``run-<timestamp>-<id>/`` folder below
``NEXTCLOUD_ROOT_PATH`` and deletes it afterwards, even when tests fail. Run
folders older than ``STALE_AFTER`` (left behind by cancelled CI jobs) are swept
at the start. Uploads are counted and capped well below the account's 1 GB
per-run quota.
"""

import asyncio
import os
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import count

import httpx
import pytest
from hypothesis import settings
from hypothesis.stateful import run_state_machine_as_test

from object_store_model import Model, ObjectStoreMachine
from polari_storage import (
    Committed,
    Conflict,
    GetResult,
    NextcloudStorage,
    NotFoundError,
    ObjectInfo,
    StorageTransportError,
)
from polari_storage.keys import encode_key, encode_root_url

BYTE_BUDGET = 50 * 1024 * 1024  # the account allows 1 GB per run
STALE_AFTER = timedelta(hours=6)  # far longer than the 20 minute job timeout
RUN_PATTERN = re.compile(r"run-(\d{8}T\d{6}Z)-[0-9a-f]{8}")


@dataclass
class LiveNextcloud:
    """One test session's folder on the real server, plus a byte budget."""

    base_url: str  # plain (not encoded) URL of NEXTCLOUD_ROOT_PATH
    username: str
    password: str
    run: str
    admin: httpx.Client
    bytes_written: int = 0
    _folders: Iterator[int] = field(default_factory=count)

    def folder_url(self, *levels: str) -> str:
        """Plain URL of a folder inside this run, for ``NextcloudStorage``."""
        return "/".join([self.base_url, self.run, *levels])

    def mkcol(self, *levels: str) -> None:
        response = self.admin.request("MKCOL", self._encoded(*levels))
        assert response.status_code == 201, f"MKCOL failed: {response.status_code}"

    def delete(self, *levels: str) -> None:
        # Test-only cleanup: the library deliberately never deletes folders.
        response = self.admin.delete(self._encoded(*levels))
        assert response.status_code in (204, 404), f"cleanup: {response.status_code}"

    def new_folder(self) -> str:
        name = f"case-{next(self._folders)}"
        self.mkcol(self.run, name)
        return name

    def spend(self, size: int) -> None:
        self.bytes_written += size
        assert self.bytes_written <= BYTE_BUDGET, "test byte budget exceeded"

    def _encoded(self, *levels: str) -> str:
        url, _ = encode_root_url(self.base_url)
        return url + encode_key("/".join(levels)) + "/"


@pytest.fixture(scope="session")
def live() -> Iterator[LiveNextcloud]:
    username = os.environ["NEXTCLOUD_USERNAME"]
    password = os.environ["NEXTCLOUD_PASSWORD"]
    root = os.environ["NEXTCLOUD_ROOT_PATH"].strip("/")
    server_url = os.environ["NEXTCLOUD_BASE_URL"].rstrip("/")
    base_url = f"{server_url}/remote.php/dav/files/{username}/{root}"
    run = f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"

    auth = httpx.BasicAuth(username, password)
    with httpx.Client(auth=auth, follow_redirects=False, timeout=30.0) as admin:
        server = LiveNextcloud(base_url, username, password, run, admin)
        sweep_stale_runs(server)
        server.mkcol(run)
        try:
            yield server
        finally:
            server.delete(run)


def sweep_stale_runs(server: LiveNextcloud) -> None:
    """Delete run folders that cancelled or crashed sessions left behind."""

    async def stale_runs() -> list[str]:
        async with NextcloudStorage(
            server.base_url, server.username, server.password
        ) as storage:
            listing = await storage.list_objects(delimiter="/")
        cutoff = datetime.now(UTC) - STALE_AFTER
        stale = []
        for prefix in listing.common_prefixes:
            match = RUN_PATTERN.fullmatch(prefix.removesuffix("/"))
            started = match and datetime.strptime(match[1], "%Y%m%dT%H%M%SZ")
            if started and started.replace(tzinfo=UTC) < cutoff:
                stale.append(prefix.removesuffix("/"))
        return stale

    for folder in asyncio.run(stale_runs()):
        server.delete(folder)


@pytest.fixture
async def storage(live: LiveNextcloud) -> AsyncIterator[NextcloudStorage]:
    folder = live.new_folder()
    async with NextcloudStorage(
        live.folder_url(folder), live.username, live.password
    ) as storage:
        yield storage
    live.delete(live.run, folder)


@pytest.mark.anyio
async def test_round_trip(storage: NextcloudStorage, live: LiveNextcloud) -> None:
    key = "2026/p01/über experiment #1.json"
    data = b'{"title": "integration"}'
    live.spend(2 * len(data))

    created = await storage.put_object(key, data, if_none_match=True)
    assert isinstance(created, Committed)
    assert await storage.get_object(key) == GetResult(data, created.version)
    assert (await storage.get_object(key, offset=2, length=5)).data == data[2:7]
    assert (await storage.get_object(key, offset=0, length=1)).data == data[:1]
    assert await storage.head_object(key) == ObjectInfo(key, len(data), created.version)
    with pytest.raises(NotFoundError):
        await storage.get_object("2026/p01")

    listing = await storage.list_objects("2026/", delimiter="/")
    assert listing.common_prefixes == ["2026/p01/"]
    assert [o.key for o in (await storage.list_objects()).objects] == [key]

    assert await storage.put_object(key, b"x", if_none_match=True) == Conflict()
    updated = await storage.put_object(key, data[::-1], if_match=created.version)
    assert isinstance(updated, Committed)
    assert await storage.put_object(key, b"x", if_match=created.version) == Conflict()
    assert (await storage.get_object(key)).data == data[::-1]

    await storage.delete_object(key)
    with pytest.raises(NotFoundError):
        await storage.head_object(key)


WRITERS = 6
INCREMENTS = 5


@pytest.mark.anyio
async def test_concurrent_read_modify_write_loses_no_update(
    live: LiveNextcloud,
) -> None:
    """Writers increment one counter at the same time; every increment counts."""
    folder = live.new_folder()
    url = live.folder_url(folder)
    live.spend(WRITERS * INCREMENTS * 8)
    async with NextcloudStorage(url, live.username, live.password) as storage:
        assert isinstance(
            await storage.put_object("counter", b"0:start", if_none_match=True),
            Committed,
        )

    async def writer() -> int:
        conflicts = 0
        async with NextcloudStorage(url, live.username, live.password) as storage:
            for _ in range(INCREMENTS):
                draft = None
                while True:
                    try:
                        current = await storage.get_object("counter")
                        if current.data == draft:
                            break  # an attempt that looked failed had landed
                        value = int(current.data.split(b":")[0])
                        # A random suffix makes every draft unique, so a
                        # silently overwritten version would be noticed.
                        draft = f"{value + 1}:{uuid.uuid4().hex}".encode()
                        result = await storage.put_object(
                            "counter", draft, if_match=current.version
                        )
                    except StorageTransportError:
                        continue  # like the app: read again and retry
                    if isinstance(result, Committed):
                        break
                    conflicts += 1
        return conflicts

    conflicts = await asyncio.gather(*(writer() for _ in range(WRITERS)))
    async with NextcloudStorage(url, live.username, live.password) as storage:
        final = await storage.get_object("counter")
    assert int(final.data.split(b":")[0]) == WRITERS * INCREMENTS
    assert int(final.version.token) == WRITERS * INCREMENTS + 1
    assert sum(conflicts) > 0, "the writers never raced; the test proves nothing"
    live.delete(live.run, folder)


class LiveMachine(ObjectStoreMachine):
    """The model-based test from the unit suite, against the real server."""

    live: LiveNextcloud

    def make_storage(self) -> NextcloudStorage:
        self.folder = self.live.new_folder()
        return NextcloudStorage(
            self.live.folder_url(self.folder), self.live.username, self.live.password
        )

    def before_write(self, size: int) -> None:
        self.live.spend(size)

    def resync(self) -> Model:
        raise AssertionError("no faults are injected against the real server")

    def teardown(self) -> None:
        try:
            super().teardown()
        finally:
            self.live.delete(self.live.run, self.folder)


def test_model_based_against_nextcloud(live: LiveNextcloud) -> None:
    LiveMachine.live = live
    run_state_machine_as_test(
        LiveMachine,
        settings=settings(
            max_examples=10, stateful_step_count=20, deadline=None, database=None
        ),
    )
