"""HTTP status codes, transport failures and timeouts -> typed errors."""

from collections.abc import Awaitable, Callable

import httpx
import pytest

from dav_helpers import ROOT_URL, Recorder
from polari_app.storage import (
    DEFAULT_TIMEOUT,
    AuthenticationError,
    ConflictError,
    HTTPStatusError,
    NotFoundError,
    OutcomeUnknownError,
    PermissionDeniedError,
    PreconditionFailedError,
    StorageConnectionError,
    StorageError,
    StorageTimeoutError,
    StorageTransportError,
    UnexpectedStatusError,
    WebDAVStorage,
)

pytestmark = pytest.mark.anyio

Operation = Callable[[WebDAVStorage], Awaitable[object]]

READ_OPERATIONS: dict[str, Operation] = {
    "list_directory": lambda s: s.list_directory("d"),
    "get_metadata": lambda s: s.get_metadata("d/a.json"),
    "read_file": lambda s: s.read_file("d/a.json"),
}
ALL_OPERATIONS: dict[str, Operation] = {
    **READ_OPERATIONS,
    "create_file": lambda s: s.create_file("d/new.json", b"{}"),
}


@pytest.mark.parametrize("operation", ALL_OPERATIONS)
@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (409, ConflictError),
        (412, PreconditionFailedError),
        (423, UnexpectedStatusError),
        (500, UnexpectedStatusError),
        (503, UnexpectedStatusError),
        (302, UnexpectedStatusError),
    ],
)
async def test_status_codes_map_to_typed_errors(
    storage: WebDAVStorage,
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


@pytest.mark.parametrize("operation", ALL_OPERATIONS)
async def test_redirects_are_not_followed(recorder: Recorder, operation: str) -> None:
    recorder.handler = lambda request: httpx.Response(
        301, headers={"Location": "https://elsewhere.example.test/"}
    )
    transport = httpx.MockTransport(recorder)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        # Even if the injected client follows redirects, the adapter does not:
        # a redirect could send the request (and credentials) elsewhere.
        storage = WebDAVStorage(ROOT_URL, client)
        with pytest.raises(UnexpectedStatusError) as info:
            await ALL_OPERATIONS[operation](storage)
    assert info.value.status_code == 301
    assert len(recorder.requests) == 1


@pytest.mark.parametrize("operation", READ_OPERATIONS)
@pytest.mark.parametrize(
    "exception_type", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout]
)
async def test_read_timeouts(
    storage: WebDAVStorage,
    recorder: Recorder,
    operation: str,
    exception_type: type[httpx.TimeoutException],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("synthetic timeout", request=request)

    recorder.handler = handler
    with pytest.raises(StorageTimeoutError) as info:
        await READ_OPERATIONS[operation](storage)
    assert isinstance(info.value.__cause__, exception_type)


@pytest.mark.parametrize("operation", READ_OPERATIONS)
@pytest.mark.parametrize(
    "exception_type",
    [httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError],
)
async def test_read_connection_failures(
    storage: WebDAVStorage,
    recorder: Recorder,
    operation: str,
    exception_type: type[httpx.TransportError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("synthetic failure", request=request)

    recorder.handler = handler
    with pytest.raises(StorageConnectionError):
        await READ_OPERATIONS[operation](storage)


@pytest.mark.parametrize(
    ("exception_type", "error_type"),
    [
        (httpx.ConnectError, StorageConnectionError),
        (httpx.ConnectTimeout, StorageTimeoutError),
        (httpx.PoolTimeout, StorageTimeoutError),
        (httpx.WriteTimeout, OutcomeUnknownError),
        (httpx.ReadTimeout, OutcomeUnknownError),
        (httpx.ReadError, OutcomeUnknownError),
        (httpx.WriteError, OutcomeUnknownError),
        (httpx.RemoteProtocolError, OutcomeUnknownError),
    ],
)
async def test_create_distinguishes_not_sent_from_unknown_outcome(
    storage: WebDAVStorage,
    recorder: Recorder,
    exception_type: type[httpx.TransportError],
    error_type: type[StorageTransportError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception_type("synthetic failure", request=request)

    recorder.handler = handler
    with pytest.raises(error_type) as info:
        await storage.create_file("d/new.json", b"{}")
    assert type(info.value) is error_type
    assert len(recorder.requests) == 1  # never retried automatically


@pytest.mark.parametrize("operation", ALL_OPERATIONS)
async def test_default_timeout_is_applied_per_request(
    storage: WebDAVStorage, recorder: Recorder, operation: str
) -> None:
    recorder.handler = lambda request: httpx.Response(404)
    with pytest.raises(NotFoundError):
        await ALL_OPERATIONS[operation](storage)
    assert recorder.last.extensions["timeout"] == DEFAULT_TIMEOUT.as_dict()


async def test_custom_timeout_overrides_client_timeout() -> None:
    recorder = Recorder()
    recorder.handler = lambda request: httpx.Response(404)
    custom = httpx.Timeout(2.0)
    transport = httpx.MockTransport(recorder)
    async with httpx.AsyncClient(transport=transport, timeout=None) as client:
        storage = WebDAVStorage(ROOT_URL, client, timeout=custom)
        with pytest.raises(NotFoundError):
            await storage.read_file("a.json")
    assert recorder.last.extensions["timeout"] == custom.as_dict()


async def test_errors_do_not_leak_credentials_or_server_url() -> None:
    recorder = Recorder()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(401, text="Unauthorized s3cret-echo")

    recorder.handler = handler
    transport = httpx.MockTransport(recorder)
    auth = httpx.BasicAuth("alice", "s3cret-app-password")
    async with httpx.AsyncClient(transport=transport, auth=auth) as client:
        storage = WebDAVStorage(ROOT_URL, client)
        with pytest.raises(AuthenticationError) as info:
            await storage.read_file("a.json")

    message = str(info.value)
    assert message == "GET 'a.json' failed with HTTP 401"
    assert "s3cret" not in message
    assert "dav.example.test" not in message
    assert "Basic" not in repr(info.value)
