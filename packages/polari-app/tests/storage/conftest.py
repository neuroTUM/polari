"""Shared fixtures for storage tests.

No test talks to a real server. ``httpx.MockTransport`` calls a Python
function instead of opening a socket; ``.test`` hosts can never resolve.
Async tests run through the ``anyio`` pytest plugin (installed with httpx).
"""

from collections.abc import AsyncIterator

import httpx
import pytest

from dav_helpers import ROOT_URL, Recorder
from polari_app.storage import WebDAVStorage


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
async def storage(recorder: Recorder) -> AsyncIterator[WebDAVStorage]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(recorder)) as client:
        yield WebDAVStorage(ROOT_URL, client)
