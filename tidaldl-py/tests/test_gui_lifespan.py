"""Tests for FastAPI lifespan startup behavior."""

from __future__ import annotations

import warnings

from fastapi.testclient import TestClient

from tidal_dl.gui import create_app


class _FakeTidal:
    calls: list[bool] = []

    def login_token(self, quiet: bool = False) -> None:
        self.calls.append(quiet)


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


def test_create_app_restores_tidal_session_on_startup(monkeypatch):
    _FakeTidal.calls = []
    monkeypatch.setattr("tidal_dl.config.Tidal", _FakeTidal)

    with TestClient(create_app(port=8765)):
        pass

    assert _FakeTidal.calls == [True]


def test_create_app_ignores_tidal_restore_failures_on_startup(monkeypatch):
    class _BrokenTidal:
        def login_token(self, quiet: bool = False) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr("tidal_dl.config.Tidal", _BrokenTidal)

    with TestClient(create_app(port=8765)):
        pass


def test_health_returns_structured_daemon_state():
    with TestClient(create_app(port=8765)) as client:
        resp = client.get("/api/server/health", headers={"host": "localhost:8765"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == "music-dl"
    assert data["status"] == "ready"
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 8765
