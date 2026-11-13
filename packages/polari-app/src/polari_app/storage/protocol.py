"""The storage interface, independent of any concrete backend."""

from typing import Protocol

from polari_app.storage.models import RemoteEntry


class RemoteStorage(Protocol):
    """Asynchronous access to files below one remote root.

    All ``path`` arguments are relative to the storage root, use ``/`` as
    separator and are plain (not percent-encoded) text. ``""`` is the root.
    Implementations raise subclasses of
    :class:`polari_app.storage.errors.StorageError`.
    """

    async def list_directory(self, path: str) -> list[RemoteEntry]:
        """Return the direct children of the directory at ``path``.

        The directory itself is not part of the result. An empty list means
        the directory exists and is empty; a missing directory raises
        ``NotFoundError``.
        """
        ...

    async def get_metadata(self, path: str) -> RemoteEntry:
        """Return metadata for the file or directory at ``path``."""
        ...

    async def read_file(self, path: str) -> bytes:
        """Return the complete content of the (small) file at ``path``."""
        ...

    async def create_file(self, path: str, content: bytes) -> RemoteEntry:
        """Create a new file at ``path``. Never overwrites an existing one.

        Raises ``RemoteFileExistsError`` if something already exists there.
        """
        ...
