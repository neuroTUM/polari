"""Remote storage: a small async interface and its WebDAV implementation.

This package must stay independent of the GUI (PySide6/Qt) and of the
experiment models. It moves bytes and metadata; it does not know what an
experiment is.

Typical use::

    async with create_http_client(user, app_password) as client:
        storage: RemoteStorage = WebDAVStorage(root_url, client)
        await storage.create_file("2026/p01/experiment.json", data)
"""

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
from polari_app.storage.paths import normalize_path
from polari_app.storage.protocol import RemoteStorage
from polari_app.storage.webdav import (
    DEFAULT_MAX_READ_BYTES,
    DEFAULT_TIMEOUT,
    WebDAVStorage,
    create_http_client,
)

__all__ = [
    "DEFAULT_MAX_READ_BYTES",
    "DEFAULT_TIMEOUT",
    "AuthenticationError",
    "ConflictError",
    "FileTooLargeError",
    "HTTPStatusError",
    "InvalidPathError",
    "InvalidResponseError",
    "NotACollectionError",
    "NotFoundError",
    "OutcomeUnknownError",
    "PermissionDeniedError",
    "PreconditionFailedError",
    "RemoteEntry",
    "RemoteFileExistsError",
    "RemoteStorage",
    "StorageConnectionError",
    "StorageError",
    "StorageTimeoutError",
    "StorageTransportError",
    "UnexpectedStatusError",
    "WebDAVStorage",
    "create_http_client",
    "normalize_path",
]
