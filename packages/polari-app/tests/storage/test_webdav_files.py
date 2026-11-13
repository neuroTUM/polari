"""read_file() (GET) and create_file() (conditional PUT)."""

from collections.abc import AsyncIterator

import httpx
import pytest

from dav_helpers import ROOT_URL, Recorder
from polari_app.storage import (
    ConflictError,
    FileTooLargeError,
    InvalidPathError,
    NotFoundError,
    PreconditionFailedError,
    RemoteEntry,
    RemoteFileExistsError,
    UnexpectedStatusError,
    WebDAVStorage,
)

pytestmark = pytest.mark.anyio

JSON_BYTES = '{"title": "Synthetic test", "pilot": "p01", "note": "ü"}\n'.encode()


async def test_read_returns_exact_bytes(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    payload = JSON_BYTES + b"\x00\xff\r\n"  # not even valid UTF-8: bytes stay bytes
    recorder.handler = lambda request: httpx.Response(200, content=payload)

    assert await storage.read_file("2026/p01/experiment.json") == payload
    assert recorder.last.method == "GET"
    assert str(recorder.last.url) == ROOT_URL + "2026/p01/experiment.json"


async def test_read_empty_file(storage: WebDAVStorage, recorder: Recorder) -> None:
    recorder.handler = lambda request: httpx.Response(200, content=b"")
    assert await storage.read_file("empty.json") == b""


async def test_read_missing_file(storage: WebDAVStorage, recorder: Recorder) -> None:
    recorder.handler = lambda request: httpx.Response(404)
    with pytest.raises(NotFoundError) as info:
        await storage.read_file("missing.json")
    assert info.value.method == "GET"


async def test_read_root_is_rejected_without_request(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    with pytest.raises(InvalidPathError):
        await storage.read_file("")
    assert recorder.requests == []


async def test_read_rejects_declared_oversize() -> None:
    recorder = Recorder()
    recorder.handler = lambda request: httpx.Response(
        200, headers={"Content-Length": "11"}, content=b"x" * 11
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as client:
        storage = WebDAVStorage(ROOT_URL, client, max_read_bytes=10)
        with pytest.raises(FileTooLargeError):
            await storage.read_file("big.json")


async def test_read_rejects_streamed_oversize_without_length() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(5):
            yield b"x" * 4

    recorder = Recorder()
    recorder.handler = lambda request: httpx.Response(200, content=chunks())
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as client:
        storage = WebDAVStorage(ROOT_URL, client, max_read_bytes=10)
        with pytest.raises(FileTooLargeError):
            await storage.read_file("big.json")


async def test_read_exactly_at_limit_is_allowed() -> None:
    recorder = Recorder()
    recorder.handler = lambda request: httpx.Response(200, content=b"x" * 10)
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as client:
        storage = WebDAVStorage(ROOT_URL, client, max_read_bytes=10)
        assert await storage.read_file("ok.json") == b"x" * 10


async def test_create_sends_conditional_put_with_exact_content(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = lambda request: httpx.Response(201, headers={"ETag": '"n1"'})
    entry = await storage.create_file("2026/p01/new experiment.json", JSON_BYTES)

    request = recorder.last
    assert request.method == "PUT"
    assert request.headers["If-None-Match"] == "*"
    assert request.headers["Content-Type"] == "application/octet-stream"
    assert request.content == JSON_BYTES
    assert str(request.url) == ROOT_URL + "2026/p01/new%20experiment.json"
    assert entry == RemoteEntry(
        "2026/p01/new experiment.json",
        "new experiment.json",
        False,
        len(JSON_BYTES),
        '"n1"',
    )


async def test_create_without_etag_header(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = lambda request: httpx.Response(201)
    entry = await storage.create_file("a.json", b"{}")
    assert entry.etag is None


async def test_create_existing_file_raises_and_does_not_overwrite(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    remote = {"a.json": b"original"}

    def server(request: httpx.Request) -> httpx.Response:
        # A tiny fake server that honours If-None-Match: * like RFC 9110.
        name = request.url.path.rsplit("/", 1)[-1]
        if name in remote and request.headers.get("If-None-Match") == "*":
            return httpx.Response(412)
        remote[name] = request.content
        return httpx.Response(201)

    recorder.handler = server
    with pytest.raises(RemoteFileExistsError) as info:
        await storage.create_file("a.json", b"replacement")

    assert remote["a.json"] == b"original"
    assert isinstance(info.value, PreconditionFailedError)
    assert info.value.status_code == 412
    assert len(recorder.requests) == 1  # no retry, no fallback without condition


async def test_create_missing_parent_raises_conflict(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = lambda request: httpx.Response(409)
    with pytest.raises(ConflictError):
        await storage.create_file("no/such/dir/a.json", b"{}")


@pytest.mark.parametrize("status", [200, 204])
async def test_create_rejects_success_codes_that_mean_replace(
    storage: WebDAVStorage, recorder: Recorder, status: int
) -> None:
    recorder.handler = lambda request: httpx.Response(status)
    with pytest.raises(UnexpectedStatusError):
        await storage.create_file("a.json", b"{}")


async def test_create_rejects_text_content(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    with pytest.raises(TypeError):
        await storage.create_file("a.json", "{}")  # type: ignore[arg-type]
    assert recorder.requests == []


@pytest.mark.parametrize("path", ["", "../a.json", "/abs.json", "a/../../b.json"])
async def test_create_rejects_unsafe_paths_without_request(
    storage: WebDAVStorage, recorder: Recorder, path: str
) -> None:
    with pytest.raises(InvalidPathError):
        await storage.create_file(path, b"{}")
    assert recorder.requests == []
