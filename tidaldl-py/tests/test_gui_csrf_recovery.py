from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "app.js"


def test_api_client_recovers_from_stale_csrf_token():
    source = APP_JS.read_text()

    assert "let CSRF_TOKEN =" in source
    assert "async function refreshCsrfToken()" in source
    assert "Forbidden: invalid or missing CSRF token" in source
    assert "_csrfRetried: true" in source
