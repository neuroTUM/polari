"""Remote path safety: normalization, URL encoding and href mapping."""

import httpx
import pytest

from dav_helpers import ROOT_PATH
from polari_app.storage import InvalidPathError, InvalidResponseError, WebDAVStorage
from polari_app.storage.paths import (
    decode_root_path,
    encode_path,
    entry_name,
    href_to_path,
    normalize_path,
    parent_path,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("experiment.json", "experiment.json"),
        ("2026/p01/2026-11-14/trial_1", "2026/p01/2026-11-14/trial_1"),
        ("2026/p01/", "2026/p01"),
        ("my data/notes 1.yaml", "my data/notes 1.yaml"),
        ("Müller/çalışma.json", "Müller/çalışma.json"),
        ("100%/a%20b", "100%/a%20b"),  # literal percent signs, not decoded
        ("...hidden/..x", "...hidden/..x"),  # dots inside names are fine
    ],
)
def test_normalize_accepts_safe_paths(raw: str, expected: str) -> None:
    assert normalize_path(raw) == expected


def test_normalize_uses_nfc() -> None:
    decomposed = "Mu\u0308ller"  # "Müller" as macOS file names often store it
    assert normalize_path(decomposed) == "M\u00fcller"


@pytest.mark.parametrize(
    "raw",
    [
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
        "a//",
    ],
)
def test_normalize_rejects_unsafe_paths(raw: str) -> None:
    with pytest.raises(InvalidPathError):
        normalize_path(raw)


def test_invalid_path_error_is_value_error() -> None:
    with pytest.raises(ValueError):
        normalize_path("../x")


def test_normalize_rejects_non_string() -> None:
    with pytest.raises(InvalidPathError):
        normalize_path(b"a.json")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("path", "encoded"),
    [
        ("", ""),
        ("a/b.json", "a/b.json"),
        ("my data/a b.json", "my%20data/a%20b.json"),
        ("ü/ç.json", "%C3%BC/%C3%A7.json"),
        ("100%", "100%25"),
        ("a?b#c", "a%3Fb%23c"),
        ("%2e%2e", "%252e%252e"),  # cannot turn into ".." on the server
    ],
)
def test_encode_path(path: str, encoded: str) -> None:
    assert encode_path(path) == encoded


def test_parent_and_name() -> None:
    assert parent_path("a/b/c.json") == "a/b"
    assert parent_path("c.json") == ""
    assert entry_name("a/b/c.json") == "c.json"
    assert entry_name("") == ""


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
def test_href_to_path(href: str, expected: str) -> None:
    assert href_to_path(href, ROOT_PATH) == expected


@pytest.mark.parametrize(
    "href",
    [
        "/remote.php/dav/files/alice/other/a.json",
        "/remote.php/dav/files/alice/polari-evil/a.json",
        ROOT_PATH + "a/../../escape",
        ROOT_PATH + "%2E%2E/escape",
        ROOT_PATH + "a//b",
        ROOT_PATH + "%FF.json",  # not UTF-8
    ],
)
def test_href_to_path_rejects_outside_or_unsafe(href: str) -> None:
    with pytest.raises(InvalidResponseError):
        href_to_path(href, ROOT_PATH)


def test_decode_root_path() -> None:
    assert decode_root_path("/dav/my%20data/") == "/dav/my data/"


@pytest.mark.parametrize(
    "root_url",
    [
        "ftp://dav.example.test/x/",
        "dav.example.test/x/",
        "https:///x/",
        "https://alice:secret@dav.example.test/x/",
        "https://dav.example.test/x/?a=1",
        "https://dav.example.test/x/#frag",
    ],
)
def test_storage_rejects_bad_root_url(root_url: str) -> None:
    client = httpx.AsyncClient()
    with pytest.raises(ValueError):
        WebDAVStorage(root_url, client)


def test_storage_rejects_negative_read_limit() -> None:
    with pytest.raises(ValueError):
        WebDAVStorage(
            "https://dav.example.test/x/", httpx.AsyncClient(), max_read_bytes=-1
        )
