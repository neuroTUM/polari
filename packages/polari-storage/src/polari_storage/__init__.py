"""Async object storage with a Nextcloud backend.

Objects are addressed by keys such as ``"2026/p01/experiment.json"``.
Every write is conditional.
A write never overwrites a change it has not seen.
A conflicting write gives ``Conflict``; the caller then merges and retries::

    async with NextcloudStorage(root_url, username, app_password) as storage:
        await storage.put_object(key, data, if_none_match=True)

        current = await storage.get_object(key)
        draft = edit(current.data)
        while True:
            match await storage.put_object(key, draft, if_match=current.version):
                case Committed():
                    break
                case Conflict():
                    latest = await storage.get_object(key)
                    draft = merge(current.data, latest.data, draft)
                    current = latest
"""

from polari_storage.errors import (
    AuthenticationError,
    HTTPStatusError,
    InvalidKeyError,
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
from polari_storage.models import (
    Committed,
    Conflict,
    GetResult,
    ListResult,
    ObjectInfo,
    Version,
)
from polari_storage.nextcloud import NextcloudStorage
from polari_storage.protocol import ObjectStore

__all__ = [
    "AuthenticationError",
    "Committed",
    "Conflict",
    "GetResult",
    "HTTPStatusError",
    "InvalidKeyError",
    "InvalidResponseError",
    "ListResult",
    "LockedError",
    "NextcloudStorage",
    "NotFoundError",
    "ObjectInfo",
    "ObjectStore",
    "ObjectTooLargeError",
    "PermissionDeniedError",
    "RangeNotSatisfiableError",
    "StorageConnectionError",
    "StorageError",
    "StorageTimeoutError",
    "StorageTransportError",
    "UnexpectedStatusError",
    "Version",
]
