from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Version:
    """One version of one object, as returned by the store.

    Pass it as ``if_match`` to write only if the object is still at this version.
    Treat ``token`` as opaque.
    Its format belongs to the backend.
    """

    token: str


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    """The size and the latest version of one object."""

    key: str
    size: int
    version: Version


@dataclass(frozen=True, slots=True)
class GetResult:
    """The content of one version of an object, and that version."""

    data: bytes
    version: Version


@dataclass(frozen=True, slots=True)
class Committed:
    """``put_object`` wrote ``version``."""

    version: Version


@dataclass(frozen=True, slots=True)
class Conflict:
    """``put_object`` could not confirm a new version.

    Usually the object was no longer at the expected version.
    Then nothing was written.
    In rare cases the write landed but could not be confirmed in time.
    Read the object again.
    If it already holds your data, your write landed.
    Otherwise merge and retry.
    """


@dataclass(frozen=True, slots=True)
class ListResult:
    """The result of ``list_objects``.

    Neither list has a particular order.
    """

    objects: list[ObjectInfo] = field(default_factory=list)
    common_prefixes: list[str] = field(default_factory=list)
