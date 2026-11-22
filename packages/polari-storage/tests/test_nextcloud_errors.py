from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta

import httpx
import pytest

from dav_helpers import (
    ROOT_PATH,
    ROOT_URL,
    Handler,
    Recorder,
    dav_response,
    multistatus,
)
from polari_storage import (
    AuthenticationError,
    Conflict,
    HTTPStatusError,
    InvalidResponseError,
    LockedError,
    NextcloudStorage,
    PermissionDeniedError,
    StorageConnectionError,
    StorageError,
    StorageTimeoutError,
    StorageTransportError,
    UnexpectedStatusError,
    Version,
)
from polari_storage.nextcloud import _ATTEMPTS, _DEFAULT_TIMEOUT

pytestmark = pytest.mark.anyio

Operation = Callable[[NextcloudStorage], Awaitable[object]]

# Every operation starts by listing the object's folder.
READ_OPERATIONS: dict[str, Operation] = {
    "list_objects": lambda s: s.list_objects("d/", delimiter="/"),
    "head_object": lambda s: s.head_object("d/a.json"),
    "get_object": lambda s: s.get_object("d/a.json"),
}
WRITE_OPERATIONS: dict[str, Operation] = {
    "put_object": lambda s: s.put_object("d/a.json", b"{}", if_match=Version("1")),
    "delete_object": lambda s: s.delete_object("d/a.json"),
}
ALL_OPERATIONS = {**READ_OPERATIONS, **WRITE_OPERATIONS}


def serving(other: Handler, *, size: int = 1) -> Handler:
    """List ``d/a.json`` at version 1; answer every other request with ``other``."""
    listing = multistatus(
        dav_response(ROOT_PATH + "d/", collection=True),
        dav_response(ROOT_PATH + "d/a.json%40000001/", collection=True, size=size),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, content=listing)
        return other(request)

    return handler


def raising(
    exception_type: type[httpx.TransportError],
) -> Callable[..., httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("synthetic failure", request=request)

    return handler


@pytest.mark.parametrize("operation", ALL_OPERATIONS)
@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (423, LockedError),
        (500, UnexpectedStatusError),
        (503, UnexpectedStatusError),
        (302, UnexpectedStatusError),
    ],
)
async def test_status_codes_map_to_typed_errors(
    storage: NextcloudStorage,
    recorder: Recorder,
    operation: str,
    status: int,
    error_type: type[HTTPStatusError],
) -> None:
    recorder.handler = lambda request: httpx.Response(status)
    with pytest.raises(error_type) as info:
        await ALL_OPERATIONS[operation](storage)
    assert info.value.status_code == status
    assert isinstance(info.value, StorageError)
    # Only the read that every operation starts with is retried, and only on 423.
    assert len(recorder.requests) == (_ATTEMPTS if status == 423 else 1)


async def test_locked_read_succeeds_once_the_lock_is_gone(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    statuses = iter([423, 423])

    def get(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses, 200), content=b"x")

    recorder.handler = serving(get)
    assert (await storage.get_object("d/a.json")).data == b"x"
    assert [r.method for r in recorder.requests] == ["PROPFIND", "GET", "GET", "GET"]


@pytest.mark.parametrize("operation", ALL_OPERATIONS)
async def test_redirects_are_not_followed(
    storage: NextcloudStorage, recorder: Recorder, operation: str
) -> None:
    # A redirect could send the request (and credentials) to another host.
    recorder.handler = lambda request: httpx.Response(
        301, headers={"Location": "https://elsewhere.example.test/"}
    )
    with pytest.raises(UnexpectedStatusError) as info:
        await ALL_OPERATIONS[operation](storage)
    assert info.value.status_code == 301
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("operation", READ_OPERATIONS)
@pytest.mark.parametrize(
    "exception_type", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout]
)
async def test_read_timeouts(
    storage: NextcloudStorage,
    recorder: Recorder,
    operation: str,
    exception_type: type[httpx.TimeoutException],
) -> None:
    recorder.handler = raising(exception_type)
    with pytest.raises(StorageTimeoutError) as info:
        await READ_OPERATIONS[operation](storage)
    assert isinstance(info.value.__cause__, exception_type)


@pytest.mark.parametrize("operation", READ_OPERATIONS)
@pytest.mark.parametrize(
    "exception_type", [httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError]
)
async def test_read_connection_failures(
    storage: NextcloudStorage,
    recorder: Recorder,
    operation: str,
    exception_type: type[httpx.TransportError],
) -> None:
    recorder.handler = raising(exception_type)
    with pytest.raises(StorageConnectionError):
        await READ_OPERATIONS[operation](storage)


