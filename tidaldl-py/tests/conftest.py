"""Shared pytest fixtures."""

import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_session_config_dir = tempfile.TemporaryDirectory(prefix="music-dl-pytest-")
os.environ["MUSIC_DL_CONFIG_DIR"] = _session_config_dir.name

from tidal_dl.config import reset_singletons


@pytest.fixture(autouse=True)
def isolate_test_config(tmp_path, monkeypatch):
    """Keep each test's configuration and singletons in its own temp directory."""
    from tidal_dl.download.api_pacing import reset_shared_pacer_for_tests

    monkeypatch.setenv("MUSIC_DL_CONFIG_DIR", str(tmp_path))
    reset_singletons()
    reset_shared_pacer_for_tests()
    yield
    reset_singletons()
    reset_shared_pacer_for_tests()


@pytest.fixture(autouse=False)
def clear_singletons():
    """Reset all singletons before and after each test that requests this fixture."""
    reset_singletons()
    yield
    reset_singletons()


@pytest.fixture
def library_scan_env(monkeypatch, tmp_path):
    """Point the library scanner at a temp music root and stub tag reads."""
    import tidal_dl.gui.api.library as lib
    from tests.library_scan_support import DURATIONS, fake_metadata

    root = tmp_path / "music"
    root.mkdir()

    class FakeSettings:
        data = SimpleNamespace(download_base_path=str(root), scan_paths="")

    monkeypatch.setattr(lib, "Settings", FakeSettings)
    monkeypatch.setattr(lib, "path_config_base", lambda: str(tmp_path))
    monkeypatch.setattr(lib, "_schedule_album_enrichment", lambda: None)
    monkeypatch.setattr(lib, "_album_cards", lambda db, *args, **kwargs: [])
    monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)
    monkeypatch.setattr(lib, "_has_local_art", lambda path: False)
    monkeypatch.setattr(lib, "_read_metadata", fake_metadata)
    lib._scan_running = False
    lib._reconcile_running = False
    lib._reconcile_last_at = 0.0
    lib._reconcile_progress = lib._new_reconcile_progress(phase="idle", done=True)
    lib._scan_progress = lib._new_scan_progress(phase="idle", done=True)
    DURATIONS.clear()
    yield lib, root, tmp_path
    lib._scan_running = False
    lib._reconcile_running = False


@pytest.fixture
def chmod_restore():
    """Restore modes changed by unlistable-directory tests."""
    touched: list[Path] = []
    yield touched
    for path in touched:
        os.chmod(path, 0o755)


@pytest.fixture
def client(tmp_path):
    """FastAPI TestClient with CSRF support."""
    from fastapi.testclient import TestClient

    from tidal_dl.gui import create_app
    with TestClient(create_app(port=8765, job_db_path=tmp_path / "jobs.db")) as c:
        c._host_header = {"host": "localhost:8765"}
        index = c.get("/", headers=c._host_header)
        match = re.search(r'name="csrf-token" content="([^"]+)"', index.text)
        c._csrf = match.group(1) if match else ""
        c._headers = {**c._host_header, "X-CSRF-Token": c._csrf}
        yield c
