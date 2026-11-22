"""207 Multi-Status XML parsing, independent of HTTP."""

import pytest

from dav_helpers import dav_response, multistatus
from polari_storage import InvalidResponseError
from polari_storage.propfind import (
    PROPFIND_BODY,
    PropfindResource,
    parse_multistatus,
    parse_status_line,
)


def test_parses_files_and_collections() -> None:
    body = multistatus(
        dav_response("/r/", collection=True, size=42),
        dav_response("/r/a.json", length=42),
    )
    assert parse_multistatus(body) == [
        PropfindResource("/r/", True, None, 42),
        PropfindResource("/r/a.json", False, 42, None),
    ]


@pytest.mark.parametrize("prefix", ["d", "D", "dav", "x"])
def test_any_prefix_for_dav_namespace(prefix: str) -> None:
    body = multistatus(dav_response("/r/a", length=1, prefix=prefix), prefix=prefix)
    assert parse_multistatus(body) == [PropfindResource("/r/a", False, 1, None)]


def test_default_namespace_without_prefix() -> None:
    body = b"""<?xml version="1.0"?>
    <multistatus xmlns="DAV:"><response><href>/r/a</href>
      <propstat><prop><resourcetype><collection/></resourcetype></prop>
      <status>HTTP/1.1 200 OK</status></propstat></response></multistatus>"""
    assert parse_multistatus(body) == [PropfindResource("/r/a", True, None, None)]


def test_wrong_namespace_is_not_dav() -> None:
    body = b'<d:multistatus xmlns:d="urn:not-dav"/>'
    with pytest.raises(InvalidResponseError, match="multistatus"):
        parse_multistatus(body)


def test_extra_nextcloud_namespaces_and_props_are_ignored() -> None:
    body = b"""<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"
                   xmlns:nc="http://nextcloud.org/ns">
      <d:response><d:href>/r/a.json</d:href>
        <d:propstat><d:prop>
          <d:resourcetype/><d:getcontentlength> 7 </d:getcontentlength>
          <d:getetag>"abc"</d:getetag><oc:fileid>12</oc:fileid>
          <oc:size>7</oc:size>
        </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
      </d:response></d:multistatus>"""
    assert parse_multistatus(body) == [PropfindResource("/r/a.json", False, 7, 7)]


def test_unsuccessful_propstat_values_are_ignored() -> None:
    # A 404 group that (oddly) carries values must not be used.
    body = b"""<d:multistatus xmlns:d="DAV:"><d:response><d:href>/r/a</d:href>
      <d:propstat><d:prop><d:resourcetype/></d:prop>
        <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
      <d:propstat><d:prop><d:getetag>"stale"</d:getetag>
        <d:getcontentlength>99</d:getcontentlength></d:prop>
        <d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>
    </d:response></d:multistatus>"""
    assert parse_multistatus(body) == [PropfindResource("/r/a", False, None, None)]


def test_resourcetype_only_in_failed_propstat_is_invalid() -> None:
    body = b"""<d:multistatus xmlns:d="DAV:"><d:response><d:href>/r/a</d:href>
      <d:propstat><d:prop><d:resourcetype/></d:prop>
        <d:status>HTTP/1.1 403 Forbidden</d:status></d:propstat>
    </d:response></d:multistatus>"""
    with pytest.raises(InvalidResponseError, match="resourcetype"):
        parse_multistatus(body)


def test_empty_size_and_length_are_none() -> None:
    body = b"""<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
      <d:response><d:href>/r/a</d:href>
      <d:propstat><d:prop><d:resourcetype/><oc:size/>
        <d:getcontentlength></d:getcontentlength></d:prop>
        <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
    </d:response></d:multistatus>"""
    assert parse_multistatus(body) == [PropfindResource("/r/a", False, None, None)]


def test_empty_multistatus() -> None:
    assert parse_multistatus(multistatus()) == []


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not xml at all",
        b"<d:multistatus xmlns:d='DAV:'><d:response>",
        b"<html><body>Login</body></html>",
        b"<d:multistatus><d:response/></d:multistatus>",  # unbound prefix
    ],
)
def test_malformed_or_wrong_documents(body: bytes) -> None:
    with pytest.raises(InvalidResponseError):
        parse_multistatus(body)


def test_doctype_is_rejected() -> None:
    body = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
        b'<d:multistatus xmlns:d="DAV:"/>'
    )
    with pytest.raises(InvalidResponseError, match="DOCTYPE"):
        parse_multistatus(body)


@pytest.mark.parametrize(
    "response",
    [
        # no href
        "<d:response><d:propstat><d:prop><d:resourcetype/></d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>",
        # two hrefs
        "<d:response><d:href>/a</d:href><d:href>/b</d:href>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:response>",
        # response-level status instead of properties
        "<d:response><d:href>/a</d:href>"
        "<d:status>HTTP/1.1 404 Not Found</d:status></d:response>",
        # no propstat at all
        "<d:response><d:href>/a</d:href></d:response>",
        # propstat without status
        "<d:response><d:href>/a</d:href><d:propstat><d:prop>"
        "<d:resourcetype/></d:prop></d:propstat></d:response>",
        # successful propstat without prop
        "<d:response><d:href>/a</d:href><d:propstat>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>",
        # negative / non-numeric content length
        "<d:response><d:href>/a</d:href><d:propstat><d:prop><d:resourcetype/>"
        "<d:getcontentlength>-1</d:getcontentlength></d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>",
        "<d:response><d:href>/a</d:href><d:propstat><d:prop><d:resourcetype/>"
        "<d:getcontentlength>12kB</d:getcontentlength></d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>",
    ],
)
def test_invalid_response_structures(response: str) -> None:
    with pytest.raises(InvalidResponseError):
        parse_multistatus(multistatus(response))


@pytest.mark.parametrize(
    ("line", "code"),
    [("HTTP/1.1 200 OK", 200), ("HTTP/1.1 404 Not Found", 404), ("HTTP/2 207", 207)],
)
def test_status_line(line: str, code: int) -> None:
    assert parse_status_line(line) == code


@pytest.mark.parametrize("line", [None, "", "200 OK", "HTTP/1.1 OK", "HTTP/1.1 20"])
def test_invalid_status_line(line: str | None) -> None:
    with pytest.raises(InvalidResponseError):
        parse_status_line(line)


def test_request_body_asks_for_needed_props() -> None:
    for prop in (b"resourcetype", b"getcontentlength", b"oc:size"):
        assert prop in PROPFIND_BODY
    assert b'xmlns:d="DAV:"' in PROPFIND_BODY


def test_folder_size_minus_one_means_unknown() -> None:
    # Nextcloud reports -1 for a folder whose size it has not computed yet.
    body = multistatus(dav_response("/r/d/", collection=True, size=-1))
    assert parse_multistatus(body) == [PropfindResource("/r/d/", True, None, None)]
