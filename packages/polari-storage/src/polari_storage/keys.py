import unicodedata
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from polari_storage.errors import InvalidKeyError, InvalidResponseError


def validate_key(key: str) -> str:
    """Check an object key and return its canonical form (Unicode NFC).

    A key is relative and uses ``/`` between levels.
    It must not end with ``/``, because that names a prefix.
    Empty, ``.`` and ``..`` levels are not allowed.
    Backslashes and control characters are not allowed.
    ``@`` is not allowed, because it marks versions.
    """
    if key == "" or key.endswith("/"):
        raise InvalidKeyError(f"Key must name an object, not a prefix: {key!r}")
    return _canonical(_no_version_separator(key))


def validate_prefix(prefix: str) -> str:
    """Check a listing prefix and return its canonical form.

    A prefix is ``""`` or whole levels that end with ``/``.
    Unlike in S3, it cannot end in the middle of a level.
    ``"2026/"`` is fine; ``"2026/p0"`` is not.
    """
    if prefix == "":
        return ""
    if not prefix.endswith("/"):
        raise InvalidKeyError(f"Prefix must be '' or end with '/': {prefix!r}")
    return _canonical(_no_version_separator(prefix.removesuffix("/"))) + "/"


def encode_key(key: str) -> str:
    """Percent-encode a canonical key for a URL, one level at a time.

    The ``/`` separators are kept.
    Characters such as ``%``, ``?``, ``#`` and spaces cannot change the URL.
    """
    return "/".join(quote(level, safe="") for level in key.split("/"))


def parent_key(key: str) -> str:
    """``"a/b/c.json"`` -> ``"a/b"``; ``""`` for top-level keys."""
    return key.rpartition("/")[0]


def parent_folders(key: str) -> list[str]:
    """All folders a key lives in, top-down: ``"a/b/c"`` -> ``["a", "a/b"]``."""
    levels = key.split("/")[:-1]
    return ["/".join(levels[: depth + 1]) for depth in range(len(levels))]


def encode_root_url(root_url: str) -> tuple[str, str]:
    """Turn a plain root URL into ``(encoded_url, decoded_path)``.

    The URL is not percent-encoded, as a user would type it.
    ``"my data"`` stays a folder called ``my data``.
    A literal ``%`` stays a ``%``.
    The encoded URL always ends with ``/``.
    The decoded path maps hrefs in server answers back to keys.
    """
    parts = urlsplit(root_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("root_url must be an absolute http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("root_url must not contain credentials")
    if parts.query or parts.fragment:
        raise ValueError("root_url must not contain a query or fragment")

    levels = [unicodedata.normalize("NFC", level) for level in parts.path.split("/")]
    levels = [level for level in levels if level]
    if any(level in (".", "..") for level in levels):
        raise ValueError("root_url must not contain '.' or '..' path segments")

    encoded_path = "".join("/" + quote(level, safe="") for level in levels) + "/"
    decoded_path = "".join("/" + level for level in levels) + "/"
    encoded_url = urlunsplit((parts.scheme, parts.netloc, encoded_path, "", ""))
    return encoded_url, decoded_path


def href_to_key(href: str, root_path: str) -> str:
    """Turn a WebDAV ``<d:href>`` into a canonical key.

    The root itself gives ``""``.
    ``href`` is percent-encoded, as an absolute URL or an absolute path.
    ``root_path`` is the decoded path of the storage root, ending with ``/``.
    Folder hrefs lose their trailing ``/``.
    Only the path is compared; the host of an absolute href is not checked.
    Raises :class:`InvalidResponseError` if the href is outside the root.
    It also raises it if the href does not decode into a safe key.
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
        return _canonical(decoded[len(root_path) :].removesuffix("/"))
    except InvalidKeyError as exc:
        raise InvalidResponseError(f"href is not a safe key: {href!r}") from exc


def _canonical(key: str) -> str:
    if key.startswith("/"):
        raise InvalidKeyError(f"Keys must be relative: {key!r}")
    if "\\" in key:
        raise InvalidKeyError(f"Backslashes are not allowed in keys: {key!r}")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in key):
        raise InvalidKeyError(f"Control characters are not allowed: {key!r}")

    key = unicodedata.normalize("NFC", key)
    for level in key.split("/"):
        if level in ("", ".", ".."):
            raise InvalidKeyError(f"Empty, '.' or '..' level in {key!r}")
    return key


def _no_version_separator(key: str) -> str:
    if "@" in key:
        raise InvalidKeyError(f"'@' is reserved for versions: {key!r}")
    return key
