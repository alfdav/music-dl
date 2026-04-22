"""Tests for the /setup API endpoints."""

import pytest


class TestSetupStatus:
    def test_returns_200(self, client):
        resp = client.get("/api/setup/status", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/setup/status", headers=client._host_header)
        data = resp.json()
        assert "logged_in" in data
        assert "scan_paths_configured" in data
        assert "setup_complete" in data

    def test_logged_in_is_bool(self, client):
        resp = client.get("/api/setup/status", headers=client._host_header)
        data = resp.json()
        assert isinstance(data["logged_in"], bool)

    def test_scan_paths_configured_is_bool(self, client):
        resp = client.get("/api/setup/status", headers=client._host_header)
        data = resp.json()
        assert isinstance(data["scan_paths_configured"], bool)

    def test_setup_complete_is_bool(self, client):
        resp = client.get("/api/setup/status", headers=client._host_header)
        data = resp.json()
        assert isinstance(data["setup_complete"], bool)

    def test_setup_complete_reflects_logged_in_and_paths(self, client):
        """setup_complete must be True iff both logged_in and scan_paths_configured are True."""
        resp = client.get("/api/setup/status", headers=client._host_header)
        data = resp.json()
        expected = data["logged_in"] and data["scan_paths_configured"]
        assert data["setup_complete"] == expected


class TestSetupValidatePath:
    def test_valid_existing_directory(self, client):
        """A real directory under the user home should be accepted."""
        import tempfile
        from pathlib import Path

        # Use a directory under $HOME so macOS /private/var resolution doesn't
        # hit the /var forbidden path check.
        with tempfile.TemporaryDirectory(dir=Path.home()) as td:
            resp = client.post(
                "/api/setup/validate-path",
                json={"path": td},
                headers=client._headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is True
            assert data["reason"] is None

    def test_nonexistent_path_invalid(self, client):
        resp = client.post(
            "/api/setup/validate-path",
            json={"path": "/this/path/does/not/exist/at/all"},
            headers=client._headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["reason"] is not None

    def test_empty_path_returns_400(self, client):
        resp = client.post(
            "/api/setup/validate-path",
            json={"path": ""},
            headers=client._headers,
        )
        assert resp.status_code == 400

    def test_whitespace_only_path_returns_400(self, client):
        resp = client.post(
            "/api/setup/validate-path",
            json={"path": "   "},
            headers=client._headers,
        )
        assert resp.status_code == 400

    def test_forbidden_system_path_invalid(self, client):
        """System paths like /etc should be rejected."""
        resp = client.post(
            "/api/setup/validate-path",
            json={"path": "/etc"},
            headers=client._headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    def test_response_contains_resolved_path(self, client):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(dir=Path.home()) as td:
            resp = client.post(
                "/api/setup/validate-path",
                json={"path": td},
                headers=client._headers,
            )
            data = resp.json()
            assert "path" in data
            assert isinstance(data["path"], str)

    def test_requires_csrf_token(self, client):
        """POST without CSRF token must be rejected with 403."""
        from tidal_dl.gui import create_app
        from fastapi.testclient import TestClient

        c = TestClient(create_app(port=8765))
        resp = c.post(
            "/api/setup/validate-path",
            json={"path": "/tmp"},
            headers={"host": "localhost:8765"},
        )
        assert resp.status_code == 403
