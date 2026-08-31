"""Tests for FastAPI lifespan startup behavior."""

from __future__ import annotations

import json
import threading
import time
import warnings
from pathlib import Path

from fastapi.testclient import TestClient

from tidal_dl.gui import create_app


def test_create_app_does_not_emit_on_event_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        create_app(port=8765)

    on_event_deprecations = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning)
        and "on_event" in str(w.message)
        and "deprecated" in str(w.message).lower()
    ]
    assert on_event_deprecations == []


def test_gui_lifespan_invokes_noninteractive_source_resolution(tmp_path):
    assert not (tmp_path / "token.json").exists()

    app = create_app(port=8765, job_db_path=tmp_path / "jobs.db")
    with TestClient(app) as client:
        response = client.get("/api/server/health", headers={"host": "localhost:8765"})
        _wait_for_source_restore(app)

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert app.state.source_restore_attempted is True
    assert app.state.source_restored is False
    assert app.state.source_restore_error is None


def test_health_returns_structured_daemon_state():
    with TestClient(create_app(port=8765)) as client:
        resp = client.get("/api/server/health", headers={"host": "localhost:8765"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == "music-dl"
    assert data["status"] == "ready"
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 8765
    assert data["base_url"] == "http://127.0.0.1:8765"
    assert data["health_url"] == "http://127.0.0.1:8765/api/server/health"


def _wait_for_source_restore(app, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(app.state, "source_restore_attempted", False):
            return
        time.sleep(0.01)
    raise AssertionError("Tidal restore was not attempted after ready")


def test_health_ready_does_not_wait_for_blocked_tidal_probe(tmp_path, monkeypatch):
    """Sidecar health must clear without waiting on a hanging Tidal probe."""
    entered = threading.Event()
    release = threading.Event()
    result: dict[str, object] = {}

    def hanging_resolve(self, *args, **kwargs):
        entered.set()
        release.wait(timeout=30)
        return False

    monkeypatch.setattr("tidal_dl.config.Tidal.resolve_source", hanging_resolve)

    app = create_app(port=8765, job_db_path=tmp_path / "jobs.db")

    def run_client() -> None:
        started = time.monotonic()
        with TestClient(app) as client:
            result["startup_ms"] = (time.monotonic() - started) * 1000
            result["response"] = client.get(
                "/api/server/health",
                headers={"host": "localhost:8765"},
            )

    worker = threading.Thread(target=run_client, name="lifespan-health-client")
    worker.start()
    worker.join(timeout=2.5)
    still_blocked = worker.is_alive()
    release.set()
    worker.join(timeout=2)

    assert still_blocked is False
    assert result.get("startup_ms", 10_000) < 2000
    response = result["response"]
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert entered.wait(timeout=1)


def test_lifespan_refreshes_persisted_token_on_start(tmp_path, monkeypatch):
    """Sidecar start must refresh from disk before any OAuth prompt."""
    ensure_calls = []

    def spy_ensure(self, refresh_window_sec=300):
        ensure_calls.append(refresh_window_sec)
        return False

    def spy_resolve(self, *args, **kwargs):
        assert kwargs.get("allow_interactive_login") is False
        return False

    monkeypatch.setattr("tidal_dl.config.Tidal._ensure_token_fresh", spy_ensure)
    monkeypatch.setattr("tidal_dl.config.Tidal.resolve_source", spy_resolve)

    app = create_app(port=8765, job_db_path=tmp_path / "jobs.db")
    with TestClient(app) as client:
        response = client.get("/api/server/health", headers={"host": "localhost:8765"})
        _wait_for_source_restore(app)

    assert response.status_code == 200
    assert ensure_calls
    assert any(window >= 1800 for window in ensure_calls)


def test_sidecar_start_after_binary_update_revives_refresh_token_without_oauth(tmp_path, monkeypatch):
    """First sidecar start of a new binary must revive token.json with no device-code OAuth.

    Tauri install_update replaces the app and restarts the sidecar. token.json lives
    outside the bundle (~/.config/music-dl). An expired access_token plus a still-valid
    refresh_token must become credentials_ready without login_oauth().
    """
    (tmp_path / "token.json").write_text(
        json.dumps(
            {
                "token_type": "Bearer",
                "access_token": "expired-access",
                "refresh_token": "persist-refresh",
                "expiry_time": time.time() - 120,
                "account_quality": "HI_RES",
            }
        ),
        encoding="utf-8",
    )

    oauth_calls: list[str] = []

    def boom_oauth(self, *args, **kwargs):
        oauth_calls.append("login_oauth")
        raise AssertionError("process start must not call login_oauth")

    def fake_refresh(self, refresh_token):
        self.token_type = "Bearer"
        self.access_token = "fresh-access"
        self.refresh_token = refresh_token
        self.expiry_time = time.time() + 3600
        return True

    monkeypatch.setattr("tidalapi.session.Session.login_oauth", boom_oauth)
    monkeypatch.setattr("tidalapi.session.Session.token_refresh", fake_refresh)
    monkeypatch.setattr("tidal_dl.config.Tidal.resolve_source", lambda self, *args, **kwargs: False)

    app = create_app(port=8765, job_db_path=tmp_path / "jobs.db")
    with TestClient(app) as client:
        _wait_for_source_restore(app)
        deadline = time.monotonic() + 2.0
        body = None
        while time.monotonic() < deadline:
            response = client.get("/api/auth/status", headers={"host": "localhost:8765"})
            assert response.status_code == 200
            body = response.json()
            if body.get("auth_state") == "credentials_ready":
                break
            time.sleep(0.05)

    assert oauth_calls == []
    assert body == {
        "logged_in": True,
        "username": "",
        "auth_state": "credentials_ready",
        "account_quality": "HI_RES",
    }


def test_install_update_does_not_touch_token_json():
    updater = Path(__file__).resolve().parents[1] / "src-tauri" / "src" / "updater.rs"
    source = updater.read_text(encoding="utf-8")
    assert "token.json" not in source
    assert "MUSIC_DL_CONFIG_DIR" not in source
    assert "path_config" not in source
    assert "install_update" in source


def test_tidal_restore_still_runs_after_ready(tmp_path, monkeypatch):
    """Quiet Tidal restore must still happen after health is ready."""
    restore_started = threading.Event()

    def spy_resolve(self, *args, **kwargs):
        restore_started.set()
        return False

    monkeypatch.setattr("tidal_dl.config.Tidal.resolve_source", spy_resolve)

    app = create_app(port=8765, job_db_path=tmp_path / "jobs.db")
    with TestClient(app) as client:
        response = client.get("/api/server/health", headers={"host": "localhost:8765"})
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert restore_started.wait(timeout=2)

    assert app.state.source_restore_attempted is True
    assert app.state.source_restored is False
    assert app.state.source_restore_error is None


def test_recover_download_jobs_runs_before_first_claim(tmp_path, monkeypatch):
    """Worker must not claim until recover_download_jobs has committed."""
    order: list[str] = []
    recovered = threading.Event()
    claimed = threading.Event()

    from tidal_dl.gui.services.download_job_service import DownloadJobService
    from tidal_dl.helper.library_db import LibraryDB

    original_recover = LibraryDB.recover_download_jobs
    original_claim = LibraryDB.claim_next_download_job

    def recover(self):
        result = original_recover(self)
        order.append("recover")
        recovered.set()
        return result

    def claim(self, *args, **kwargs):
        if recovered.is_set():
            order.append("claim")
            claimed.set()
        else:
            order.append("claim-before-recover")
            claimed.set()
        return original_claim(self, *args, **kwargs)

    monkeypatch.setattr(LibraryDB, "recover_download_jobs", recover)
    monkeypatch.setattr(LibraryDB, "claim_next_download_job", claim)

    db_path = tmp_path / "jobs.db"
    seeder = DownloadJobService(db_path=db_path, autostart=False)
    seeder.enqueue_download([4242])

    app = create_app(port=8765, job_db_path=db_path)
    with TestClient(app) as client:
        response = client.get("/api/server/health", headers={"host": "localhost:8765"})
        assert response.status_code == 200
        assert recovered.wait(timeout=2)
        claimed.wait(timeout=1)

    assert "recover" in order
    assert "claim-before-recover" not in order
    assert order.index("recover") == 0


def test_lifespan_does_not_scan_or_group_on_boot(tmp_path, monkeypatch):
    """Ready must not walk downloads or rebuild album cards."""

    def fail_scan(*_args, **_kwargs):
        raise AssertionError("lifespan must not scan downloads on boot")

    def fail_cards(*_args, **_kwargs):
        raise AssertionError("lifespan must not group albums on boot")

    monkeypatch.setattr(
        "tidal_dl.gui.services.download_job_service.scan_new_downloads",
        fail_scan,
    )
    monkeypatch.setattr("tidal_dl.gui.api.library._album_cards", fail_cards)

    app = create_app(port=8765, job_db_path=tmp_path / "jobs.db")
    with TestClient(app) as client:
        response = client.get("/api/server/health", headers={"host": "localhost:8765"})

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
