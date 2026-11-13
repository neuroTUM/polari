"""Asynchronous WebDAV implementation of ``RemoteStorage`` (HTTPX based).

Responsibilities are split into three layers:

* HTTP transport: :meth:`WebDAVStorage._request`, the streaming GET in
  ``read_file`` and the translation of HTTPX exceptions / status codes
  into storage errors (``_request_error``, ``_check_status``).
* XML interpretation: :mod:`polari_app.storage.propfind`.
* Domain mapping: hrefs -> remote paths (:mod:`polari_app.storage.paths`)
  and ``PropfindResource`` -> :class:`RemoteEntry`.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

import httpx

from polari_app.storage.errors import (
    AuthenticationError,
    ConflictError,
    FileTooLargeError,
    HTTPStatusError,
    InvalidPathError,
    InvalidResponseError,
    NotACollectionError,
    NotFoundError,
    OutcomeUnknownError,
    PermissionDeniedError,
    PreconditionFailedError,
    RemoteFileExistsError,
    StorageConnectionError,
    StorageError,
    StorageTimeoutError,
    StorageTransportError,
    UnexpectedStatusError,
)
from polari_app.storage.models import RemoteEntry
from polari_app.storage.paths import (
    decode_root_path,
    encode_path,
    entry_name,
    href_to_path,
    normalize_path,
    parent_path,
)
from polari_app.storage.propfind import (
    PROPFIND_BODY,
    PropfindResource,
    parse_multistatus,
)

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
"""Seconds per phase. Intended for small JSON/YAML files, not large XDF data."""

DEFAULT_MAX_READ_BYTES = 16 * 1024 * 1024
"""``read_file`` refuses files larger than this (16 MiB)."""

_STATUS_ERRORS: Mapping[int, type[HTTPStatusError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    412: PreconditionFailedError,
}

# Failures that happen before the request could reach the server.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def create_http_client(
    username: str, password: str, *, timeout: httpx.Timeout = DEFAULT_TIMEOUT
) -> httpx.AsyncClient:
    """Create an ``httpx.AsyncClient`` with HTTP Basic auth for WebDAV.

    Credentials must come from the caller (e.g. a Nextcloud app password
    loaded from local configuration); nothing is hardcoded here. Redirects
    are not followed. The caller owns the client and must close it
    (``await client.aclose()`` or ``async with``).
    """
    return httpx.AsyncClient(
        auth=httpx.BasicAuth(username, password),
        timeout=timeout,
        follow_redirects=False,
    )


class WebDAVStorage:
    """``RemoteStorage`` backed by a WebDAV server such as Nextcloud.

    ``root_url`` is the already URL-encoded collection that acts as the
    storage root, e.g.
    ``"https://cloud.example.org/remote.php/dav/files/alice/polari/"``.
    All remote paths are resolved below it; paths cannot escape it.

    The ``client`` is injected (dependency injection): production code uses
    :func:`create_http_client`, tests pass a client with a mock transport.
    ``WebDAVStorage`` never closes the client.
    """

    def __init__(
        self,
        root_url: str,
        client: httpx.AsyncClient,
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
    ) -> None:
        parts = urlsplit(root_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("root_url must be an absolute http(s) URL")
        if parts.username is not None or parts.password is not None:
            raise ValueError("root_url must not contain credentials")
        if parts.query or parts.fragment:
            raise ValueError("root_url must not contain a query or fragment")
        if max_read_bytes < 0:
            raise ValueError("max_read_bytes must not be negative")

        root_path = parts.path if parts.path.endswith("/") else parts.path + "/"
        self._root_url = urlunsplit((parts.scheme, parts.netloc, root_path, "", ""))
        self._root_path = decode_root_path(root_path)
        self._client = client
        self._timeout = timeout
        self._max_read_bytes = max_read_bytes

    # ------------------------------------------------------------------ API

    async def list_directory(self, path: str) -> list[RemoteEntry]:
        """PROPFIND ``Depth: 1``; return direct children sorted by path."""
        rel = normalize_path(path)
        entries = await self._propfind(rel, depth="1", collection=True)

        own: RemoteEntry | None = None
        children: list[RemoteEntry] = []
        for entry in entries:
            if entry.path == rel:
                if own is not None:
                    raise InvalidResponseError(f"PROPFIND {rel!r}: duplicate self")
                own = entry
            elif rel != "" and entry.path == "":
                raise InvalidResponseError(f"PROPFIND {rel!r}: unexpected root entry")
            elif parent_path(entry.path) == rel:
                children.append(entry)
            else:
                raise InvalidResponseError(
                    f"PROPFIND {rel!r}: {entry.path!r} is not a direct child"
                )

        if own is None:
            raise InvalidResponseError(f"PROPFIND {rel!r}: directory itself missing")
        if not own.is_directory:
            raise NotACollectionError(f"{rel!r} is not a directory")
        return sorted(children, key=lambda entry: entry.path)

    async def get_metadata(self, path: str) -> RemoteEntry:
        """PROPFIND ``Depth: 0``; return the entry for ``path`` itself."""
        rel = normalize_path(path)
        entries = await self._propfind(rel, depth="0", collection=rel == "")
        if len(entries) != 1 or entries[0].path != rel:
            raise InvalidResponseError(
                f"PROPFIND {rel!r}: expected exactly one entry for the resource"
            )
        return entries[0]

    async def read_file(self, path: str) -> bytes:
        """GET the file and return its exact bytes.

        Meant for small metadata files. Raises :class:`FileTooLargeError`
        once more than ``max_read_bytes`` would be held in memory.
        """
        rel = _file_path(path)
        url = self._url(rel, collection=False)
        try:
            async with self._client.stream(
                "GET", url, timeout=self._timeout, follow_redirects=False
            ) as resp:
                _check_status("GET", rel, resp, expected=200)
                declared = resp.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > self._max_read_bytes:
                    raise self._too_large(rel)
                data = bytearray()
                async for chunk in resp.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > self._max_read_bytes:
                        raise self._too_large(rel)
                return bytes(data)
        except httpx.RequestError as exc:
            raise _request_error("GET", rel, exc, write=False) from exc

    async def create_file(self, path: str, content: bytes) -> RemoteEntry:
        """PUT with ``If-None-Match: *``; never overwrites existing resources.

        Returns an entry built from the request (``content_length`` is the
        number of bytes sent, ``etag`` comes from the response ``ETag``
        header and may be ``None``).

        Raises :class:`RemoteFileExistsError` (HTTP 412) if the target
        exists, :class:`ConflictError` (409) if the parent directory is
        missing and :class:`OutcomeUnknownError` if the connection failed
        after the request may have been sent.
        """
        rel = _file_path(path)
        if not isinstance(content, bytes):
            raise TypeError("content must be bytes; encode text first (UTF-8)")
        response = await self._request(
            "PUT",
            rel,
            self._url(rel, collection=False),
            headers={
                "If-None-Match": "*",
                "Content-Type": "application/octet-stream",
            },
            content=content,
            write=True,
        )
        if response.status_code == 412:
            raise RemoteFileExistsError("PUT", rel, 412)
        # 200/204 would mean an existing resource was replaced: never accept.
        _check_status("PUT", rel, response, expected=201)
        return RemoteEntry(
            path=rel,
            name=entry_name(rel),
            is_directory=False,
            content_length=len(content),
            etag=response.headers.get("ETag"),
        )

    # ------------------------------------------------------------- helpers

    def _url(self, rel: str, *, collection: bool) -> str:
        if rel == "":
            return self._root_url
        return self._root_url + encode_path(rel) + ("/" if collection else "")

    async def _propfind(
        self, rel: str, *, depth: str, collection: bool
    ) -> list[RemoteEntry]:
        response = await self._request(
            "PROPFIND",
            rel,
            self._url(rel, collection=collection),
            headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
            content=PROPFIND_BODY,
            write=False,
        )
        _check_status("PROPFIND", rel, response, expected=207)
        try:
            resources = parse_multistatus(response.content)
            return [self._to_entry(resource) for resource in resources]
        except InvalidResponseError as exc:
            raise InvalidResponseError(f"PROPFIND {rel!r}: {exc}") from exc

    def _to_entry(self, resource: PropfindResource) -> RemoteEntry:
        rel = href_to_path(resource.href, self._root_path)
        return RemoteEntry(
            path=rel,
            name=entry_name(rel),
            is_directory=resource.is_collection,
            content_length=resource.content_length,
            etag=resource.etag,
        )

    async def _request(
        self,
        method: str,
        rel: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes,
        write: bool,
    ) -> httpx.Response:
        try:
            return await self._client.request(
                method,
                url,
                headers=headers,
                content=content,
                timeout=self._timeout,
                follow_redirects=False,
            )
        except httpx.RequestError as exc:
            raise _request_error(method, rel, exc, write=write) from exc

    def _too_large(self, rel: str) -> FileTooLargeError:
        return FileTooLargeError(
            f"GET {rel!r}: file exceeds the limit of {self._max_read_bytes} bytes"
        )


def _file_path(path: str) -> str:
    rel = normalize_path(path)
    if rel == "":
        raise InvalidPathError("The storage root is a directory, not a file")
    return rel


def _check_status(
    method: str, rel: str, response: httpx.Response, *, expected: int
) -> None:
    if response.status_code == expected:
        return
    error_type = _STATUS_ERRORS.get(response.status_code, UnexpectedStatusError)
    raise error_type(method, rel, response.status_code)


def _request_error(
    method: str, rel: str, exc: httpx.RequestError, *, write: bool
) -> StorageError:
    """Translate an HTTPX request exception into a storage error.

    Only the exception class name is included in the message; the original
    exception stays available as ``__cause__`` for debugging.
    """
    kind = type(exc).__name__
    if write and not isinstance(exc, _NOT_SENT):
        return OutcomeUnknownError(
            f"{method} {rel!r}: {kind}; the write may or may not have happened, "
            "check with get_metadata before retrying"
        )
    if isinstance(exc, httpx.TimeoutException):
        return StorageTimeoutError(f"{method} {rel!r} timed out ({kind})")
    if isinstance(exc, httpx.DecodingError):
        return InvalidResponseError(f"{method} {rel!r}: undecodable body ({kind})")
    if isinstance(exc, httpx.TransportError):
        return StorageConnectionError(f"{method} {rel!r} failed ({kind})")
    return StorageTransportError(f"{method} {rel!r} failed ({kind})")
