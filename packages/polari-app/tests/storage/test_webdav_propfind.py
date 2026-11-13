"""list_directory() and get_metadata() against a mocked WebDAV server."""

import httpx
import pytest

from dav_helpers import (
    ROOT_PATH,
    ROOT_URL,
    Recorder,
    dav_response,
    multistatus,
    respond_207,
)
from polari_app.storage import (
    InvalidPathError,
    InvalidResponseError,
    NotACollectionError,
    NotFoundError,
    RemoteEntry,
    UnexpectedStatusError,
    WebDAVStorage,
)
from polari_app.storage.propfind import PROPFIND_BODY

pytestmark = pytest.mark.anyio

TRIAL = "2026/p01/2026-11-14/trial_1"


def trial_listing() -> bytes:
    base = ROOT_PATH + TRIAL
    return multistatus(
        dav_response(base + "/", collection=True, etag='"dir-etag"'),
        dav_response(base + "/mapping.yaml", length=120, etag='"m1"'),
        dav_response(base + "/calibration/", collection=True),
        dav_response(base + "/data.xdf", length=1_048_576, etag='"x1"'),
    )


async def test_list_sends_propfind_depth_1(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(trial_listing())
    await storage.list_directory(TRIAL)

    request = recorder.last
    assert request.method == "PROPFIND"
    assert request.headers["Depth"] == "1"
    assert request.headers["Content-Type"].startswith("application/xml")
    assert request.content == PROPFIND_BODY
    assert str(request.url) == ROOT_URL + TRIAL + "/"


async def test_list_returns_direct_children_without_self(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(trial_listing())
    entries = await storage.list_directory(TRIAL)

    assert entries == [
        RemoteEntry(f"{TRIAL}/calibration", "calibration", True, None, None),
        RemoteEntry(f"{TRIAL}/data.xdf", "data.xdf", False, 1_048_576, '"x1"'),
        RemoteEntry(f"{TRIAL}/mapping.yaml", "mapping.yaml", False, 120, '"m1"'),
    ]
    assert TRIAL not in [entry.path for entry in entries]


async def test_list_root_directory(storage: WebDAVStorage, recorder: Recorder) -> None:
    recorder.handler = respond_207(
        multistatus(
            dav_response(ROOT_PATH, collection=True),
            dav_response(ROOT_PATH + "2026/", collection=True),
        )
    )
    entries = await storage.list_directory("")
    assert entries == [RemoteEntry("2026", "2026", True)]
    assert str(recorder.last.url) == ROOT_URL


async def test_empty_directory_returns_empty_list(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(
        multistatus(dav_response(ROOT_PATH + "empty/", collection=True))
    )
    assert await storage.list_directory("empty") == []


async def test_missing_directory_raises_not_found(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = lambda request: httpx.Response(404)
    with pytest.raises(NotFoundError) as info:
        await storage.list_directory("missing")
    assert info.value.status_code == 404
    assert info.value.path == "missing"


async def test_list_on_file_raises_not_a_collection(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(
        multistatus(dav_response(ROOT_PATH + "a.json", length=3))
    )
    with pytest.raises(NotACollectionError):
        await storage.list_directory("a.json")


async def test_list_encodes_spaces_and_unicode(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(
        multistatus(
            dav_response(ROOT_PATH + "my%20data/", collection=True),
            dav_response(ROOT_PATH + "my%20data/%C3%BCber%20uns.json", length=2),
        )
    )
    entries = await storage.list_directory("my data")
    expected_raw_path = ROOT_PATH.encode() + b"my%20data/"
    assert recorder.last.url.raw_path == expected_raw_path
    assert entries == [RemoteEntry("my data/über uns.json", "über uns.json", False, 2)]


async def test_list_accepts_absolute_url_hrefs(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    host = "https://dav.example.test"
    recorder.handler = respond_207(
        multistatus(
            dav_response(host + ROOT_PATH + "d/", collection=True),
            dav_response(host + ROOT_PATH + "d/x.json", length=1),
        )
    )
    assert await storage.list_directory("d") == [
        RemoteEntry("d/x.json", "x.json", False, 1)
    ]


@pytest.mark.parametrize(
    "extra",
    [
        dav_response(ROOT_PATH + "d/sub/deeper.json", length=1),  # not direct child
        dav_response(ROOT_PATH + "other/x.json", length=1),  # sibling directory
        dav_response("/remote.php/dav/files/bob/x.json", length=1),  # outside root
        dav_response(ROOT_PATH + "d/", collection=True),  # duplicate self
        dav_response(ROOT_PATH, collection=True),  # root inside listing of "d"
    ],
)
async def test_list_rejects_unexpected_entries(
    storage: WebDAVStorage, recorder: Recorder, extra: str
) -> None:
    recorder.handler = respond_207(
        multistatus(dav_response(ROOT_PATH + "d/", collection=True), extra)
    )
    with pytest.raises(InvalidResponseError):
        await storage.list_directory("d")


async def test_list_without_self_entry_is_invalid(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(
        multistatus(dav_response(ROOT_PATH + "d/x.json", length=1))
    )
    with pytest.raises(InvalidResponseError, match="itself missing"):
        await storage.list_directory("d")


async def test_list_malformed_xml(storage: WebDAVStorage, recorder: Recorder) -> None:
    recorder.handler = respond_207(b"<d:multistatus xmlns:d='DAV:'>")
    with pytest.raises(InvalidResponseError, match="PROPFIND 'd'"):
        await storage.list_directory("d")


async def test_propfind_200_instead_of_207_is_unexpected(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = lambda request: httpx.Response(200, text="<html>login</html>")
    with pytest.raises(UnexpectedStatusError) as info:
        await storage.list_directory("d")
    assert info.value.status_code == 200


async def test_list_rejects_traversal_before_any_request(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    with pytest.raises(InvalidPathError):
        await storage.list_directory("../bob")
    assert recorder.requests == []


async def test_metadata_sends_depth_0_for_file(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(
        multistatus(dav_response(ROOT_PATH + "a%20b.json", length=5, etag='"e"'))
    )
    entry = await storage.get_metadata("a b.json")

    assert entry == RemoteEntry("a b.json", "a b.json", False, 5, '"e"')
    assert recorder.last.method == "PROPFIND"
    assert recorder.last.headers["Depth"] == "0"
    assert str(recorder.last.url) == ROOT_URL + "a%20b.json"


async def test_metadata_for_directory(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(
        multistatus(dav_response(ROOT_PATH + "2026/", collection=True, etag='"d"'))
    )
    assert await storage.get_metadata("2026/") == RemoteEntry(
        "2026", "2026", True, None, '"d"'
    )


async def test_metadata_for_root(storage: WebDAVStorage, recorder: Recorder) -> None:
    recorder.handler = respond_207(
        multistatus(dav_response(ROOT_PATH, collection=True))
    )
    assert await storage.get_metadata("") == RemoteEntry("", "", True)
    assert str(recorder.last.url) == ROOT_URL


async def test_metadata_missing_optional_props(
    storage: WebDAVStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(multistatus(dav_response(ROOT_PATH + "a.json")))
    entry = await storage.get_metadata("a.json")
    assert entry.content_length is None
    assert entry.etag is None


async def test_metadata_not_found(storage: WebDAVStorage, recorder: Recorder) -> None:
    recorder.handler = lambda request: httpx.Response(404)
    with pytest.raises(NotFoundError):
        await storage.get_metadata("nope.json")


@pytest.mark.parametrize(
    "body",
    [
        multistatus(),
        multistatus(dav_response(ROOT_PATH + "other.json")),
        multistatus(
            dav_response(ROOT_PATH + "a.json"), dav_response(ROOT_PATH + "a.json")
        ),
    ],
)
async def test_metadata_requires_exactly_the_requested_entry(
    storage: WebDAVStorage, recorder: Recorder, body: bytes
) -> None:
    recorder.handler = respond_207(body)
    with pytest.raises(InvalidResponseError):
        await storage.get_metadata("a.json")


async def test_root_url_without_trailing_slash_and_encoded_root() -> None:
    recorder = Recorder()
    recorder.handler = respond_207(
        multistatus(
            dav_response("/dav/my%20root/", collection=True),
            dav_response("/dav/my%20root/a.json", length=1),
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as client:
        storage = WebDAVStorage("https://dav.example.test/dav/my%20root", client)
        entries = await storage.list_directory("")
    assert str(recorder.last.url) == "https://dav.example.test/dav/my%20root/"
    assert entries == [RemoteEntry("a.json", "a.json", False, 1)]