@pytest.mark.parametrize(
    ("exception_type", "error_type"),
    [
        (httpx.ConnectError, StorageConnectionError),
        (httpx.ConnectTimeout, StorageTimeoutError),
        (httpx.PoolTimeout, StorageTimeoutError),
        (httpx.WriteTimeout, StorageTimeoutError),
        (httpx.ReadTimeout, StorageTimeoutError),
        (httpx.ReadError, StorageConnectionError),
        (httpx.WriteError, StorageConnectionError),
        (httpx.RemoteProtocolError, StorageConnectionError),
    ],
)
async def test_delete_network_errors(
    storage: NextcloudStorage,
    recorder: Recorder,
    exception_type: type[httpx.TransportError],
    error_type: type[StorageTransportError],
) -> None:
    recorder.handler = serving(raising(exception_type))
    with pytest.raises(error_type) as info:
        await storage.delete_object("d/a.json")
    assert type(info.value) is error_type
    assert [r.method for r in recorder.requests] == ["PROPFIND", "DELETE"]


@pytest.mark.parametrize(
    ("exception_type", "error_type"),
    [
        (httpx.ConnectError, StorageConnectionError),
        (httpx.ReadTimeout, StorageTimeoutError),
        (httpx.ReadError, StorageConnectionError),
    ],
)
async def test_put_failing_while_staging_wrote_nothing(
    storage: NextcloudStorage,
    recorder: Recorder,
    exception_type: type[httpx.TransportError],
    error_type: type[StorageTransportError],
) -> None:
    # Staging is private; a failure there is a plain error, never "unknown".
    recorder.handler = serving(raising(exception_type))
    with pytest.raises(error_type) as info:
        await WRITE_OPERATIONS["put_object"](storage)
    assert type(info.value) is error_type
    assert "MOVE" not in [r.method for r in recorder.requests]


def failing_move(
    move_error: type[httpx.TransportError],
    check_error: type[httpx.TransportError] | None = None,
) -> Handler:
    """Stage fine, fail the MOVE, and optionally the check of the outcome."""

    listing = serving(lambda request: httpx.Response(201))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "MOVE":
            raise move_error("synthetic failure", request=request)
        if request.method == "PROPFIND" and b"%40000002" in request.url.raw_path:
            if check_error is not None:
                raise check_error("synthetic failure", request=request)
            return httpx.Response(404)  # the MOVE did not happen
        if request.method == "DELETE":  # of the staging folder, still there
            if check_error is not None:
                raise check_error("synthetic failure", request=request)
            return httpx.Response(204)
        return listing(request)

    return handler


