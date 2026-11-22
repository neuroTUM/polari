import pytest
from hypothesis import given
from hypothesis import strategies as st

from dav_helpers import ROOT_PATH
from polari_storage import InvalidKeyError, InvalidResponseError
from polari_storage.keys import (
    encode_key,
    encode_root_url,
    href_to_key,
    parent_folders,
    parent_key,
    validate_key,
    validate_prefix,
)

DECODED_ROOT = "/remote.php/dav/files/alice/polari data/"


@pytest.mark.parametrize(
    "key",
    [
        "experiment.json",
        "2026/p01/2026-11-14/trial_1",
        "my data/notes 1.yaml",
        "Müller/çalışma.json",
        "100%/a%20b",  # literal percent signs, not decoded
        "...hidden/..x",  # dots inside names are fine
    ],
)
def test_validate_key_accepts_safe_keys(key: str) -> None:
    assert validate_key(key) == key


def test_validate_key_uses_nfc() -> None:
    decomposed = "Mu\u0308ller"  # "Müller" as macOS file names often store it
    assert validate_key(decomposed) == "M\u00fcller"


@pytest.mark.parametrize(
    "key",
    [
        "",
        "dir/",
        "../secret.json",
        "a/../../b",
        "a/..",
        "..",
        "./a",
        "a/./b",
        "/etc/passwd",
        "/",
        "//host/share",
        "a//b",
        "a\\..\\b",
        "C:\\data",
        "a\x00b",
        "line\nbreak",
        "a.json@000001",  # "@" is reserved for version files
        "a@b/c.json",
    ],
)
def test_validate_key_rejects_unsafe_keys(key: str) -> None:
    with pytest.raises(InvalidKeyError):
        validate_key(key)


def test_invalid_key_error_is_value_error() -> None:
    with pytest.raises(ValueError, match=r"\.\."):
        validate_key("../x")


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("", ""),
        ("2026/", "2026/"),
        ("2026/p01/", "2026/p01/"),
        ("Mu\u0308/", "M\u00fc/"),
    ],
)
def test_validate_prefix(prefix: str, expected: str) -> None:
    assert validate_prefix(prefix) == expected


@pytest.mark.parametrize(
    "prefix", ["2026", "2026/p0", "/", "//", "/a/", "a//", "../", "a@1/"]
)
def test_validate_prefix_rejects_partial_or_unsafe(prefix: str) -> None:
    with pytest.raises(InvalidKeyError):
        validate_prefix(prefix)


@pytest.mark.parametrize(
    ("key", "encoded"),
    [
        ("a/b.json", "a/b.json"),
        ("my data/a b.json", "my%20data/a%20b.json"),
        ("ü/ç.json", "%C3%BC/%C3%A7.json"),
        ("100%", "100%25"),
        ("a?b#c", "a%3Fb%23c"),
        ("%2e%2e", "%252e%252e"),  # cannot turn into ".." on the server
    ],
)
def test_encode_key(key: str, encoded: str) -> None:
    assert encode_key(key) == encoded


def test_parents() -> None:
    assert parent_key("a/b/c.json") == "a/b"
    assert parent_key("c.json") == ""
    assert parent_folders("a/b/c.json") == ["a", "a/b"]
    assert parent_folders("c.json") == []


@pytest.mark.parametrize(
    ("root_url", "encoded", "decoded"),
    [
        (
            "https://dav.example.test/remote.php/dav/files/alice/polari data",
            "https://dav.example.test" + ROOT_PATH,
            DECODED_ROOT,
        ),
        (
            "https://dav.example.test:8443/dav/Müller/100%/",
            "https://dav.example.test:8443/dav/M%C3%BCller/100%25/",
            "/dav/Müller/100%/",
        ),
        ("http://localhost", "http://localhost/", "/"),
        ("  https://dav.example.test/a//b  ", "https://dav.example.test/a/b/", "/a/b/"),
    ],
)
def test_encode_root_url(root_url: str, encoded: str, decoded: str) -> None:
    assert encode_root_url(root_url) == (encoded, decoded)


@pytest.mark.parametrize(
    "root_url",
    [
        "ftp://dav.example.test/x/",
        "dav.example.test/x/",
        "https:///x/",
        "https://alice:secret@dav.example.test/x/",
        "https://dav.example.test/x/?a=1",
        "https://dav.example.test/x/#frag",
        "https://dav.example.test/x/../y",
    ],
)
def test_encode_root_url_rejects_bad_urls(root_url: str) -> None:
    with pytest.raises(ValueError, match="root_url"):
        encode_root_url(root_url)


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        (ROOT_PATH, ""),
        (ROOT_PATH.rstrip("/"), ""),
        (ROOT_PATH + "a.json", "a.json"),
        (ROOT_PATH + "dir/", "dir"),
        (ROOT_PATH + "my%20data/a%20b.json", "my data/a b.json"),
        (ROOT_PATH + "%C3%BC.json", "ü.json"),
        ("https://dav.example.test" + ROOT_PATH + "x/y", "x/y"),
    ],
)
def test_href_to_key(href: str, expected: str) -> None:
    assert href_to_key(href, DECODED_ROOT) == expected


@pytest.mark.parametrize(
    "href",
    [
        "/remote.php/dav/files/alice/other/a.json",
        "/remote.php/dav/files/alice/polari data-evil/a.json",
        ROOT_PATH + "a/../../escape",
        ROOT_PATH + "%2E%2E/escape",
        ROOT_PATH + "a//b",
        ROOT_PATH + "%FF.json",  # not UTF-8
    ],
)
def test_href_to_key_rejects_outside_or_unsafe(href: str) -> None:
    with pytest.raises(InvalidResponseError):
        href_to_key(href, DECODED_ROOT)


LEVELS = st.text(
    st.characters(codec="utf-8", exclude_categories=["Cs"]), min_size=1, max_size=8
).filter(lambda level: "/" not in level)
KEYS = st.lists(LEVELS, min_size=1, max_size=4).map("/".join)


@given(KEYS)
def test_valid_keys_round_trip_through_hrefs(key: str) -> None:
    try:
        canonical = validate_key(key)
    except InvalidKeyError:
        return
    assert validate_key(canonical) == canonical
    href = "https://dav.example.test" + ROOT_PATH + encode_key(canonical)
    assert href_to_key(href, DECODED_ROOT) == canonical


@given(KEYS)
def test_encoded_keys_only_split_at_separators(key: str) -> None:
    try:
        canonical = validate_key(key)
    except InvalidKeyError:
        return
    encoded = encode_key(canonical)
    assert encoded.count("/") == canonical.count("/")
    assert not any(char in encoded for char in "?# \\")


@given(st.text(max_size=20))
def test_validation_either_rejects_or_returns_a_safe_key(text: str) -> None:
    try:
        key = validate_key(text)
    except InvalidKeyError:
        return
    levels = key.split("/")
    assert all(level not in ("", ".", "..") for level in levels)
    assert not key.startswith("/")
    assert "\\" not in key
    assert "@" not in key
