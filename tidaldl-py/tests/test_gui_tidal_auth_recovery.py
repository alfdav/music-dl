from tests.gui_js_source import read_gui_js


def test_tidal_auth_errors_offer_explicit_catalog_login():
    source = read_gui_js()

    assert "function _isTidalAuthError(error)" in source
    assert "error.status === 401" in source
    assert "error.detail.toLowerCase().includes('not logged in to tidal')" in source
    assert "async function apiTidal(path, options)" in source
    assert "toast('Tidal login required — opening sign-in…', 'error');" in source
    assert "triggerLogin();" in source
    assert "api('/search?" in source
    assert "Connect Tidal to search, stream, and download" in source
    assert "connectButton.addEventListener('click', () => triggerLogin());" in source
    assert "await apiTidal('/download', {" in source


def test_settings_auth_status_offers_gui_login_button():
    source = read_gui_js()

    assert "if (data.auth_state === 'not_configured') return { label: 'log in', dot: 'disconnected' };" in source
    assert "const presentation = _tidalStatusPresentation(data);" in source
    assert "data.account_quality" in source
    assert "textEl('button', 'Log in to Tidal', 'banner-action')" in source
    assert "loginBtn.addEventListener('click', () => { triggerLogin(); });" in source
    assert "textEl('button', 'Reset Tidal connection', 'banner-action')" in source
    assert "_resetTidalConnection(container)" in source


def test_successful_login_acknowledges_and_clears_auth_banner():
    source = read_gui_js()

    assert "function _handleLoginSuccess()" in source
    assert "refreshStatusLights();" in source
    assert "await _checkErrorBanners();" in source
    assert "toast('Connected to Tidal', 'success');" in source
    assert "const authSection = document.getElementById('settings-auth-status');" in source
    assert "if (authSection) await loadAuthStatus(authSection);" in source
    assert "if (data.status === 'already_logged_in') {" in source
    assert "await _handleLoginSuccess();" in source
    assert "if (data.status === 'expired')" in source
    assert "if (status.status === 'success') {" in source


def test_gui_does_not_send_background_tidal_keepalive_requests():
    source = read_gui_js()

    assert "/auth/keepalive" not in source
