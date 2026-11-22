import asyncio
import contextlib
import re
import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import Literal, Self, overload

import httpx

from polari_storage.errors import (
    AuthenticationError,
    HTTPStatusError,
    InvalidResponseError,
    LockedError,
    NotFoundError,
    ObjectTooLargeError,
    PermissionDeniedError,
    RangeNotSatisfiableError,
    StorageConnectionError,
    StorageError,
    StorageTimeoutError,
    StorageTransportError,
    UnexpectedStatusError,
)
from polari_storage.keys import (
    encode_key,
    encode_root_url,
    href_to_key,
    parent_folders,
    parent_key,
    validate_key,
    validate_prefix,
)
from polari_storage.models import (
    Committed,
    Conflict,
    GetResult,
    ListResult,
    ObjectInfo,
    Version,
)
from polari_storage.propfind import PROPFIND_BODY, PropfindResource, parse_multistatus

# Meant for small JSON/YAML objects, not large XDF recordings.
_DEFAULT_TIMEOUT = timedelta(seconds=30)
_DEFAULT_MAX_READ_BYTES = 16 * 1024 * 1024

# Nextcloud answers 423 while a concurrent write holds a lock, also to reads.
# Reads are safe to repeat, so they are retried.
_ATTEMPTS = 3
_RETRY_DELAY = 0.2
# How long to wait for the outcome of an unclear MOVE.
_SETTLE_ATTEMPTS = 8
_SETTLE_DELAY = 0.5

_VERSION = re.compile(r"(?P<key>.+)@(?P<number>[0-9]+)")

