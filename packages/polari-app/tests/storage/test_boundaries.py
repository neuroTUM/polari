"""Architecture boundaries of the storage package."""

import ast
import subprocess
import sys
from pathlib import Path

import httpx

import polari_app.storage
from polari_app.storage import RemoteStorage, WebDAVStorage, create_http_client

STORAGE_DIR = Path(polari_app.storage.__file__).parent
FORBIDDEN_TOP_LEVEL = {"PySide6", "PyQt6", "PyQt5", "shiboken6"}


def test_import_does_not_load_gui_or_experiment_modules() -> None:
    # A fresh interpreter, so modules imported by other tests do not count.
    code = (
        "import sys, polari_app.storage\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in "
        f"{sorted(FORBIDDEN_TOP_LEVEL)!r} or m.startswith('polari_app.experiment'))\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


def test_source_has_no_forbidden_imports() -> None:
    for source in STORAGE_DIR.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in FORBIDDEN_TOP_LEVEL, source
                assert not name.startswith("polari_app.experiment"), source
                if name.startswith("polari_app"):
                    assert name.startswith("polari_app.storage"), source


def test_webdav_storage_satisfies_protocol() -> None:
    # Checked statically by mypy; at runtime we check the method names.
    storage: RemoteStorage = WebDAVStorage(
        "https://dav.example.test/x/", httpx.AsyncClient()
    )
    for name in ("list_directory", "get_metadata", "read_file", "create_file"):
        assert callable(getattr(storage, name))


def test_create_http_client_configuration() -> None:
    client = create_http_client("alice", "not-a-real-password")
    assert isinstance(client.auth, httpx.BasicAuth)
    assert client.follow_redirects is False
    assert client.timeout == polari_app.storage.DEFAULT_TIMEOUT
