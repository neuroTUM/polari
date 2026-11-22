from collections.abc import AsyncIterator
from functools import partial

import httpx
import pytest

from dav_helpers import ROOT_URL, FakeNextcloud, Handler, Recorder
from polari_storage import NextcloudStorage

# No test talks to a real server: httpx.MockTransport calls a Python function
# instead of opening a socket, and ``.test`` hosts never resolve anyway.


def serve(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    """Make every ``httpx.AsyncClient`` created from now on use ``handler``."""
    client = partial(httpx.AsyncClient, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "AsyncClient", client)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def no_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("polari_storage.nextcloud._RETRY_DELAY", 0.0)
    monkeypatch.setattr("polari_storage.nextcloud._SETTLE_DELAY", 0.0)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeNextcloud:
    server = FakeNextcloud()
    serve(monkeypatch, server)
    return server


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    serve(monkeypatch, recorder)
    return recorder


@pytest.fixture
async def storage(
    request: pytest.FixtureRequest,
) -> AsyncIterator[NextcloudStorage]:
    """Storage wired to whichever of ``fake`` / ``recorder`` the test uses."""
    servers = [name for name in ("fake", "recorder") if name in request.fixturenames]
    if len(servers) != 1:
        pytest.fail("use exactly one of `fake` / `recorder` together with `storage`")
    request.getfixturevalue(servers[0])  # patch httpx before the client exists
    async with NextcloudStorage(ROOT_URL, "alice", "not-a-real-password") as storage:
        yield storage
