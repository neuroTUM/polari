import httpx
import pytest

from dav_helpers import (
    ENCODED_ROOT_URL,
    ROOT_PATH,
    Recorder,
    dav_response,
    multistatus,
    respond_207,
)
from polari_storage import (
    InvalidResponseError,
    ListResult,
    NextcloudStorage,
    NotFoundError,
    ObjectInfo,
    UnexpectedStatusError,
    Version,
)
from polari_storage.propfind import PROPFIND_BODY

pytestmark = pytest.mark.anyio

TRIAL = "2026/p01/2026-11-14/trial_1"


def trial_listing() -> bytes:
    base = ROOT_PATH + TRIAL
    return multistatus(
        dav_response(base + "/", collection=True),
        dav_response(base + "/mapping.yaml%40000001/", collection=True, size=120),
        dav_response(base + "/calibration/", collection=True),
        dav_response(base + "/data.xdf%40000001/", collection=True, size=10),
        dav_response(base + "/data.xdf%40000002/", collection=True, size=1_048_576),
        dav_response(base + "/README.txt", length=5),  # not a version: ignored
    )


async def test_list_sends_propfind_depth_1(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(trial_listing())
    await storage.list_objects(TRIAL + "/", delimiter="/")

    request = recorder.last
    assert request.method == "PROPFIND"
    assert request.headers["Depth"] == "1"
    assert request.headers["Content-Type"].startswith("application/xml")
    assert request.content == PROPFIND_BODY
    assert str(request.url) == ENCODED_ROOT_URL + TRIAL + "/"


async def test_list_maps_files_and_folders(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(trial_listing())
    result = await storage.list_objects(TRIAL + "/", delimiter="/")
    assert sorted(result.objects, key=lambda o: o.key) == [
        ObjectInfo(f"{TRIAL}/data.xdf", 1_048_576, Version("2")),
        ObjectInfo(f"{TRIAL}/mapping.yaml", 120, Version("1")),
    ]
    assert result.common_prefixes == [f"{TRIAL}/calibration/"]


async def test_list_decodes_spaces_and_unicode(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(
        multistatus(
            dav_response(ROOT_PATH + "my%20data/", collection=True),
            dav_response(
                ROOT_PATH + "my%20data/%C3%BCber%20uns.json%40000001/",
                collection=True,
                size=2,
            ),
        )
    )
    result = await storage.list_objects("my data/", delimiter="/")
    assert recorder.last.url.raw_path == (ROOT_PATH + "my%20data/").encode()
    assert result == ListResult(
        [ObjectInfo("my data/über uns.json", 2, Version("1"))], []
    )


async def test_list_accepts_absolute_url_hrefs(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    host = "https://dav.example.test"
    recorder.handler = respond_207(
        multistatus(
            dav_response(host + ROOT_PATH + "d/", collection=True),
            dav_response(host + ROOT_PATH + "d/x.json@1/", collection=True, size=1),
        )
    )
    result = await storage.list_objects("d/", delimiter="/")
    assert result.objects == [ObjectInfo("d/x.json", 1, Version("1"))]


@pytest.mark.parametrize(
    "extra",
    [
        dav_response(ROOT_PATH + "d/sub/deeper.json", length=1),  # not direct child
        dav_response(ROOT_PATH + "other/x.json", length=1),  # sibling folder
        dav_response("/remote.php/dav/files/bob/x.json", length=1),  # outside root
        dav_response(ROOT_PATH + "d/", collection=True),  # duplicate self
        dav_response(ROOT_PATH, collection=True),  # root inside listing of "d"
    ],
)
async def test_list_rejects_unexpected_entries(
    storage: NextcloudStorage, recorder: Recorder, extra: str
) -> None:
    recorder.handler = respond_207(
        multistatus(dav_response(ROOT_PATH + "d/", collection=True), extra)
    )
    with pytest.raises(InvalidResponseError):
        await storage.list_objects("d/", delimiter="/")


async def test_list_without_self_entry_is_invalid(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(
        multistatus(dav_response(ROOT_PATH + "d/x.json", length=1))
    )
    with pytest.raises(InvalidResponseError, match="folder itself"):
        await storage.list_objects("d/")


async def test_list_malformed_xml(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(b"<d:multistatus xmlns:d='DAV:'>")
    with pytest.raises(InvalidResponseError, match="PROPFIND 'd'"):
        await storage.list_objects("d/")


async def test_propfind_200_instead_of_207_is_unexpected(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = lambda request: httpx.Response(200, text="<html>login</html>")
    with pytest.raises(UnexpectedStatusError) as info:
        await storage.list_objects("d/")
    assert info.value.status_code == 200


async def test_head_lists_the_parent_folder(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = respond_207(
        multistatus(
            dav_response(ROOT_PATH + "d/", collection=True),
            dav_response(ROOT_PATH + "d/a%20b.json%40000003/", collection=True, size=5),
            dav_response(ROOT_PATH + "d/other.json%40000009/", collection=True, size=1),
        )
    )
    info = await storage.head_object("d/a b.json")
    assert info == ObjectInfo("d/a b.json", 5, Version("3"))
    assert recorder.last.headers["Depth"] == "1"
    assert str(recorder.last.url) == ENCODED_ROOT_URL + "d/"


async def test_head_of_missing_folder(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    recorder.handler = lambda request: httpx.Response(404)
    with pytest.raises(NotFoundError):
        await storage.head_object("d/a.json")


async def test_unknown_folder_size_falls_back_to_the_data_file(
    storage: NextcloudStorage, recorder: Recorder
) -> None:
    version = ROOT_PATH + "d/a.json%40000002/"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.raw_path == version.encode():
            return httpx.Response(
                207,
                content=multistatus(
                    dav_response(version, collection=True, size=-1),
                    dav_response(version + "data", length=7),
                    dav_response(version + "writer-0123", length=0),
                ),
            )
        return httpx.Response(
            207,
            content=multistatus(
                dav_response(ROOT_PATH + "d/", collection=True),
                dav_response(version, collection=True, size=-1),
            ),
        )

    recorder.handler = handler
    assert await storage.head_object("d/a.json") == ObjectInfo(
        "d/a.json", 7, Version("2")
    )
    listing = await storage.list_objects("d/", delimiter="/")
    assert listing.objects == [ObjectInfo("d/a.json", 7, Version("2"))]