_STATUS_ERRORS: Mapping[int, type[HTTPStatusError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    416: RangeNotSatisfiableError,
    423: LockedError,
}

# Failures before the request could reach the server.
# A MOVE that failed like this cannot have landed.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

type _Entry = tuple[str, PropfindResource]


class NextcloudStorage:
    """An :class:`~polari_storage.ObjectStore` in a Nextcloud folder, over WebDAV.

    ``root_url`` is the folder that holds all objects.
    It is a plain URL, not percent-encoded.
    Example: ``"https://cloud.example.org/remote.php/dav/files/alice/Polari Data"``.
    The folder must exist.
    ``username`` and ``password`` are sent with HTTP Basic auth.
    Use a Nextcloud app password.
    Redirects are never followed, so credentials never go to another host.
    Close the storage with ``async with`` or :meth:`aclose`.

    Layout:

    * Each version of an object is a folder.
    * Version 3 of ``"a/b/c.json"`` is the folder ``a/b/c.json@000003/``.
    * The content is in the file ``data`` inside it.
    * The object is its highest version.
    * Older versions are kept.
    * Keys cannot contain ``@``, so a version folder never collides with a key.
    * The folders for the levels of a key are created when needed.

    Writes:

    * Nextcloud checks ``If-Match`` and ``If-None-Match`` before it locks a file.
    * So two conditional PUTs can both succeed, and one overwrites the other.
    * Renaming a folder onto an existing folder fails reliably, though.
    * So a write first builds the new version in a private staging folder.
    * It then MOVEs that folder to the next version number with ``Overwrite: F``.
    * The staging folder holds a marker file with a random id.
    * A writer has won only if it sees its marker in the version folder.
    * The MOVE's status code is ignored, because it is unreliable.

    Invariants:

    * A version folder appears complete, in one step.
    * A version folder is never changed afterwards.
    * At most one write creates each version.
    * ``Committed`` means our data is in the new version.
    * ``Conflict`` usually means our write did not land.
    * Rarely, a write lands but cannot be confirmed in time; it then gives ``Conflict``.
    * Readers never see staging folders.
    """

    def __init__(
        self,
        root_url: str,
        username: str,
        password: str,
        *,
        timeout: timedelta = _DEFAULT_TIMEOUT,
        max_read_bytes: int = _DEFAULT_MAX_READ_BYTES,
    ) -> None:
        if timeout <= timedelta(0):
            raise ValueError("timeout must be positive")
        if max_read_bytes < 0:
            raise ValueError("max_read_bytes must not be negative")
        self._root_url, self._root_path = encode_root_url(root_url)
        self._max_read_bytes = max_read_bytes
        self._client = httpx.AsyncClient(
            auth=httpx.BasicAuth(username, password),
            timeout=timeout.total_seconds(),
            follow_redirects=False,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_objects(
        self, prefix: str = "", *, delimiter: Literal["/"] | None = None
    ) -> ListResult:
        """Send one PROPFIND per folder.

        Nextcloud refuses ``Depth: infinity``.
        """
        prefix = validate_prefix(prefix)

        result = ListResult()
        pending = [prefix]
        while pending:
            entries = await self._list_folder(pending.pop())
            for key, (number, folder, resource) in _latest(entries).items():
                result.objects.append(await self._info(key, number, folder, resource))
            for key, resource in entries:
                if not resource.is_collection or "@" in key.rpartition("/")[2]:
                    continue  # a file, a version or a staging folder
                if delimiter is None:
                    pending.append(key + "/")
                else:
                    result.common_prefixes.append(key + "/")
        return result

    async def head_object(self, key: str) -> ObjectInfo:
        key = validate_key(key)
        latest = _latest(await self._list_folder(_folder_of(key))).get(key)
        if latest is None:
            raise NotFoundError("PROPFIND", key, 404)
        return await self._info(key, *latest)

    async def get_object(
        self, key: str, *, offset: int = 0, length: int | None = None
    ) -> GetResult:
        """Raises :class:`ObjectTooLargeError` above ``max_read_bytes``."""
        key = validate_key(key)
        if offset < 0:
            raise ValueError("offset must not be negative")
        if length is not None and length < 1:
            raise ValueError("length must be at least 1")

        folders = {
            number: folder
            for object_key, number, folder, _ in _versions(
                await self._list_folder(_folder_of(key))
            )
            if object_key == key
        }
        if not folders:
            raise NotFoundError("GET", key, 404)
        latest = max(folders)
        data = await self._read(key, f"{folders[latest]}/data", offset, length)
        return GetResult(data, Version(str(latest)))

    @overload
    async def put_object(
        self, key: str, data: bytes, *, if_match: Version
    ) -> Committed | Conflict: ...

    @overload
    async def put_object(
        self, key: str, data: bytes, *, if_none_match: Literal[True]
    ) -> Committed | Conflict: ...

    async def put_object(
        self,
        key: str,
        data: bytes,
        *,
        if_match: Version | None = None,
        if_none_match: bool = False,
    ) -> Committed | Conflict:
        """Write ``data`` as the version after ``if_match``.

        ``if_none_match=True`` writes version 1.
        A stale version gives ``Conflict`` before anything is uploaded.
        """
        key = validate_key(key)
        expected = 0 if if_match is None else _number(if_match)
        latest = _latest(await self._list_folder(_folder_of(key))).get(key)
        if (0 if latest is None else latest[0]) != expected:
            return Conflict()

        target = _version_folder(key, expected + 1)
        writer = uuid.uuid4().hex
        stage, marker = f"{key}@stage-{writer}", f"writer-{writer}"
        if not await self._stage(key, stage, marker, data):
            return Conflict()

        try:
            response = await self._request(
                "MOVE",
                key,
                self._folder_url(stage),
                headers={"Destination": self._folder_url(target), "Overwrite": "F"},
                retry_locked=False,
            )
            if response.status_code in (401, 403):
                _check_status("MOVE", key, response, 201)
        except StorageTransportError as exc:
            if isinstance(exc.__cause__, _NOT_SENT):
                await self._discard(stage)
                raise
            # The MOVE was sent; _won finds out whether it happened.
        except StorageError:
            await self._discard(stage)
            raise

        if await self._won(key, target, stage, marker):
            return Committed(Version(str(expected + 1)))
        return Conflict()

    async def delete_object(self, key: str) -> None:
        """Delete all versions, oldest first.

        Readers keep seeing the latest version until it is gone.
        """
        key = validate_key(key)
        entries = await self._list_folder(_folder_of(key))
        versions = sorted(
            (number, folder)
            for object_key, number, folder, _ in _versions(entries)
            if object_key == key
        )
        for _, folder in versions:
            response = await self._write("DELETE", key, folder)
            if response.status_code != 404:
                _check_status("DELETE", key, response, 200, 204)

    async def _stage(self, key: str, stage: str, marker: str, data: bytes) -> bool:
        """Build a version in the private folder ``stage``.

        Returns ``False`` if concurrent writers kept the folder locked.
        Readers never see staging folders.
        So every step here is safe to retry.
        """
        for _ in range(_ATTEMPTS):
            response = await self._request(
                "MKCOL", key, self._folder_url(stage), headers={}, retry_locked=True
            )
            if response.status_code not in (404, 409):
                break
            await self._create_folders(key)  # a parent folder is missing
        if response.status_code == 423:
            return False
        _check_status("MKCOL", key, response, 201)

        for name, content in (("data", data), (marker, b"")):
            response = await self._request(
                "PUT",
                key,
                self._url(f"{stage}/{name}"),
                headers={"Content-Type": "application/octet-stream"},
                content=content,
                retry_locked=True,
            )
            if response.status_code not in (200, 201, 204):
                await self._discard(stage)
                if response.status_code == 423:
                    return False
                _check_status("PUT", key, response, 201)
        return True

    async def _info(
        self, key: str, number: int, folder: str, resource: PropfindResource
    ) -> ObjectInfo:
        size = resource.size
        if size is None:
            # Nextcloud reports -1 for a folder size it has not computed yet.
            # This happens right after a MOVE.
            # Then the size of the data file is used.
            entries = await self._propfind(folder, self._folder_url(folder)) or []
            size = dict(entries).get(f"{folder}/data", resource).content_length
        if size is None:
            raise InvalidResponseError(f"PROPFIND {key!r}: object without a size")
        return ObjectInfo(key, size, Version(str(number)))

    async def _won(self, key: str, target: str, stage: str, marker: str) -> bool:
        """Whether our staging folder became the version folder ``target``.

        Under contention, Nextcloud's answers to MOVE are unreliable.
        A winner can get a 500.
        A loser can get a 201, and its staging folder can still disappear.
        A listing right after a MOVE can be stale.
        So we only claim a win when we see our marker in ``target``.
        Not seeing it may just be a stale listing, so we look a few times.
        If the marker never shows up, we report a loss.
        The worst case is a missed win: the caller retries and finds its own
        data. A false win cannot happen, because the marker id is random.
        """
        if await self._has_marker(target, marker):
            return True
        for _ in range(_SETTLE_ATTEMPTS):
            try:
                response = await self._request(
                    "DELETE",
                    key,
                    self._folder_url(stage),
                    headers={},
                    retry_locked=True,
                )
            except StorageTransportError:
                response = None
            if response is not None and response.status_code in (200, 204, 404):
                # The staging folder is gone now: it cannot land any more.
                return await self._marker_appears(target, marker)
            await asyncio.sleep(_SETTLE_DELAY)  # e.g. 403 or 423 while MOVE runs
        raise StorageTransportError(
            f"PUT {key!r}: could not find out whether the write happened; "
            "read the object again before retrying"
        )

    async def _marker_appears(self, target: str, marker: str) -> bool:
        for _ in range(_SETTLE_ATTEMPTS):
            if await self._has_marker(target, marker):
                return True
            await asyncio.sleep(_SETTLE_DELAY)
        return False

    async def _has_marker(self, target: str, marker: str) -> bool:
        try:
            entries = await self._propfind(target, self._folder_url(target))
        except StorageTransportError:
            return False
        return any(entry == f"{target}/{marker}" for entry, _ in entries or [])

    async def _discard(self, stage: str) -> None:
        """Delete a staging folder and ignore errors.

        A leftover staging folder is invisible to readers.
        """
        with contextlib.suppress(StorageError):
            await self._request(
                "DELETE", stage, self._folder_url(stage), headers={}, retry_locked=True
            )

    def _url(self, key: str) -> str:
        return self._root_url + encode_key(key)

    def _folder_url(self, folder: str) -> str:
        return self._root_url + (encode_key(folder) + "/" if folder else "")

    async def _read(
        self, key: str, file: str, offset: int, length: int | None
    ) -> bytes:
        headers: dict[str, str] = {}
        ranged = offset > 0 or length is not None
        if ranged:
            end = "" if length is None else str(offset + length - 1)
            headers["Range"] = f"bytes={offset}-{end}"

        data, partial = await self._get(key, file, headers, offset, length)
        if partial:
            return bytes(data)
        if ranged:
            # A server may ignore Range and answer 200 with everything.
            # Nextcloud does this for empty files.
            if offset >= len(data):
                raise RangeNotSatisfiableError("GET", key, 416)
            data = data[offset : None if length is None else offset + length]
        return bytes(data)

    async def _get(
        self,
        key: str,
        file: str,
        headers: Mapping[str, str],
        offset: int,
        length: int | None,
    ) -> tuple[bytearray, bool]:
        """GET ``file`` and retry while it is locked.

        Returns the body and whether the answer was 206.
        """
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                async with self._client.stream(
                    "GET", self._url(file), headers=headers
                ) as response:
                    if response.status_code != 423 or attempt == _ATTEMPTS:
                        ranged = "Range" in headers
                        data, partial = await self._receive(
                            key, response, ranged, length
                        )
                        if partial:
                            _check_range_start("GET", key, response, offset)
                        return data, partial
            except httpx.RequestError as exc:
                raise _request_error("GET", key, exc) from exc
            await asyncio.sleep(_RETRY_DELAY * attempt)
        raise AssertionError("unreachable")

    async def _receive(
        self, key: str, response: httpx.Response, ranged: bool, length: int | None
    ) -> tuple[bytearray, bool]:
        """Read a GET body within the size limit.

        Returns the body and whether the answer was 206.
        """
        _check_status("GET", key, response, *((200, 206) if ranged else (200,)))
        partial = response.status_code == 206
        keep = length if partial else None
        declared = response.headers.get("Content-Length", "")
        if keep is None and declared.isdigit() and int(declared) > self._max_read_bytes:
            raise self._too_large(key)
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if keep is not None and len(data) >= keep:
                # Nextcloud answers "bytes=0-0" with the whole file.
                # So stop reading once the range is complete.
                del data[keep:]
                break
            if len(data) > self._max_read_bytes:
                raise self._too_large(key)
        return data, partial

    async def _list_folder(self, prefix: str) -> list[_Entry]:
        """List the direct children of a folder.

        A missing folder gives an empty list.
        """
        folder = prefix.removesuffix("/")
        entries = await self._propfind(folder, self._folder_url(folder))
        if entries is None:
            return []

        own = [resource for key, resource in entries if key == folder]
        if len(own) != 1:
            raise InvalidResponseError(
                f"PROPFIND {folder!r}: expected the folder itself exactly once"
            )
        if not own[0].is_collection:
            return []  # the prefix names a file, which has nothing below it

        children = [(key, resource) for key, resource in entries if key != folder]
        for key, _ in children:
            if key == "" or parent_key(key) != folder:
                raise InvalidResponseError(
                    f"PROPFIND {folder!r}: {key!r} is not a direct child"
                )
        return children

    async def _propfind(self, folder: str, url: str) -> list[_Entry] | None:
        """Send a PROPFIND with ``Depth: 1``.

        Returns ``(key, resource)`` pairs.
        Returns ``None`` if nothing is at ``url``.
        """
        response = await self._request(
            "PROPFIND",
            folder,
            url,
            headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            content=PROPFIND_BODY,
            retry_locked=True,
        )
        if response.status_code == 404:
            return None
        _check_status("PROPFIND", folder, response, 207)
        try:
            return [
                (href_to_key(resource.href, self._root_path), resource)
                for resource in parse_multistatus(response.content)
            ]
        except InvalidResponseError as exc:
            raise InvalidResponseError(f"PROPFIND {folder!r}: {exc}") from exc

    async def _create_folders(self, key: str) -> None:
        for folder in parent_folders(key):
            response = await self._request(
                "MKCOL", folder, self._folder_url(folder), headers={}, retry_locked=True
            )
            # 405: the folder exists.
            # 404, 409, 423: a concurrent writer is creating it or its parent.
            # The caller retries, so a lasting problem shows up there.
            if response.status_code not in (404, 405, 409, 423):
                _check_status("MKCOL", folder, response, 201)

    async def _write(
        self,
        method: str,
        key: str,
        file: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return await self._request(
            method,
            key,
            self._url(file),
            headers=headers or {},
            content=content,
            retry_locked=False,
        )

    async def _request(
        self,
        method: str,
        key: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes | None = None,
        retry_locked: bool,
    ) -> httpx.Response:
        """Send one request.

        With ``retry_locked``, a 423 answer is retried a few times.
        Only requests that are safe to repeat use it.
        """
        for attempt in range(_ATTEMPTS):
            try:
                response = await self._client.request(
                    method, url, headers=headers, content=content
                )
            except httpx.RequestError as exc:
                raise _request_error(method, key, exc) from exc
            last = attempt + 1 == _ATTEMPTS
            if not retry_locked or response.status_code != 423 or last:
                return response
            await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
        raise AssertionError("unreachable")

    def _too_large(self, key: str) -> ObjectTooLargeError:
        return ObjectTooLargeError(
            f"GET {key!r}: object exceeds the limit of {self._max_read_bytes} bytes"
        )


def _folder_of(key: str) -> str:
    folder = parent_key(key)
    return folder + "/" if folder else ""


def _version_folder(key: str, number: int) -> str:
    return f"{key}@{number:06d}"


def _number(version: Version) -> int:
    if not version.token.isascii() or not version.token.isdigit():
        raise ValueError(f"not a version of this store: {version!r}")
    return int(version.token)


def _versions(entries: list[_Entry]) -> list[tuple[str, int, str, PropfindResource]]:
    """``(key, number, folder, resource)`` of each version folder in ``entries``.

    Everything else is ignored, e.g. staging folders and files added by hand.
    """
    versions = []
    for folder, resource in entries:
        match = _VERSION.fullmatch(folder)
        if match and resource.is_collection and int(match["number"]) > 0:
            versions.append((match["key"], int(match["number"]), folder, resource))
    return versions


def _latest(entries: list[_Entry]) -> dict[str, tuple[int, str, PropfindResource]]:
    """``(number, folder, resource)`` of the highest version of each object."""
    latest: dict[str, tuple[int, str, PropfindResource]] = {}
    for key, number, folder, resource in _versions(entries):
        if key not in latest or latest[key][0] < number:
            latest[key] = (number, folder, resource)
    return latest


def _check_range_start(
    method: str, key: str, response: httpx.Response, offset: int
) -> None:
    content_range = response.headers.get("Content-Range", "")
    match = re.fullmatch(r"bytes (\d+)-\d+/\d+", content_range.strip())
    if match is None or int(match[1]) != offset:
        raise InvalidResponseError(
            f"{method} {key!r}: Content-Range {content_range!r} does not start "
            f"at {offset}"
        )


def _check_status(
    method: str, key: str, response: httpx.Response, *expected: int
) -> None:
    if response.status_code in expected:
        return
    error_type = _STATUS_ERRORS.get(response.status_code, UnexpectedStatusError)
    raise error_type(method, key, response.status_code)


def _request_error(method: str, key: str, exc: httpx.RequestError) -> StorageError:
    """Turn an HTTPX exception into a storage error.

    Only the exception's class name goes into the message.
    """
    kind = type(exc).__name__
    if isinstance(exc, httpx.TimeoutException):
        return StorageTimeoutError(f"{method} {key!r} timed out ({kind})")
    if isinstance(exc, httpx.DecodingError):
        return InvalidResponseError(f"{method} {key!r}: undecodable body ({kind})")
    if isinstance(exc, httpx.TransportError):
        return StorageConnectionError(f"{method} {key!r} failed ({kind})")
    return StorageTransportError(f"{method} {key!r} failed ({kind})")
