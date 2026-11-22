from collections.abc import Callable
from typing import Literal
from urllib.parse import quote, unquote, urlsplit

import httpx

# A plain root URL as a user would type it; the space must get encoded.
ROOT_URL = "https://dav.example.test/remote.php/dav/files/alice/polari data"
ENCODED_ROOT_URL = "https://dav.example.test/remote.php/dav/files/alice/polari%20data/"
ROOT_PATH = "/remote.php/dav/files/alice/polari%20data/"

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
    size: int | None = None,
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
    oc = 'xmlns:oc="http://owncloud.org/ns"'
    if size is None:
        missing.append(f"<oc:size {oc}/>")
    else:
        found.append(f"<oc:size {oc}>{size}</oc:size>")
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


class FakeNextcloud:
    """An in-memory WebDAV folder that answers like Nextcloud 34.

    It knows nothing about versions: it stores plain files and folders
    (``a.json@000001/data``). It does not reproduce Nextcloud's races; those
    are covered by the live tests.
    """

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.folders: set[str] = {""}
        self.requests: list[httpx.Request] = []

    def add_file(self, path: str, content: bytes) -> None:
        for depth in range(path.count("/")):
            self.folders.add("/".join(path.split("/")[: depth + 1]))
        self.files[path] = content

    def add_version(self, key: str, number: int, content: bytes) -> None:
        self.add_file(f"{key}@{number:06d}/data", content)

    def versions(self) -> dict[str, list[int]]:
        """Version numbers per key, as ``NextcloudStorage`` lays them out."""
        found: dict[str, list[int]] = {}
        for folder in self.folders:
            key, _, number = folder.rpartition("@")
            if key and number.isdigit():
                found.setdefault(key, []).append(int(number))
        return {key: sorted(numbers) for key, numbers in found.items()}

    def objects(self) -> dict[str, bytes]:
        """The latest content of every object, as ``NextcloudStorage`` sees it."""
        return {
            key: self.files[f"{key}@{numbers[-1]:06d}/data"]
            for key, numbers in self.versions().items()
        }

    def methods(self) -> list[str]:
        return [request.method for request in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        path = _path_of(str(request.url))
        handler = getattr(self, "_" + request.method.lower())
        return handler(request, path)

    def _propfind(self, request: httpx.Request, path: str) -> httpx.Response:
        assert request.headers["Depth"] == "1"
        if path in self.files:
            return httpx.Response(207, content=multistatus(self._entry(path)))
        if path not in self.folders:
            return httpx.Response(404)
        children = [p for p in (*self.files, *self.folders) if p and _parent(p) == path]
        entries = [self._entry(p) for p in (path, *children)]
        return httpx.Response(207, content=multistatus(*entries))

    def _get(self, request: httpx.Request, path: str) -> httpx.Response:
        if path in self.folders:
            return httpx.Response(200, text="This is the WebDAV interface.")
        if path not in self.files:
            return httpx.Response(404)
        content = self.files[path]
        range_header = request.headers.get("Range")
        if range_header is None or not content:
            # Nextcloud ignores Range for empty files.
            return httpx.Response(200, content=content)
        start_text, _, end_text = range_header.removeprefix("bytes=").partition("-")
        start = int(start_text)
        if start >= len(content):
            return httpx.Response(416)
        end = int(end_text) + 1 if end_text else len(content)
        if end_text == "0":
            end = len(content)  # Nextcloud bug: "bytes=0-0" sends everything
        end = min(end, len(content))
        headers = {"Content-Range": f"bytes {start}-{end - 1}/{len(content)}"}
        return httpx.Response(206, headers=headers, content=content[start:end])

    def _put(self, request: httpx.Request, path: str) -> httpx.Response:
        if _parent(path) not in self.folders or path in self.folders:
            return httpx.Response(409)
        if request.headers.get("If-None-Match") == "*" and path in self.files:
            return httpx.Response(412)
        existed = path in self.files
        self.files[path] = request.content
        return httpx.Response(204 if existed else 201)

    def _mkcol(self, request: httpx.Request, path: str) -> httpx.Response:
        if path in self.folders or path in self.files:
            return httpx.Response(405)
        if _parent(path) not in self.folders:
            return httpx.Response(409)
        self.folders.add(path)
        return httpx.Response(201)

    def _delete(self, request: httpx.Request, path: str) -> httpx.Response:
        if path not in self.files and path not in self.folders:
            return httpx.Response(404)
        assert path != "", "DELETE of the root"
        self.files = {p: c for p, c in self.files.items() if not _within(p, path)}
        self.folders = {p for p in self.folders if not _within(p, path)}
        return httpx.Response(204)

    def _move(self, request: httpx.Request, path: str) -> httpx.Response:
        if path not in self.files and path not in self.folders:
            return httpx.Response(404)
        dest = _path_of(request.headers["Destination"])
        if dest in self.files or dest in self.folders:
            if request.headers.get("Overwrite") == "F":
                return httpx.Response(412)
            raise AssertionError("NextcloudStorage never overwrites with MOVE")
        if _parent(dest) not in self.folders:
            return httpx.Response(409)

        def moved(p: str) -> str:
            return dest + p[len(path) :]

        self.files = {
            moved(p) if _within(p, path) else p: c for p, c in self.files.items()
        }
        self.folders = {moved(p) if _within(p, path) else p for p in self.folders}
        return httpx.Response(201)

    def _entry(self, path: str) -> str:
        href = ROOT_PATH + "/".join(quote(level, safe="") for level in path.split("/"))
        if path in self.folders:
            size = sum(len(c) for p, c in self.files.items() if _within(p, path))
            return dav_response(href.rstrip("/") + "/", collection=True, size=size)
        content = self.files[path]
        return dav_response(href, length=len(content), size=len(content))


def _path_of(url: str) -> str:
    path = urlsplit(url).path
    assert path.startswith(ROOT_PATH.rstrip("/")), f"request outside root: {url}"
    return unquote(path.removeprefix(ROOT_PATH.rstrip("/"))).strip("/")


def _parent(path: str) -> str:
    return path.rpartition("/")[0]


def _within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


class Faulty:
    """Wraps a handler and fails one upcoming request on demand.

    The fault hits the next request whose method is in ``methods`` (any
    method if empty). ``"before"`` raises a connect error without passing the
    request on, so nothing can have changed. ``"after"`` lets the server
    handle the request and then raises a read timeout, as if the response got
    lost.
    """

    def __init__(self, server: Handler) -> None:
        self.server = server
        self.next_fault: Literal["before", "after"] | None = None
        self.methods: frozenset[str] = frozenset()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        fault = self.next_fault
        if fault is not None and (not self.methods or request.method in self.methods):
            self.next_fault = None
        else:
            fault = None
        if fault == "before":
            raise httpx.ConnectError("injected fault", request=request)
        response = self.server(request)
        if fault == "after":
            raise httpx.ReadTimeout("injected fault", request=request)
        return response
