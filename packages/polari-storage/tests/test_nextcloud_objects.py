import httpx
import pytest

from dav_helpers import (
    ENCODED_ROOT_URL,
    ROOT_PATH,
    FakeNextcloud,
    Recorder,
    dav_response,
    multistatus,
)
from polari_storage import (
    Committed,
    Conflict,
    GetResult,
    InvalidKeyError,
    ListResult,
    NextcloudStorage,
    NotFoundError,
    ObjectInfo,
    ObjectStore,
    RangeNotSatisfiableError,
    StorageTransportError,
    Version,
)

pytestmark = pytest.mark.anyio

JSON_BYTES = '{"title": "Synthetic test", "pilot": "p01", "note": "ü"}\n'.encode()
KEY = "2026/p01/experiment.json"


def sorted_result(result: ListResult) -> tuple[list[str], list[str]]:
    return sorted(o.key for o in result.objects), sorted(result.common_prefixes)


def staging_folders(fake: FakeNextcloud) -> list[str]:
    return [f for f in fake.folders if f.rpartition("@")[2].startswith("stage")]


def test_satisfies_object_store_protocol() -> None:
    storage: ObjectStore = NextcloudStorage(ENCODED_ROOT_URL, "alice", "pw")
    assert isinstance(storage, NextcloudStorage)


