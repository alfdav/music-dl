"""Shared pytest fixtures."""

import os
import re
import tempfile

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
def client(tmp_path):
    """FastAPI TestClient with CSRF support."""
    from tidal_dl.gui import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(port=8765, job_db_path=tmp_path / "jobs.db")) as c:
        c._host_header = {"host": "localhost:8765"}
        index = c.get("/", headers=c._host_header)
        match = re.search(r'name="csrf-token" content="([^"]+)"', index.text)
        c._csrf = match.group(1) if match else ""
        c._headers = {**c._host_header, "X-CSRF-Token": c._csrf}
        yield c