async def test_put_move_not_sent_is_a_plain_error(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = failing_move(httpx.ConnectError)
    with pytest.raises(StorageConnectionError):
        await WRITE_OPERATIONS["put_object"](storage)
    assert recorder.last.method == "DELETE"  # the staging folder is removed


async def test_put_move_lost_and_not_applied_is_a_conflict(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = failing_move(httpx.ReadTimeout)
    assert await WRITE_OPERATIONS["put_object"](storage) == Conflict()


async def test_put_raises_only_if_the_outcome_cannot_be_checked(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = failing_move(httpx.ReadTimeout, httpx.ConnectError)
    with pytest.raises(StorageTransportError, match="could not find out"):
        await WRITE_OPERATIONS["put_object"](storage)


async def test_default_timeout_is_applied(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = lambda request: httpx.Response(404)
    await storage.list_objects("d/")
    seconds = _DEFAULT_TIMEOUT.total_seconds()
    assert recorder.last.extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), seconds
    )


async def test_custom_timeout(recorder: Recorder) -> None:
    recorder.handler = lambda request: httpx.Response(404)
    custom = timedelta(milliseconds=2500)
    async with NextcloudStorage(ROOT_URL, "alice", "pw", timeout=custom) as storage:
        await storage.list_objects("d/")
    assert recorder.last.extensions["timeout"]["read"] == 2.5


async def test_credentials_are_sent_but_never_leak(recorder: Recorder) -> None:
    recorder.handler = lambda request: httpx.Response(401, text="Unauthorized s3cret")
    async with NextcloudStorage(ROOT_URL, "alice", "s3cret-app-password") as storage:
        with pytest.raises(AuthenticationError) as info:
            await storage.get_object("d/a.json")

    assert recorder.last.headers["Authorization"].startswith("Basic ")
    message = str(info.value)
    assert message == "PROPFIND 'd' failed with HTTP 401"
    assert "s3cret" not in message
    assert "dav.example.test" not in message
    assert "Basic" not in repr(info.value)


async def test_get_rejects_declared_oversize(recorder: Recorder) -> None:
    recorder.handler = serving(
        lambda request: httpx.Response(
            200, headers={"Content-Length": "11"}, content=b"x" * 11
        ),
        size=11,
    )
    async with NextcloudStorage(ROOT_URL, "a", "pw", max_read_bytes=10) as storage:
        with pytest.raises(StorageError, match="exceeds the limit of 10 bytes"):
            await storage.get_object("d/a.json")


async def test_get_rejects_streamed_oversize_without_length(recorder: Recorder) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * 4

    recorder.handler = serving(lambda request: httpx.Response(200, content=chunks()))
    async with NextcloudStorage(ROOT_URL, "a", "pw", max_read_bytes=10) as storage:
        with pytest.raises(StorageError, match="exceeds the limit"):
            await storage.get_object("d/a.json")


async def test_get_exactly_at_limit_is_allowed(recorder: Recorder) -> None:
    recorder.handler = serving(lambda request: httpx.Response(200, content=b"x" * 10))
    async with NextcloudStorage(ROOT_URL, "a", "pw", max_read_bytes=10) as storage:
        assert (await storage.get_object("d/a.json")).data == b"x" * 10


@pytest.mark.parametrize(
    ("content", "offset", "length", "expected"),
    [(b"0123456789", 2, 3, b"234"), (b"0123456789", 7, None, b"789")],
)
async def test_get_range_answered_with_whole_object(
    storage: NextcloudStorage,
    recorder: Recorder,
    content: bytes,
    offset: int,
    length: int | None,
    expected: bytes,
) -> None:
    # A server may ignore Range and answer 200 with everything.
    recorder.handler = serving(lambda request: httpx.Response(200, content=content))
    result = await storage.get_object("d/a.json", offset=offset, length=length)
    assert result.data == expected


@pytest.mark.parametrize("content_range", [None, "bytes 3-9/10", "bytes */10"])
async def test_range_response_must_start_at_offset(
    storage: NextcloudStorage, recorder: Recorder, content_range: str | None
) -> None:
    headers = {} if content_range is None else {"Content-Range": content_range}
    recorder.handler = serving(
        lambda request: httpx.Response(206, headers=headers, content=b"x")
    )
    with pytest.raises(InvalidResponseError):
        await storage.get_object("d/a.json", offset=2, length=1)


@pytest.mark.parametrize("timeout", [timedelta(0), timedelta(seconds=-1)])
def test_rejects_non_positive_timeout(timeout: timedelta) -> None:
    with pytest.raises(ValueError, match="timeout"):
        NextcloudStorage(ROOT_URL, "a", "pw", timeout=timeout)


def test_rejects_negative_read_limit() -> None:
    with pytest.raises(ValueError, match="max_read_bytes"):
        NextcloudStorage(ROOT_URL, "a", "pw", max_read_bytes=-1)


async def test_version_without_size_is_invalid(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = lambda request: httpx.Response(
        207,
        content=multistatus(
            dav_response(ROOT_PATH + "d/", collection=True),
            dav_response(ROOT_PATH + "d/a.json%40000001/", collection=True),
        ),
    )
    with pytest.raises(StorageError, match="without a size"):
        await storage.head_object("d/a.json")


async def test_get_timeout_after_listing(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = serving(raising(httpx.ReadTimeout))
    with pytest.raises(StorageTimeoutError):
        await storage.get_object("d/a.json")


async def test_put_gives_up_when_the_folder_never_appears(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    # MKCOL of the parent says it exists, but the staging folder still
    # cannot be created below it: retried a few times, then reported.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(404)
        return httpx.Response(409 if b"%40stage-" in request.url.raw_path else 405)

    recorder.handler = handler
    with pytest.raises(UnexpectedStatusError) as info:
        await storage.put_object("d/a.json", b"x", if_none_match=True)
    assert info.value.status_code == 409
    methods = [r.method for r in recorder.requests]
    assert "PUT" not in methods
    assert "MOVE" not in methods


async def test_delete_tolerates_versions_deleted_concurrently(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = serving(lambda request: httpx.Response(404))
    await storage.delete_object("d/a.json")
    assert [r.method for r in recorder.requests] == ["PROPFIND", "DELETE"]


def staging_answers(*, mkcol: int = 201, put: int = 201, move: int = 201) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            {"MKCOL": mkcol, "PUT": put, "MOVE": move}.get(request.method, 204)
        )

    return serving(handler)


@pytest.mark.parametrize("answers", [{"mkcol": 423}, {"put": 423}])
async def test_put_conflicts_while_the_folder_stays_locked(
    storage: NextcloudStorage, recorder: Recorder, answers: dict[str, int]
) -> None:
    # Nothing was written; re-reading and retrying is the right reaction.
    recorder.handler = staging_answers(**answers)
    assert await WRITE_OPERATIONS["put_object"](storage) == Conflict()
    assert "MOVE" not in [r.method for r in recorder.requests]


async def test_put_staging_rejected_by_the_server_is_an_error(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = staging_answers(put=507)  # e.g. quota exceeded
    with pytest.raises(UnexpectedStatusError) as info:
        await WRITE_OPERATIONS["put_object"](storage)
    assert info.value.status_code == 507
    assert recorder.last.method == "DELETE"  # the staging folder is removed


async def test_put_move_forbidden_is_an_error(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = staging_answers(move=403)
    with pytest.raises(PermissionDeniedError):
        await WRITE_OPERATIONS["put_object"](storage)
    assert recorder.last.method == "DELETE"
