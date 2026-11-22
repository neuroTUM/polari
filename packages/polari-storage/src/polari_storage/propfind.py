import xml.etree.ElementTree as ET
from dataclasses import dataclass

from polari_storage.errors import InvalidResponseError

# ElementTree turns namespaced tags into "{uri}localname".
# So the prefix the server picks never matters: <d:href>, <D:href> and
# <href xmlns="DAV:"> are all the same tag.
_DAV = "{DAV:}"
MULTISTATUS = f"{_DAV}multistatus"
RESPONSE = f"{_DAV}response"
HREF = f"{_DAV}href"
STATUS = f"{_DAV}status"
PROPSTAT = f"{_DAV}propstat"
PROP = f"{_DAV}prop"
RESOURCETYPE = f"{_DAV}resourcetype"
COLLECTION = f"{_DAV}collection"
GETCONTENTLENGTH = f"{_DAV}getcontentlength"
# Nextcloud's size of a resource.
# For a folder it is the size of everything inside.
OC_SIZE = "{http://owncloud.org/ns}size"

PROPFIND_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
    b"<d:prop><d:resourcetype/><d:getcontentlength/><oc:size/></d:prop>"
    b"</d:propfind>"
)
"""The PROPFIND body. It asks only for the properties the storage uses."""


@dataclass(frozen=True, slots=True)
class PropfindResource:
    """One ``<d:response>`` element, reduced to the properties we use."""

    href: str
    is_collection: bool
    content_length: int | None
    size: int | None


def parse_multistatus(body: bytes) -> list[PropfindResource]:
    """Parse a 207 Multi-Status body into resources, in document order.

    Only ``<d:propstat>`` groups with a 2xx status are used.
    Other groups are ignored.
    They typically list properties a resource does not have, with 404.
    Raises :class:`InvalidResponseError` for malformed XML or a DTD.
    It also raises it for a wrong root element or invalid values.
    It also raises it if ``href`` or ``resourcetype`` is missing.
    """
    # WebDAV never needs a DTD.
    # Refusing it blocks entity expansion attacks.
    if b"<!DOCTYPE" in body:
        raise InvalidResponseError("XML with a DOCTYPE is not accepted")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise InvalidResponseError(f"Malformed XML: {exc}") from exc
    if root.tag != MULTISTATUS:
        raise InvalidResponseError(f"Expected DAV: multistatus, got {root.tag!r}")
    return [_parse_response(element) for element in root.findall(RESPONSE)]


def parse_status_line(text: str | None) -> int:
    """``"HTTP/1.1 200 OK"`` -> ``200``."""
    parts = (text or "").split()
    if (
        len(parts) < 2
        or not parts[0].startswith("HTTP/")
        or len(parts[1]) != 3
        or not (parts[1].isascii() and parts[1].isdigit())
    ):
        raise InvalidResponseError(f"Invalid status line: {text!r}")
    return int(parts[1])


def _parse_response(element: ET.Element) -> PropfindResource:
    hrefs = element.findall(HREF)
    if len(hrefs) != 1 or not (hrefs[0].text or "").strip():
        raise InvalidResponseError("Each response needs exactly one non-empty href")
    href = (hrefs[0].text or "").strip()

    response_status = element.find(STATUS)
    if response_status is not None:
        code = parse_status_line(response_status.text)
        raise InvalidResponseError(
            f"Server reported status {code} for {href!r} instead of properties"
        )

    found: dict[str, ET.Element] = {}
    propstats = element.findall(PROPSTAT)
    if not propstats:
        raise InvalidResponseError(f"No propstat for {href!r}")
    for propstat in propstats:
        code = parse_status_line(_text_of(propstat.find(STATUS)))
        if not 200 <= code < 300:
            continue
        prop = propstat.find(PROP)
        if prop is None:
            raise InvalidResponseError(f"Successful propstat without prop: {href!r}")
        for child in prop:
            found[child.tag] = child

    resourcetype = found.get(RESOURCETYPE)
    if resourcetype is None:
        raise InvalidResponseError(f"No successful resourcetype for {href!r}")

    return PropfindResource(
        href=href,
        is_collection=resourcetype.find(COLLECTION) is not None,
        content_length=_number(found.get(GETCONTENTLENGTH), "getcontentlength", href),
        size=_size(found.get(OC_SIZE), href),
    )


def _size(element: ET.Element | None, href: str) -> int | None:
    # Nextcloud reports -1 for a folder size it has not computed yet.
    if _text_of(element).strip() == "-1":
        return None
    return _number(element, "size", href)


def _number(element: ET.Element | None, name: str, href: str) -> int | None:
    text = _text_of(element).strip()
    if not text:
        return None
    if not (text.isascii() and text.isdigit()):
        raise InvalidResponseError(f"Invalid {name} {text!r} for {href!r}")
    return int(text)


def _text_of(element: ET.Element | None) -> str:
    return "" if element is None else (element.text or "")
