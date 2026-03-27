"""Tests for the GUI API layer."""
from fastapi.testclient import TestClient

_TEST_PORT = 8765
_HOST_HEADER = {"host": f"localhost:{_TEST_PORT}"}


def _make_client():
    from tidal_dl.gui import create_app

    return TestClient(create_app(port=_TEST_PORT))


def test_app_factory_returns_fastapi_instance():
    client = _make_client()
    resp = client.get("/", headers=_HOST_HEADER)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "csrf-token" in resp.text


def test_static_css_served():
    client = _make_client()
    resp = client.get("/style.css", headers=_HOST_HEADER)
    assert resp.status_code == 200


def test_static_js_served():
    client = _make_client()
    resp = client.get("/app.js", headers=_HOST_HEADER)
    assert resp.status_code == 200


def test_static_js_does_not_force_single_tab_playback():
    client = _make_client()
    resp = client.get("/app.js", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert "BroadcastChannel('music-dl-player')" not in resp.text
    assert '_playerChannel.postMessage(\'pause\')' not in resp.text
