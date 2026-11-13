"""Typed metadata for entries in remote storage."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RemoteEntry:
    """One file or directory in remote storage.

    ``path`` is relative to the storage root and uses ``/`` as separator,
    without leading or trailing slash. The storage root itself has the
    path ``""`` and the name ``""``. Paths are decoded text (``"a b.json"``),
    never percent-encoded URL fragments (``"a%20b.json"``).

    ``content_length`` and ``etag`` are ``None`` when the server did not
    report them (servers usually omit the length for directories).

    ``etag`` is an opaque server-side validator, stored exactly as the
    server sent it (including quotes, e.g. ``'"5f3a"'``). It is not the
    experiment revision and must not be interpreted.
    """

    path: str
    name: str
    is_directory: bool
    content_length: int | None = None
    etag: str | None = None
