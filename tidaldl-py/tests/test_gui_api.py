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


def test_index_does_not_contain_recently_added_sidebar_entry():
    client = _make_client()
    resp = client.get("/", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert "Recently Added" not in resp.text
    assert 'data-view="recent-added"' not in resp.text


def test_static_js_contains_recently_added_library_hooks():
    client = _make_client()
    resp = client.get("/app.js", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert "recent-added" in resp.text
    assert "/library/recent-albums" in resp.text
    assert "loadLibraryRecentAlbumsExpanded" in resp.text
    assert "See all" not in resp.text


def test_static_js_contains_recently_added_expanded_states():
    client = _make_client()
    resp = client.get("/app.js", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert "No recently added albums yet" in resp.text
    assert "Download music or sync your library to populate this view." in resp.text
    assert "Could not load recently added albums" in resp.text


def test_static_js_playlist_sync_updates_download_badge_and_sse():
    client = _make_client()
    resp = client.get("/app.js", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert "toast('Downloading ' + result.missing + ' missing tracks', 'success');\n            updateDlBadge(result.missing);\n            _ensureGlobalSSE();" in resp.text


def test_static_js_playlist_auto_upgrade_scan_present():
    client = _make_client()
    resp = client.get("/app.js", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert "Checking upgrades..." in resp.text
    assert "async function _scanPlaylistUpgrades(" in resp.text
    assert "if (!_setPlaylistUpgradeBadge(trackList, track, result.max_quality)) return;" in resp.text
    assert "upgradeBtn.textContent = 'Upgrade ' + allUpgradeable.length + ' Tracks';" in resp.text


def test_static_js_playlist_upgrade_refresh_control_present():
    client = _make_client()
    resp = client.get("/app.js", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert "album-upgrade-refresh-btn" in resp.text
    assert "Refresh upgrade availability" in resp.text
    assert "force: true" in resp.text
