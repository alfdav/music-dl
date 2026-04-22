from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "app.js"


def test_tidal_auth_errors_launch_gui_login_flow():
    source = APP_JS.read_text()

    assert "function _isTidalAuthError(error)" in source
    assert "error.status === 401" in source
    assert "error.detail.toLowerCase().includes('not logged in to tidal')" in source
    assert "async function apiTidal(path, options)" in source
    assert "toast('Tidal login required — opening sign-in…', 'error');" in source
    assert "triggerLogin();" in source
    assert "tidalData = await apiTidal('/search?" in source
    assert "await apiTidal('/download', {" in source


def test_settings_auth_status_offers_gui_login_button():
    source = APP_JS.read_text()

    assert "document.createTextNode('Not logged in to Tidal')" in source
    assert "textEl('button', 'Log in to Tidal', 'banner-action')" in source
    assert "loginBtn.addEventListener('click', () => { triggerLogin(); });" in source


def test_successful_login_acknowledges_and_clears_auth_banner():
    source = APP_JS.read_text()

    assert "function _handleLoginSuccess()" in source
    assert "refreshStatusLights();" in source
    assert "await _checkErrorBanners();" in source
    assert "toast('Connected to Tidal', 'success');" in source
    assert "const authSection = document.getElementById('settings-auth-status');" in source
    assert "if (authSection) await loadAuthStatus(authSection);" in source
    assert "if (data.status === 'already_logged_in') {" in source
    assert "await _handleLoginSuccess();" in source
    assert "if (status.status === 'success') {" in source
