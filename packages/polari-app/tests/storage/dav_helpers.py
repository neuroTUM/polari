"""Helpers that build synthetic WebDAV responses for tests.

Everything here is fake: no real server, account or research data.
"""

from collections.abc import Callable

import httpx

ROOT_URL = "https://dav.example.test/remote.php/dav/files/alice/polari/"
ROOT_PATH = "/remote.php/dav/files/alice/polari/"

Handler = Callable[[httpx.Request], httpx.Response]


class Recorder:
    """Records every request and answers with a configurable handler."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.handler: Handler = lambda request: httpx.Response(500)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return self.handler(request)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def multistatus(*responses: str, prefix: str = "d") -> bytes:
    """Build a 207 body; ``responses`` are inner ``<response>`` fragments."""
    inner = "".join(responses)
    return (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<{prefix}:multistatus xmlns:{prefix}="DAV:">{inner}</{prefix}:multistatus>'
    ).encode()


def dav_response(
    href: str,
    *,
    collection: bool = False,
    length: int | None = None,
    etag: str | None = None,
    prefix: str = "d",
) -> str:
    """One ``<response>`` like Nextcloud sends it (missing props -> 404 group)."""
    p = prefix
    found = [
        f"<{p}:resourcetype><{p}:collection/></{p}:resourcetype>"
        if collection
        else f"<{p}:resourcetype/>"
    ]
    missing = []
    if length is None:
        missing.append(f"<{p}:getcontentlength/>")
    else:
        found.append(f"<{p}:getcontentlength>{length}</{p}:getcontentlength>")
    if etag is None:
        missing.append(f"<{p}:getetag/>")
    else:
        found.append(f"<{p}:getetag>{etag}</{p}:getetag>")
    groups = (
        f"<{p}:propstat><{p}:prop>{''.join(found)}</{p}:prop>"
        f"<{p}:status>HTTP/1.1 200 OK</{p}:status></{p}:propstat>"
    )
    if missing:
        groups += (
            f"<{p}:propstat><{p}:prop>{''.join(missing)}</{p}:prop>"
            f"<{p}:status>HTTP/1.1 404 Not Found</{p}:status></{p}:propstat>"
        )
    return f"<{p}:response><{p}:href>{href}</{p}:href>{groups}</{p}:response>"


def respond_207(body: bytes) -> Handler:
    return lambda request: httpx.Response(207, content=body)
