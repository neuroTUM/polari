"""Typed errors raised by the storage layer.

Every error derives from :class:`StorageError`, so callers can catch the
whole family at once or react to specific cases. Messages contain the HTTP
method, the *relative* remote path and the status code, but never the full
server URL or any credentials.

Hierarchy::

    StorageError
    +-- InvalidPathError            (also a ValueError; nothing was sent)
    +-- HTTPStatusError             (server answered with an error status)
    |   +-- AuthenticationError     401
    |   +-- PermissionDeniedError   403
    |   +-- NotFoundError           404
    |   +-- ConflictError           409
    |   +-- PreconditionFailedError 412
    |   |   +-- RemoteFileExistsError  (412 for create_file)
    |   +-- UnexpectedStatusError   anything else
    +-- InvalidResponseError        (bad XML, unexpected response shape)
    +-- NotACollectionError         (list_directory on a file)
    +-- FileTooLargeError           (read_file size limit exceeded)
    +-- StorageTransportError       (no usable HTTP response)
        +-- StorageTimeoutError
        +-- StorageConnectionError
        +-- OutcomeUnknownError     (write may or may not have happened)
"""


class StorageError(Exception):
    """Base class of all storage errors."""


class InvalidPathError(StorageError, ValueError):
    """A remote path is unsafe or malformed. Raised before any request."""


class HTTPStatusError(StorageError):
    """The server answered with a status code that signals an error."""

    def __init__(self, method: str, path: str, status_code: int) -> None:
        self.method = method
        self.path = path
        self.status_code = status_code
        super().__init__(f"{method} {path!r} failed with HTTP {status_code}")


class AuthenticationError(HTTPStatusError):
    """HTTP 401: missing or wrong credentials."""


class PermissionDeniedError(HTTPStatusError):
    """HTTP 403: authenticated, but not allowed to do this."""


class NotFoundError(HTTPStatusError):
    """HTTP 404: the resource does not exist."""


class ConflictError(HTTPStatusError):
    """HTTP 409: e.g. the parent directory of a new file does not exist."""


class PreconditionFailedError(HTTPStatusError):
    """HTTP 412: a conditional request header did not match."""


class RemoteFileExistsError(PreconditionFailedError):
    """``create_file`` refused because the target already exists."""


class UnexpectedStatusError(HTTPStatusError):
    """Any other status code that the operation does not accept."""


class InvalidResponseError(StorageError):
    """The response could not be interpreted (malformed or unexpected)."""


class NotACollectionError(StorageError):
    """A directory operation was used on something that is not a directory."""


class FileTooLargeError(StorageError):
    """A downloaded file is larger than the allowed maximum."""


class StorageTransportError(StorageError):
    """No usable HTTP response was received (network level problem)."""


class StorageTimeoutError(StorageTransportError):
    """The request timed out."""


class StorageConnectionError(StorageTransportError):
    """The connection failed or broke."""


class OutcomeUnknownError(StorageTransportError):
    """A write request failed after it may have reached the server.

    The remote file may or may not exist now. Check with ``get_metadata``
    before retrying; never assume that the write failed.
    """
