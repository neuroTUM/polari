from typing import Literal, Protocol, overload

from polari_storage.models import (
    Committed,
    Conflict,
    GetResult,
    ListResult,
    ObjectInfo,
    Version,
)


class ObjectStore(Protocol):
    """An async object store with compare-and-swap writes.

    Keys are flat strings such as ``"2026/p01/experiment.json"``.
    A ``/`` only matters as a level separator when listing.
    Keys are plain text, never percent-encoded.
    Each write creates a new version of an object.
    A write only succeeds if the object is still at the version the caller expects.
    So a write never overwrites a change the caller has not seen.
    All errors are subclasses of :class:`~polari_storage.errors.StorageError`.
    """

    async def list_objects(
        self, prefix: str = "", *, delimiter: Literal["/"] | None = None
    ) -> ListResult:
        """List the objects whose keys start with ``prefix``.

        ``prefix`` is ``""`` or whole levels that end with ``/``.
        With ``delimiter="/"``, only the objects directly at ``prefix`` are listed.
        Each deeper level then appears once in ``common_prefixes``.
        With ``delimiter=None``, all objects below ``prefix`` are listed.
        A prefix without objects gives an empty result.
        The result has no order and is not paginated.
        A listing with ``delimiter=None`` is not a snapshot.
        Objects can change while it runs.
        A level can stay in ``common_prefixes`` after its last object is deleted.
        """
        ...

    async def head_object(self, key: str) -> ObjectInfo:
        """Return the size and the latest version of the object at ``key``.

        Raises ``NotFoundError`` if there is no object at ``key``.
        """
        ...

    async def get_object(
        self, key: str, *, offset: int = 0, length: int | None = None
    ) -> GetResult:
        """Return the content of the latest version, and that version.

        With ``offset`` and ``length``, only that byte range is returned.
        Raises ``NotFoundError`` if there is no object at ``key``.
        Raises ``RangeNotSatisfiableError`` if ``offset`` is at or past the end.
        """
        ...

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
        """Write ``data`` as the next version of the object at ``key``.

        Exactly one condition must be given.
        There is no unconditional write.
        ``if_none_match=True`` creates the object.
        It gives ``Conflict`` if the object already exists.
        ``if_match=version`` replaces the object.
        It gives ``Conflict`` if ``version`` is no longer the latest version.
        ``Committed`` always means the new version holds ``data``.
        After ``Conflict``, read the object again to see its state.
        """
        ...

    async def delete_object(self, key: str) -> None:
        """Delete the object at ``key`` with all its versions.

        Deleting a missing object does nothing.
        The object can be created again afterwards.
        Its versions then start again from the beginning.
        So a version taken before the delete can match the new object.
        Do not keep versions across a delete.
        """
        ...
