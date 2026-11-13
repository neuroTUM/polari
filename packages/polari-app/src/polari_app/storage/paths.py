"""Remote path safety and conversion between paths and URLs.

A *remote path* is what callers pass to the storage API: plain text,
relative to the storage root, ``/`` as separator, e.g. ``"2026/p01/a b.json"``.
It is never percent-encoded by the caller; encoding happens here.

All checks are purely syntactic and run before any network request.
"""

import unicodedata
from urllib.parse import quote, unquote, urlsplit

from polari_app.storage.errors import InvalidPathError, InvalidResponseError


def normalize_path(path: str) -> str:
    """Validate a remote path and return its canonical form.

    The canonical form has no leading or trailing slash and is Unicode NFC
    normalized. ``""`` means the storage root.
    A single trailing slash is accepted and removed (``"a/"`` -> ``"a"``).

    Raises :class:`InvalidPathError` for absolute paths, ``.``/``..``
    segments, empty segments (``"a//b"``), backslashes and control
    characters. Nothing is silently "fixed" except the trailing slash.
    """
    if not isinstance(path, str):
        raise InvalidPathError(f"Remote path must be a string, got {type(path)!r}")
    if path.startswith("/"):
        raise InvalidPathError(f"Absolute remote paths are not allowed: {path!r}")
    if "\\" in path:
        raise InvalidPathError(f"Backslashes are not allowed in remote paths: {path!r}")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in path):
        raise InvalidPathError(f"Control characters are not allowed: {path!r}")

    path = unicodedata.normalize("NFC", path).removesuffix("/")
    if path == "":
        return ""

    segments = path.split("/")
    for segment in segments:
        if segment == "":
            raise InvalidPathError(f"Empty path segment in {path!r}")
        if segment in (".", ".."):
            raise InvalidPathError(f"'.' and '..' are not allowed: {path!r}")
    return path


def encode_path(path: str) -> str:
    """Percent-encode a canonical remote path for use in a URL.

    Every segment is encoded on its own (UTF-8, ``safe=""``), so characters
    such as ``%``, ``?``, ``#`` and spaces can never change the URL
    structure. The ``/`` separators are kept.
    """
    if path == "":
        return ""
    return "/".join(quote(segment, safe="") for segment in path.split("/"))


def parent_path(path: str) -> str:
    """Return the parent of a canonical remote path (``""`` for top level)."""
    return path.rpartition("/")[0]


def entry_name(path: str) -> str:
    """Return the last segment of a canonical remote path."""
    return path.rpartition("/")[2]


def decode_root_path(encoded_root_path: str) -> str:
    """Decode the URL path of the storage root for comparing with hrefs.

    ``"/dav/files/alice/my%20data/"`` -> ``"/dav/files/alice/my data/"``.
    """
    return unicodedata.normalize("NFC", unquote(encoded_root_path))


def href_to_path(href: str, root_path: str) -> str:
    """Convert a WebDAV ``<d:href>`` into a canonical remote path.

    ``href`` may be an absolute URL or an absolute path, percent-encoded.
    ``root_path`` is the *decoded* URL path of the storage root, ending
    with ``/`` (e.g. ``"/remote.php/dav/files/alice/polari/"``).

    Raises :class:`InvalidResponseError` if the href is not below the root
    or does not decode into a safe path. Only the URL path is compared; the
    host of an absolute href is not checked.
    """
    raw_path = urlsplit(href.strip()).path
    try:
        decoded = unquote(raw_path, errors="strict")
    except UnicodeDecodeError as exc:
        raise InvalidResponseError(f"href is not valid UTF-8: {href!r}") from exc
    decoded = unicodedata.normalize("NFC", decoded)

    if decoded.rstrip("/") + "/" == root_path:
        return ""
    if not decoded.startswith(root_path):
        raise InvalidResponseError(f"href is outside the storage root: {href!r}")
    try:
        return normalize_path(decoded[len(root_path) :])
    except InvalidPathError as exc:
        raise InvalidResponseError(f"href is not a safe path: {href!r}") from exc
