class StorageError(Exception):
    """Base class of all storage errors."""


class InvalidKeyError(StorageError, ValueError):
    """A key or prefix is not allowed.

    It is raised before any request is sent.
    """


class HTTPStatusError(StorageError):
    """The server answered with an error status.

    The message names the method, the key and the status code.
    It never contains the server URL or credentials.
    """

    def __init__(self, method: str, key: str, status_code: int) -> None:
        self.method = method
        self.key = key
        self.status_code = status_code
        super().__init__(f"{method} {key!r} failed with HTTP {status_code}")


class AuthenticationError(HTTPStatusError):
    """HTTP 401: the credentials are missing or wrong."""


class PermissionDeniedError(HTTPStatusError):
    """HTTP 403: the user may not do this."""


class NotFoundError(HTTPStatusError):
    """There is no object at this key."""


class RangeNotSatisfiableError(HTTPStatusError):
    """HTTP 416: the byte range starts at or past the end of the object."""


class LockedError(HTTPStatusError):
    """HTTP 423: a concurrent write kept the object locked.

    Reads are retried a few times before this is raised.
    The request had no effect.
    """


class UnexpectedStatusError(HTTPStatusError):
    """The server answered with a status code the operation does not expect."""


class InvalidResponseError(StorageError):
    """The server's answer could not be understood."""


class ObjectTooLargeError(StorageError):
    """The object is larger than the read limit."""


class StorageTransportError(StorageError):
    """No usable answer arrived from the server.

    This is a network problem.
    The operation may or may not have taken effect.
    Every operation is safe to retry.
    A retried ``put_object`` gives ``Conflict`` if the first attempt landed.
    Read the object again to find out.
    """


class StorageTimeoutError(StorageTransportError):
    """The request timed out."""


class StorageConnectionError(StorageTransportError):
    """The connection failed or broke."""
