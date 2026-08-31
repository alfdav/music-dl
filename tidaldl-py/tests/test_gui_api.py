"""Tests for the GUI API layer."""
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from tests.gui_js_source import GUI_JS_FILES

_TEST_PORT = 8765
_HOST_HEADER = {"host": f"localhost:{_TEST_PORT}"}


def _fetch_gui_js(client: TestClient) -> str:
    parts: list[str] = []
    for name in GUI_JS_FILES:
        resp = client.get(f"/{name}", headers=_HOST_HEADER)
        assert resp.status_code == 200
        parts.append(resp.text)
    return "".join(parts)


def _make_client():
    from tidal_dl.gui import create_app

    return TestClient(create_app(port=_TEST_PORT))


class _FakeTidalSession:
    def __init__(self, logged_in: bool, username: str = ""):
        self.logged_in = logged_in
        self.user = SimpleNamespace(name=username)

    def check_login(self) -> bool:
        raise AssertionError("auth status called provider-backed check_login")


class _UnavailableTidalSession:
    def check_login(self) -> bool:
        raise RuntimeError("Tidal session unavailable")


class _FakeTidal:
    def __init__(
        self,
        logged_in: bool,
        access_token: str | None,
        username: str = "",
        expiry_time: object | None = None,
    ):
        self.session = _FakeTidalSession(logged_in, username)
        if expiry_time is None:
            expiry_time = time.time() + 3600 if logged_in else time.time() - 60
        self.data = SimpleNamespace(
            access_token=access_token,
            refresh_token=None,
            expiry_time=expiry_time,
            account_quality="HI_RES" if logged_in else None,
        )


def _make_auth_client(tidal: _FakeTidal) -> TestClient:
    from tidal_dl.gui import create_app
    from tidal_dl.gui.api.settings import get_tidal_instance

    app = create_app(port=_TEST_PORT)
    app.dependency_overrides[get_tidal_instance] = lambda: tidal
    return TestClient(app)


def test_app_factory_returns_fastapi_instance():
    client = _make_client()
    resp = client.get("/", headers=_HOST_HEADER)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "csrf-token" in resp.text