async def test_create_then_get_and_head(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    payload = JSON_BYTES + b"\x00\xff"  # not even valid UTF-8: bytes stay bytes
    result = await storage.put_object(KEY, payload, if_none_match=True)

    assert result == Committed(Version("1"))
    assert fake.objects() == {KEY: payload}
    assert fake.versions() == {KEY: [1]}
    assert await storage.get_object(KEY) == GetResult(payload, Version("1"))
    assert await storage.head_object(KEY) == ObjectInfo(KEY, len(payload), Version("1"))


async def test_create_makes_missing_folders_only_when_needed(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    await storage.put_object(KEY, JSON_BYTES, if_none_match=True)
    # The staging folder cannot be made until its parent folders exist.
    assert fake.methods() == [
        *("PROPFIND", "MKCOL", "MKCOL", "MKCOL", "MKCOL"),
        *("PUT", "PUT", "MOVE", "PROPFIND"),
    ]
    assert {"2026", "2026/p01"} <= fake.folders

    fake.requests.clear()
    await storage.put_object("2026/p01/second.json", JSON_BYTES, if_none_match=True)
    assert fake.methods() == ["PROPFIND", "MKCOL", "PUT", "PUT", "MOVE", "PROPFIND"]


async def test_create_of_existing_object_conflicts(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    fake.add_version(KEY, 1, b"first")
    fake.requests.clear()
    assert await storage.put_object(KEY, b"second", if_none_match=True) == Conflict()
    assert fake.methods() == ["PROPFIND"]
    assert fake.objects() == {KEY: b"first"}


async def test_update_writes_a_new_version_and_keeps_the_old(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    await storage.put_object(KEY, b"v1", if_none_match=True)
    current = await storage.get_object(KEY)

    result = await storage.put_object(KEY, b"v2", if_match=current.version)

    assert result == Committed(Version("2"))
    assert fake.versions() == {KEY: [1, 2]}
    assert fake.files[f"{KEY}@000001/data"] == b"v1"  # old versions are kept
    assert await storage.get_object(KEY) == GetResult(b"v2", Version("2"))
    move = [r for r in fake.requests if r.method == "MOVE"][-1]
    assert move.headers["Overwrite"] == "F"
    assert move.headers["Destination"].endswith("experiment.json%40000002/")
    assert staging_folders(fake) == []


async def test_stale_update_conflicts_without_writing(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    fake.add_version(KEY, 1, b"v1")
    fake.add_version(KEY, 2, b"v2")
    fake.requests.clear()
    assert await storage.put_object(KEY, b"lost", if_match=Version("1")) == Conflict()
    assert fake.methods() == ["PROPFIND"]


async def test_update_of_missing_object_conflicts(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    assert await storage.put_object(KEY, b"x", if_match=Version("1")) == Conflict()
    assert fake.versions() == {}


async def test_second_writer_with_the_same_version_conflicts(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    await storage.put_object(KEY, b"base", if_none_match=True)
    base = await storage.get_object(KEY)

    first = await storage.put_object(KEY, b"alice", if_match=base.version)
    second = await storage.put_object(KEY, b"bob", if_match=base.version)

    assert isinstance(first, Committed)
    assert second == Conflict()
    assert (await storage.get_object(KEY)).data == b"alice"


async def test_writer_losing_the_move_race_conflicts(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    # Both writers listed version 1; the other one MOVEd to version 2 first.
    fake.add_version(KEY, 1, b"base")
    original = fake._move

    def other_writer_first(request: httpx.Request, path: str) -> httpx.Response:
        fake.add_version(KEY, 2, b"other")
        return original(request, path)

    fake._move = other_writer_first  # type: ignore[method-assign]
    assert await storage.put_object(KEY, b"mine", if_match=Version("1")) == Conflict()
    assert fake.objects() == {KEY: b"other"}
    assert staging_folders(fake) == []


class RacingServer:
    """Lists ``a.json`` at version 1 and lets a test decide how MOVE ends.

    ``won`` says whether our staging folder really landed on version 2;
    ``move_status`` is what the server claims, which under contention does
    not have to match.
    """

    def __init__(
        self,
        move_status: int,
        *,
        won: bool,
        stale_listings: int = 0,
        delete_status: int | None = None,
    ) -> None:
        self.move_status, self.won = move_status, won
        # How many listings of the target still miss our marker.
        self.stale_listings = stale_listings
        # What DELETE of the staging folder answers; by default 404 if the
        # MOVE took it, else 204.
        self.delete_status = delete_status
        self.marker = ""
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.raw_path.decode()
        if request.method == "PUT" and "writer-" in path:
            self.marker = path.rpartition("/")[2]
        if request.method == "MOVE":
            return httpx.Response(self.move_status)
        if request.method == "DELETE":  # of our staging folder
            if self.delete_status is not None:
                return httpx.Response(self.delete_status)
            return httpx.Response(404 if self.won else 204)
        if request.method == "PROPFIND" and path.endswith("a.json%40000002/"):
            target = ROOT_PATH + "a.json%40000002/"
            entries = [dav_response(target, collection=True, size=1)]
            if self.won and self.stale_listings == 0:
                entries.append(dav_response(target + self.marker, length=0))
            self.stale_listings = max(0, self.stale_listings - 1)
            return httpx.Response(207, content=multistatus(*entries))
        if request.method == "PROPFIND":
            return httpx.Response(
                207,
                content=multistatus(
                    dav_response(ROOT_PATH, collection=True),
                    dav_response(
                        ROOT_PATH + "a.json%40000001/", collection=True, size=1
                    ),
                ),
            )
        return httpx.Response(201)


@pytest.mark.parametrize("move_status", [201, 412, 423, 500])
async def test_losing_the_race_is_a_conflict_whatever_move_says(
    storage: NextcloudStorage, recorder: Recorder, move_status: int
) -> None:
    server = RacingServer(move_status, won=False)
    recorder.handler = server
    assert await storage.put_object("a.json", b"x", if_match=Version("1")) == Conflict()
    assert "DELETE" in [r.method for r in server.requests]  # staging is removed


@pytest.mark.parametrize("move_status", [201, 500])
async def test_winning_the_race_is_committed_whatever_move_says(
    storage: NextcloudStorage, recorder: Recorder, move_status: int
) -> None:
    # Seen on Nextcloud 34: the winner of a contended MOVE can get a 500.
    recorder.handler = RacingServer(move_status, won=True)
    result = await storage.put_object("a.json", b"x", if_match=Version("1"))
    assert result == Committed(Version("2"))


async def test_briefly_stale_listing_after_a_won_move_is_committed(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    # Seen on Nextcloud 34: right after a MOVE, the target can be listed
    # without our marker. It shows up a moment later.
    recorder.handler = RacingServer(201, won=True, stale_listings=2)
    result = await storage.put_object("a.json", b"x", if_match=Version("1"))
    assert result == Committed(Version("2"))


async def test_move_answered_201_without_our_marker_conflicts(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    # Seen on Nextcloud 34: a losing MOVE answered 201 and its staging folder
    # disappeared, but the version folder held another writer's marker.
    recorder.handler = RacingServer(201, won=False, delete_status=404)
    assert await storage.put_object("a.json", b"x", if_match=Version("1")) == Conflict()


async def test_failed_move_that_destroyed_the_staging_folder_conflicts(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    # Seen on Nextcloud 34: a MOVE answered 500 removed the source without
    # it landing anywhere. "Staging folder gone" alone does not mean "won".
    recorder.handler = RacingServer(500, won=False, delete_status=404)
    assert await storage.put_object("a.json", b"x", if_match=Version("1")) == Conflict()


async def test_failed_move_that_landed_late_is_committed(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = RacingServer(500, won=True, stale_listings=2)
    result = await storage.put_object("a.json", b"x", if_match=Version("1"))
    assert result == Committed(Version("2"))


async def test_network_error_when_the_staging_folder_never_settles(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = RacingServer(500, won=False, delete_status=403)
    with pytest.raises(StorageTransportError, match="could not find out"):
        await storage.put_object("a.json", b"x", if_match=Version("1"))


async def test_lost_move_response_is_resolved_by_the_marker(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    server = RacingServer(201, won=True)

    def handler(request: httpx.Request) -> httpx.Response:
        response = server(request)
        if request.method == "MOVE":
            raise httpx.ReadTimeout("response lost", request=request)
        return response

    recorder.handler = handler
    result = await storage.put_object("a.json", b"x", if_match=Version("1"))
    assert result == Committed(Version("2"))


async def test_put_sends_exact_bytes_to_encoded_url(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    await storage.put_object("my data/über uns.json", JSON_BYTES, if_none_match=True)
    data = next(r for r in fake.requests if r.url.raw_path.endswith(b"/data"))
    assert data.content == JSON_BYTES
    assert data.headers["Content-Type"] == "application/octet-stream"
    move = next(r for r in fake.requests if r.method == "MOVE")
    assert (
        httpx.URL(move.headers["Destination"]).raw_path
        == (ROOT_PATH + "my%20data/%C3%BCber%20uns.json%40000001/").encode()
    )
    assert fake.objects() == {"my data/über uns.json": JSON_BYTES}


async def test_get_uses_the_highest_version_and_ignores_other_entries(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    fake.add_version("d/a.json", 1, b"one")
    fake.add_file("d/a.json@2/data", b"two")  # unpadded, e.g. made by hand
    fake.add_version("d/a.json", 10, b"ten")
    fake.add_file("d/a.json@000011", b"a file, not a version folder")
    fake.add_file("d/a.json@stage-0123/data", b"someone's unfinished write")
    fake.add_file("d/a.json", b"not a version")
    assert await storage.get_object("d/a.json") == GetResult(b"ten", Version("10"))
    listing = await storage.list_objects("d/", delimiter="/")
    assert listing == ListResult([ObjectInfo("d/a.json", 3, Version("10"))], [])


async def test_get_missing_object(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    with pytest.raises(NotFoundError):
        await storage.get_object("missing.json")
    with pytest.raises(NotFoundError):
        await storage.head_object("missing/deeper.json")


@pytest.mark.parametrize(
    ("offset", "length", "header", "expected"),
    [
        (2, 3, "bytes=2-4", b"234"),
        (7, None, "bytes=7-", b"789"),
        (0, 2, "bytes=0-1", b"01"),
        (8, 10, "bytes=8-17", b"89"),
        (0, 1, "bytes=0-0", b"0"),  # Nextcloud sends the whole object here
    ],
)
async def test_get_byte_range(
    storage: NextcloudStorage,
    fake: FakeNextcloud,
    offset: int,
    length: int | None,
    header: str,
    expected: bytes,
) -> None:
    fake.add_version("digits.txt", 1, b"0123456789")
    result = await storage.get_object("digits.txt", offset=offset, length=length)
    assert result == GetResult(expected, Version("1"))
    assert fake.requests[-1].headers["Range"] == header


@pytest.mark.parametrize(
    ("content", "offset", "length"), [(b"0123", 4, None), (b"", 0, 1)]
)
async def test_get_range_beyond_end(
    storage: NextcloudStorage,
    fake: FakeNextcloud,
    content: bytes,
    offset: int,
    length: int | None,
) -> None:
    # Nextcloud answers 416, except for empty objects, where it sends 200.
    fake.add_version("a.bin", 1, content)
    with pytest.raises(RangeNotSatisfiableError):
        await storage.get_object("a.bin", offset=offset, length=length)


@pytest.mark.parametrize(("offset", "length"), [(-1, None), (0, 0), (0, -5)])
async def test_get_rejects_bad_ranges(
    storage: NextcloudStorage, fake: FakeNextcloud, offset: int, length: int | None
) -> None:
    with pytest.raises(ValueError, match="offset|length"):
        await storage.get_object("a.json", offset=offset, length=length)
    assert fake.requests == []


async def test_folders_are_not_objects(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    fake.add_version(KEY, 1, JSON_BYTES)
    with pytest.raises(NotFoundError):
        await storage.head_object("2026/p01")
    with pytest.raises(NotFoundError):
        await storage.get_object("2026/p01")


async def test_list_with_delimiter(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    for key in [
        "2026/p01/experiment.json",
        "2026/p01/mapping.yaml",
        "2026/p01/trial_1/data.xdf",
        "2026/p01/trial_2/data.xdf",
        "2026/p02/experiment.json",
    ]:
        fake.add_version(key, 1, b"x")

    assert sorted_result(await storage.list_objects("2026/p01/", delimiter="/")) == (
        ["2026/p01/experiment.json", "2026/p01/mapping.yaml"],
        ["2026/p01/trial_1/", "2026/p01/trial_2/"],
    )
    assert sorted_result(await storage.list_objects("2026/", delimiter="/")) == (
        [],
        ["2026/p01/", "2026/p02/"],
    )
    assert sorted_result(await storage.list_objects("2026/")) == (
        [
            "2026/p01/experiment.json",
            "2026/p01/mapping.yaml",
            "2026/p01/trial_1/data.xdf",
            "2026/p01/trial_2/data.xdf",
            "2026/p02/experiment.json",
        ],
        [],
    )


async def test_list_missing_prefix_is_empty(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    assert await storage.list_objects("nothing/here/") == ListResult()


async def test_delete_removes_every_version_oldest_first(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    fake.add_version(KEY, 2, b"v2")
    fake.add_version(KEY, 1, b"v1")
    fake.add_version("2026/p01/other.json", 1, b"keep")
    fake.requests.clear()

    await storage.delete_object(KEY)

    assert fake.methods() == ["PROPFIND", "DELETE", "DELETE"]
    assert [r.url.raw_path.decode()[-6:] for r in fake.requests[1:]] == [
        "000001",
        "000002",
    ]
    assert fake.objects() == {"2026/p01/other.json": b"keep"}
    assert "2026/p01" in fake.folders  # empty folders stay


async def test_delete_missing_object_is_a_no_op(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    await storage.delete_object("missing/a.json")
    assert fake.methods() == ["PROPFIND"]


async def test_object_can_be_created_again_after_delete(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    await storage.put_object(KEY, b"old", if_none_match=True)
    await storage.delete_object(KEY)
    result = await storage.put_object(KEY, b"new", if_none_match=True)
    assert result == Committed(Version("1"))
    assert (await storage.get_object(KEY)).data == b"new"


@pytest.mark.parametrize(
    "key", ["", "dir/", "../a.json", "/abs.json", "a/../../b", "a.json@000001"]
)
async def test_object_operations_reject_bad_keys_without_request(
    storage: NextcloudStorage, fake: FakeNextcloud, key: str
) -> None:
    for operation in (
        storage.head_object(key),
        storage.get_object(key),
        storage.put_object(key, b"x", if_none_match=True),
        storage.put_object(key, b"x", if_match=Version("1")),
        storage.delete_object(key),
    ):
        with pytest.raises(InvalidKeyError):
            await operation
    assert fake.requests == []


async def test_foreign_version_token_is_rejected(
    storage: NextcloudStorage, fake: FakeNextcloud
) -> None:
    with pytest.raises(ValueError, match="not a version"):
        await storage.put_object(KEY, b"x", if_match=Version('"an-etag"'))


async def test_context_manager_closes_client(fake: FakeNextcloud) -> None:
    async with NextcloudStorage(ENCODED_ROOT_URL, "alice", "pw") as storage:
        pass
    assert storage._client.is_closed
