"""Phase 0/1 Tidal auth v2: crash-safe writes, single-flight, no auto-login."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _legacy_token(access="live-access-1-7-11", refresh="live-refresh-1-7-11", *, expiry=None, pretty=True):
    payload = {
        "token_type": "Bearer",
        "access_token": access,
        "refresh_token": refresh,
        "expiry_time": expiry if expiry is not None else time.time() + 36000,
        "account_quality": "HI_RES",
    }
    if pretty:
        return json.dumps(payload, indent=4)
    return json.dumps(payload)


def test_atomic_write_crash_before_rename_keeps_original(tmp_path, monkeypatch):
    from tidal_dl.helper.atomic_io import atomic_write_text

    dest = tmp_path / "token.json"
    dest.write_text(_legacy_token(), encoding="utf-8")
    original = dest.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr("tidal_dl.helper.atomic_io.os.replace", boom)
    with pytest.raises(OSError, match="simulated crash"):
        atomic_write_text(dest, _legacy_token(access="new-access", refresh="new-refresh"))

    assert dest.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("token.json.tmp-*"))


def test_atomic_write_uses_0600_from_creation(tmp_path):
    from tidal_dl.helper.atomic_io import atomic_write_text

    dest = tmp_path / "token.json"
    atomic_write_text(dest, '{"refresh_token":"r"}')
    assert oct(dest.stat().st_mode & 0o777) == "0o600"


def test_token_persist_crash_before_rename_keeps_working_file(tmp_path, monkeypatch):
    from tidal_dl.config import Tidal

    token_path = tmp_path / "token.json"
    token_path.write_text(_legacy_token(), encoding="utf-8")
    tidal = Tidal()
    tidal.file_path = str(token_path)
    tidal.path_base = str(tmp_path)
    tidal.session.access_token = "rotated-access"
    tidal.session.refresh_token = "rotated-refresh"
    tidal.session.token_type = "Bearer"
    tidal.session.expiry_time = time.time() + 3600

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr("tidal_dl.helper.atomic_io.os.replace", boom)
    with pytest.raises(OSError, match="simulated crash"):
        tidal.token_persist()

    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "live-refresh-1-7-11"
    assert saved["access_token"] == "live-access-1-7-11"


def test_corrupt_primary_restores_valid_bak(tmp_path):
    from tidal_dl.config import Tidal, reset_singletons

    reset_singletons()
    token_path = tmp_path / "token.json"
    bak = tmp_path / "token.json.bak"
    token_path.write_text("{not-json", encoding="utf-8")
    bak.write_text(_legacy_token(), encoding="utf-8")

    tidal = Tidal()
    assert tidal.data.refresh_token == "live-refresh-1-7-11"
    restored = json.loads(token_path.read_text(encoding="utf-8"))
    assert restored["refresh_token"] == "live-refresh-1-7-11"
    assert bak.is_file()
    assert "live-refresh-1-7-11" in bak.read_text(encoding="utf-8")


def test_both_bad_does_not_write_empty_token_or_discard_bak(tmp_path):
    from tidal_dl.config import Tidal, reset_singletons

    reset_singletons()
    token_path = tmp_path / "token.json"
    bak = tmp_path / "token.json.bak"
    token_path.write_text("{broken", encoding="utf-8")
    bak.write_text("{also-broken", encoding="utf-8")

    tidal = Tidal()
    assert not tidal.data.refresh_token
    assert not tidal.data.access_token
    assert token_path.read_text(encoding="utf-8") == "{broken"
    assert bak.read_text(encoding="utf-8") == "{also-broken"


def test_upgrade_keeps_1_7_11_token_without_rewrite_or_oauth(tmp_path, monkeypatch):
    from tidal_dl.config import Tidal, reset_singletons
    from tidal_dl.gui import create_app
    from fastapi.testclient import TestClient

    reset_singletons()
    body = _legacy_token()
    token_path = tmp_path / "token.json"
    token_path.write_text(body, encoding="utf-8")

    oauth_calls = []

    def boom_oauth(self, *args, **kwargs):
        oauth_calls.append("login_oauth")
        raise AssertionError("upgrade must not start login_oauth")

    def boom_refresh(self, refresh_token):
        raise AssertionError("unexpired 1.7.11 token must not refresh")

    monkeypatch.setattr("tidalapi.session.Session.login_oauth", boom_oauth)
    monkeypatch.setattr("tidalapi.session.Session.token_refresh", boom_refresh)

    tidal = Tidal()
    assert tidal.data.refresh_token == "live-refresh-1-7-11"
    assert tidal.data.access_token == "live-access-1-7-11"
    assert token_path.read_text(encoding="utf-8") == body

    app = create_app(port=8765, job_db_path=tmp_path / "jobs.db")
    headers = {"host": "localhost:8765", "X-Music-DL-UI": app.state.ui_secret}
    with TestClient(app) as client:
        resp = client.get("/api/auth/status", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["auth_state"] == "credentials_ready"
    assert "access_token" not in payload
    assert "refresh_token" not in payload
    assert token_path.read_text(encoding="utf-8") == body
    assert oauth_calls == []


def test_single_flight_refresh_one_call_for_concurrent_threads(tmp_path):
    from tidal_dl.config import Tidal, reset_singletons

    reset_singletons()
    token_path = tmp_path / "token.json"
    token_path.write_text(_legacy_token(expiry=time.time() - 60), encoding="utf-8")
    tidal = Tidal()
    refreshes = []
    lock = threading.Lock()

    def refresh(token):
        with lock:
            refreshes.append(token)
        time.sleep(0.05)
        tidal.session.access_token = "fresh-access"
        tidal.session.refresh_token = token
        tidal.session.token_type = "Bearer"
        tidal.session.expiry_time = time.time() + 3600
        return True

    tidal.session.token_refresh = refresh
    tidal.session.token_type = "Bearer"
    tidal.session.access_token = "stale"
    tidal.session.refresh_token = "live-refresh-1-7-11"
    tidal.session.expiry_time = time.time() - 60

    results = []

    def worker():
        results.append(tidal._ensure_token_fresh(refresh_window_sec=300))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert refreshes == ["live-refresh-1-7-11"]
    assert results.count(True) >= 1


def test_auth_login_without_confirm_never_starts_oauth():
    from tidal_dl.gui.api import settings as settings_api

    calls = []

    class Session:
        refresh_token = "dead-refresh"

        def check_login(self):
            return False

        def login_oauth(self):
            calls.append("login_oauth")
            raise AssertionError("login_oauth without confirm")

        def token_refresh(self, refresh_token):
            calls.append(("token_refresh", refresh_token))
            return False

    class Tidal:
        session = Session()
        data = SimpleNamespace(
            access_token="expired-access",
            refresh_token="dead-refresh",
            expiry_time=time.time() - 60,
            account_quality=None,
        )

        def _ensure_token_fresh(self, refresh_window_sec=300):
            calls.append("ensure")
            self._last_refresh_outcome = "rejected"
            return False

        def refresh_api_keys(self):
            calls.append("refresh_api_keys")

    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "idle"})
    result = settings_api.auth_login(Tidal(), confirm=False)
    assert result["auth_state"] == "needs_attention"
    assert "login_oauth" not in calls
    assert "refresh_api_keys" not in calls


def test_auth_login_confirm_starts_device_code():
    from tidal_dl.gui.api import settings as settings_api

    class Session:
        def check_login(self):
            return False

        def login_oauth(self):
            return (
                SimpleNamespace(
                    verification_uri_complete="login.tidal.com/device",
                    user_code="ABCD",
                    expires_in=300,
                ),
                SimpleNamespace(result=lambda timeout=None: threading.Event().wait(60)),
            )

    class Tidal:
        session = Session()
        data = SimpleNamespace(access_token=None, refresh_token=None, expiry_time=0)

        def refresh_api_keys(self):
            return None

        def _ensure_token_fresh(self, refresh_window_sec=300):
            return False

    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "idle"})
    result = settings_api.auth_login(Tidal(), confirm=True)
    assert result["status"] == "pending"
    assert result["user_code"] == "ABCD"


def test_rejected_refresh_is_needs_attention_not_oauth(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from tidal_dl.gui.api import settings as settings_api

    class Session:
        def check_login(self):
            return False

        def login_oauth(self):
            raise AssertionError("401 retry started login_oauth")

        def search(self, *args, **kwargs):
            raise HTTPException(status_code=401, detail="unauthorized")

    class Tidal:
        session = Session()
        data = SimpleNamespace(
            access_token="stale",
            refresh_token="dead-refresh",
            expiry_time=time.time() + 10,
        )

        def _ensure_token_fresh(self, refresh_window_sec=300):
            self._last_refresh_outcome = "rejected"
            return False

    with pytest.raises(HTTPException) as exc:
        settings_api.call_tidal(Tidal(), lambda: (_ for _ in ()).throw(HTTPException(status_code=401, detail="x")))
    detail = exc.value.detail
    if isinstance(detail, dict):
        assert detail["auth_state"] == "needs_attention"
        assert "not logged in" not in detail.get("message", "").lower()
    else:
        assert "needs attention" in str(detail).lower()
    assert exc.value.status_code == 401


def test_cli_dl_does_not_open_browser_login(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from tidal_dl.cli import app
    from tidal_dl.config import reset_singletons

    reset_singletons()
    oauth = []

    def boom_oauth(self, *args, **kwargs):
        oauth.append("login_oauth")
        raise AssertionError("dl started login_oauth")

    monkeypatch.setattr("tidalapi.session.Session.login_oauth", boom_oauth)
    monkeypatch.setattr(
        "tidal_dl.config.Tidal.refresh_api_keys",
        lambda self, timeout=None: False,
    )
    runner = CliRunner()
    result = runner.invoke(app, ["dl", "https://tidal.com/browse/track/1"])
    assert result.exit_code != 0
    assert "music-dl login" in result.output
    assert oauth == []


def test_api_rejects_missing_secret_and_bad_host(tmp_path):
    from fastapi.testclient import TestClient

    from tidal_dl.gui import create_app

    app = create_app(port=8765, job_db_path=tmp_path / "jobs.db")
    with TestClient(app) as client:
        missing = client.get("/api/auth/status", headers={"host": "localhost:8765"})
        assert missing.status_code == 403
        bad_host = client.get(
            "/api/auth/status",
            headers={"host": "evil.com", "X-Music-DL-UI": app.state.ui_secret},
        )
        assert bad_host.status_code == 403
        wrong_port = client.get(
            "/api/auth/status",
            headers={"host": "localhost:9", "X-Music-DL-UI": app.state.ui_secret},
        )
        assert wrong_port.status_code == 403
        ok = client.get(
            "/api/auth/status",
            headers={"host": "localhost:8765", "X-Music-DL-UI": app.state.ui_secret},
        )
        assert ok.status_code == 200
        assert "access_token" not in ok.json()
        index = client.get("/", headers={"host": "localhost:8765"})
        assert index.status_code == 200
        assert "csrf-token" not in index.text or 'content=""' in index.text
        assert app.state.ui_secret not in index.text


def test_redact_tokens_from_text():
    from tidal_dl.helper.redact import redact_secrets

    raw = (
        'Bearer abc.def.ghi refresh_token=super-secret '
        '{"access_token":"tok123","refresh_token":"ref456","user_code":"ABCD"}'
    )
    redacted = redact_secrets(raw)
    assert "tok123" not in redacted
    assert "ref456" not in redacted
    assert "super-secret" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "[REDACTED]" in redacted


def test_js_api_tidal_does_not_autologin():
    from tests.gui_js_source import read_gui_js

    source = read_gui_js()
    api_tidal = source.split("async function apiTidal(path, options) {")[1].split("\nfunction ")[0]
    assert "triggerLogin()" not in api_tidal
    assert "needs attention" in source.lower()
    assert "confirm: true" in source or "confirm:true" in source
    assert "This signs this device out of Tidal" in source
    assert "next Connect adds a new device session" in source


def test_cross_process_lock_serializes_refresh(tmp_path):
    from tidal_dl.helper.atomic_io import exclusive_file_lock, token_lock_path

    lock = token_lock_path(tmp_path / "token.json")
    counter = tmp_path / "refreshes.txt"
    counter.write_text("0", encoding="utf-8")

    code = f"""
import time
from pathlib import Path
from tidal_dl.helper.atomic_io import exclusive_file_lock
lock = Path({str(lock)!r})
counter = Path({str(counter)!r})
with exclusive_file_lock(lock):
    n = int(counter.read_text())
    time.sleep(0.08)
    if n == 0:
        counter.write_text("1")
"""

    import subprocess
    import sys

    procs = [
        subprocess.Popen([sys.executable, "-c", code])
        for _ in range(2)
    ]
    for proc in procs:
        proc.wait(timeout=10)
    assert all(proc.returncode == 0 for proc in procs)
    assert counter.read_text(encoding="utf-8") == "1"


def test_bind_all_requires_ui_secret(monkeypatch):
    from tidal_dl.gui.daemon import DaemonMetadata, make_uvicorn_config

    monkeypatch.delenv("MUSIC_DL_UI_SECRET", raising=False)
    meta = DaemonMetadata.for_current_process(port=8765, mode="browser")
    with pytest.raises(RuntimeError, match="MUSIC_DL_UI_SECRET"):
        make_uvicorn_config(meta, bind_all=True)