def test_auth_state_reports_saved_unexpired_credentials():
    client = _make_auth_client(_FakeTidal(logged_in=True, access_token="token", username="Ada"))

    resp = client.get("/api/auth/status", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert resp.json() == {
        "logged_in": True,
        "username": "Ada",
        "auth_state": "credentials_ready",
        "account_quality": "HI_RES",
    }


def test_auth_state_reports_not_configured_without_persisted_token():
    client = _make_auth_client(_FakeTidal(logged_in=False, access_token=None))

    resp = client.get("/api/auth/status", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert resp.json() == {
        "logged_in": False,
        "username": "",
        "auth_state": "not_configured",
        "account_quality": None,
    }


def test_auth_state_reports_expired_with_persisted_token_and_failed_session():
    client = _make_auth_client(_FakeTidal(logged_in=False, access_token="expired-token"))

    resp = client.get("/api/auth/status", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert resp.json() == {
        "logged_in": False,
        "username": "",
        "auth_state": "expired",
        "account_quality": None,
    }


def test_auth_state_reports_unavailable_when_tidal_status_check_fails():
    tidal = _FakeTidal(logged_in=False, access_token="token", expiry_time=object())
    client = _make_auth_client(tidal)

    resp = client.get("/api/auth/status", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert resp.json() == {
        "logged_in": False,
        "username": "",
        "auth_state": "unavailable",
        "account_quality": None,
    }


def test_auth_status_uses_cached_account_quality_without_provider_refresh():
    tidal = _FakeTidal(logged_in=True, access_token="token", username="Ada")
    tidal.refresh_account_quality = lambda: (_ for _ in ()).throw(
        AssertionError("auth status must stay local")
    )
    client = _make_auth_client(tidal)

    resp = client.get("/api/auth/status", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert resp.json()["account_quality"] == "HI_RES"


def test_auth_account_refreshes_quality_when_logged_in():
    tidal = _FakeTidal(logged_in=True, access_token="token", username="Ada")
    tidal.refresh_account_quality = lambda: "LOSSLESS"
    client = _make_auth_client(tidal)

    resp = client.get("/api/auth/account", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert resp.json() == {
        "logged_in": True,
        "username": "Ada",
        "auth_state": "credentials_ready",
        "account_quality": "LOSSLESS",
    }


def test_auth_account_skips_provider_refresh_when_logged_out():
    tidal = _FakeTidal(logged_in=False, access_token=None)
    tidal.refresh_account_quality = lambda: (_ for _ in ()).throw(
        AssertionError("logged-out account refresh must stay local")
    )
    client = _make_auth_client(tidal)

    resp = client.get("/api/auth/account", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert resp.json()["auth_state"] == "not_configured"
    assert resp.json()["account_quality"] is None


def test_auth_reset_endpoint_uses_local_logout_only(client):
    from tidal_dl.gui.api.settings import get_tidal_instance

    class ResetTidal:
        def __init__(self):
            self.calls = []

        def logout(self):
            self.calls.append("logout")
            return True

    tidal = ResetTidal()
    client.app.dependency_overrides[get_tidal_instance] = lambda: tidal

    resp = client.post("/api/auth/reset", headers=client._headers)

    assert resp.status_code == 200
    assert resp.json() == {"status": "reset", "auth_state": "not_configured"}
    assert tidal.calls == ["logout"]


def test_static_css_served():
    client = _make_client()
    resp = client.get("/style.css", headers=_HOST_HEADER)
    assert resp.status_code == 200


def test_static_js_served():
    client = _make_client()
    for name in GUI_JS_FILES:
        resp = client.get(f"/{name}", headers=_HOST_HEADER)
        assert resp.status_code == 200


def test_static_js_does_not_force_single_tab_playback():
    client = _make_client()
    js = _fetch_gui_js(client)
    assert "BroadcastChannel('music-dl-player')" not in js
    assert '_playerChannel.postMessage(\'pause\')' not in js


def test_static_js_syncs_recently_played_from_server_memory():
    client = _make_client()
    js = _fetch_gui_js(client)
    assert "async function _syncRecentFromServer()" in js
    assert "api('/home/recent?limit=' + MAX_RECENT)" in js


def test_index_does_not_contain_recently_added_sidebar_entry():
    client = _make_client()
    resp = client.get("/", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert "Recently Added" not in resp.text
    assert 'data-view="recent-added"' not in resp.text


def test_static_js_contains_recently_added_library_hooks():
    client = _make_client()
    js = _fetch_gui_js(client)
    assert "recent-added" in js
    assert "/library/recent-albums" in js
    assert "loadLibraryRecentAlbumsExpanded" in js
    assert "See all" not in js


def test_static_js_contains_recently_added_expanded_states():
    client = _make_client()
    js = _fetch_gui_js(client)
    assert "No recently added albums yet" in js
    assert "Download music or sync your library to populate this view." in js
    assert "Could not load recently added albums" in js


def test_static_assets_include_album_grouping_review_hooks():
    client = _make_client()
    js = _fetch_gui_js(client)
    css = client.get("/style.css", headers=_HOST_HEADER).text

    assert "possible-duplicate-badge" in js
    assert "_openGroupingReview" in js
    assert "Group together" in js
    assert "Keep separate" in js
    assert "localrelease:" in js
    assert "const previousFocus = document.activeElement;" in js
    assert "event.key === 'Tab'" in js
    assert "previousFocus.focus()" in js
    assert "user_decision_superseded" in js
    assert "Cannot group" in js
    assert ".possible-duplicate-badge" in css
    assert ".grouping-review" in css


def test_static_js_leads_onboarding_with_local_music_folders():
    client = _make_client()
    js = _fetch_gui_js(client)
    setup_source = js.split("async function _checkSetup() {")[1].split(
        "function _renderWizard(setupData) {"
    )[0]
    wizard_source = js.split("function _renderWizard(setupData) {")[1].split(
        "function _teardownWizard() {"
    )[0]

    assert "if (_setupMustBlock(data))" in setup_source
    assert "hasAnySource" not in setup_source
    assert "if (!setupData.scan_paths_configured) {\n    _wizardStepPaths(wizard);" in wizard_source
    assert "_wizardStepLogin" not in wizard_source
    assert "Select your music folders" in js
    assert "Tidal is optional. Connect it later for catalog search, streaming, and downloads." in js


def test_static_js_requires_path_setup_when_tidal_is_connected():
    client = _make_client()
    js = _fetch_gui_js(client)
    setup_source = js.split("async function _checkSetup() {")[1].split(
        "function _renderWizard(setupData) {"
    )[0]

    assert "function _setupMustBlock(setupData) {\n  return !setupData.scan_paths_configured;\n}" in js
    assert "if (_setupMustBlock(data)) {\n      _renderWizard(data);\n      return true;" in setup_source
    assert "data.logged_in" not in setup_source


def test_static_js_offers_explicit_optional_tidal_connection_during_path_setup():
    client = _make_client()
    js = _fetch_gui_js(client)
    path_step_source = js.split("function _wizardStepPaths(wizard) {")[1].split(
        "// ---- ERROR BANNERS ----"
    )[0]

    assert "textEl('button', 'Connect Tidal', 'wizard-btn wizard-btn-secondary')" in path_step_source
    assert "connectTidalBtn.addEventListener('click', () => triggerLogin());" in path_step_source


def test_static_js_tidal_login_retry_copy_works_during_setup():
    client = _make_client()
    js = _fetch_gui_js(client)
    login_source = js.split("async function triggerLogin() {")[1].split("// ---- QUEUE PANEL ----")[0]

    assert "Tidal login timed out. Try Connect Tidal again." in login_source
    assert "Tidal login failed. Try Connect Tidal again." in login_source
    assert "Connection lost during login. Try Connect Tidal again." in login_source
    assert "Could not start Tidal login. Try Connect Tidal again." in login_source
    assert "tap the status light" not in login_source


def test_static_js_search_explains_tidal_auth_without_hiding_local_results():
    client = _make_client()
    js = _fetch_gui_js(client)
    search_source = js.split("async function doSearch(resultsArea) {")[1].split(
        "function renderSearchResults("
    )[0]
    search_view_source = js.split("function renderSearch(container) {")[1].split(
        "function _greeting() {"
    )[0]

    assert "api('/search?q='" in search_source
    assert "apiTidal('/search?q='" not in search_source
    assert "Promise.all([localP, tidalP])" in search_source
    assert "if (_isTidalAuthError(error)) {\n        tidalAuthRequired = true;\n      }" in search_source
    assert "state.searchResults = { query, type, local: localData, tidal: tidalData, tidalAuthRequired };" in search_source
    assert "renderUnifiedSearchResults(resultsArea, localData, tidalData, tidalAuthRequired);" in search_source
    assert "state.searchResults.tidalAuthRequired" in search_view_source
    assert "Connect Tidal to search, stream, and download" in search_source
    assert "connectButton.addEventListener('click', () => triggerLogin());" in search_source
    assert (
        "if (localItems.length === 0 && tidalItems.length === 0\n"
        "      && originalTidalItems.length === 0 && !tidalAuthRequired)"
    ) in search_source


def test_static_js_removes_unreachable_wizard_login_step():
    client = _make_client()
    js = _fetch_gui_js(client)

    assert "function _wizardStepLogin" not in js


def test_static_js_shows_tidal_session_banner_only_for_expired_auth():
    client = _make_client()
    js = _fetch_gui_js(client)
    banner_source = js.split("async function _checkErrorBanners() {")[1].split(
        "// Library views: check scan_paths"
    )[0]

    assert "function _authStateNeedsExpiredBanner(authState) {\n  return authState === 'expired';\n}" in js
    assert "if (_authStateNeedsExpiredBanner(auth.auth_state))" in banner_source
    assert "Tidal session expired." in banner_source


def test_static_js_playlist_sync_updates_download_badge_and_sse():
    client = _make_client()
    js = _fetch_gui_js(client)
    assert (
        "toast('Downloading ' + result.missing + ' missing tracks', 'success');\n"
        "            refreshDlBadge();\n"
        "            _ensureGlobalSSE();"
    ) in js


def test_static_js_playlist_auto_upgrade_scan_present():
    client = _make_client()
    js = _fetch_gui_js(client)
    assert "Checking upgrades..." in js
    assert "async function _scanPlaylistUpgrades(" in js
    assert "if (!_setPlaylistUpgradeBadge(trackList, track, result.max_quality)) return;" in js
    assert "upgradeBtn.textContent = 'Upgrade ' + allUpgradeable.length + ' Tracks';" in js


def test_static_js_playlist_upgrade_refresh_control_present():
    client = _make_client()
    js = _fetch_gui_js(client)
    assert "album-upgrade-refresh-btn" in js
    assert "Refresh upgrade availability" in js
    assert "force: true" in js
