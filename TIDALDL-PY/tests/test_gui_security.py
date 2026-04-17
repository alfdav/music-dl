"""Security tests for the GUI server."""

import secrets

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_secured_app():
    """Create a minimal FastAPI app with security middleware for testing."""
    from tidal_dl.gui.security import CSRFMiddleware, HostValidationMiddleware

    app = FastAPI()
    csrf_token = secrets.token_urlsafe(32)
    app.state.csrf_token = csrf_token
    app.add_middleware(HostValidationMiddleware, allowed_hosts=["localhost:8765", "127.0.0.1:8765"])
    app.add_middleware(CSRFMiddleware, csrf_token=csrf_token)

    @app.get("/api/test")
    def test_read():
        return {"ok": True}

    @app.post("/api/test")
    def test_write():
        return {"ok": True}

    return app, csrf_token


class TestHostValidation:
    def test_allows_localhost(self):
        app, token = _create_secured_app()
        client = TestClient(app)
        resp = client.get("/api/test", headers={"Host": "localhost:8765", "X-CSRF-Token": token})
        assert resp.status_code == 200

    def test_allows_127(self):
        app, token = _create_secured_app()
        client = TestClient(app)
        resp = client.get("/api/test", headers={"Host": "127.0.0.1:8765", "X-CSRF-Token": token})
        assert resp.status_code == 200

    def test_rejects_foreign_host(self):
        app, token = _create_secured_app()
        client = TestClient(app)
        resp = client.get("/api/test", headers={"Host": "evil.com", "X-CSRF-Token": token})
        assert resp.status_code == 403

    def test_blocks_dns_rebinding(self):
        app, token = _create_secured_app()
        client = TestClient(app)
        resp = client.get("/api/test", headers={"Host": "attacker.localhost:8765", "X-CSRF-Token": token})
        assert resp.status_code == 403


class TestCSRF:
    def test_get_requests_pass_without_token(self):
        app, _ = _create_secured_app()
        client = TestClient(app)
        resp = client.get("/api/test", headers={"Host": "localhost:8765"})
        assert resp.status_code == 200

    def test_post_rejected_without_token(self):
        app, _ = _create_secured_app()
        client = TestClient(app)
        resp = client.post("/api/test", headers={"Host": "localhost:8765"})
        assert resp.status_code == 403

    def test_post_accepted_with_valid_token(self):
        app, token = _create_secured_app()
        client = TestClient(app)
        resp = client.post("/api/test", headers={"Host": "localhost:8765", "X-CSRF-Token": token})
        assert resp.status_code == 200

    def test_post_rejected_with_wrong_token(self):
        app, _ = _create_secured_app()
        client = TestClient(app)
        resp = client.post("/api/test", headers={"Host": "localhost:8765", "X-CSRF-Token": "wrong"})
        assert resp.status_code == 403


class TestPathValidation:
    def test_allows_audio_in_allowed_dir(self, tmp_path):
        from tidal_dl.gui.security import validate_audio_path

        audio = tmp_path / "track.flac"
        audio.write_bytes(b"fake")
        result = validate_audio_path(str(audio), [str(tmp_path)])
        assert result == audio.resolve()

    def test_rejects_outside_allowed_dir(self, tmp_path):
        from tidal_dl.gui.security import validate_audio_path

        result = validate_audio_path("/etc/passwd", [str(tmp_path)])
        assert result is None

    def test_rejects_non_audio_extension(self, tmp_path):
        from tidal_dl.gui.security import validate_audio_path

        bad = tmp_path / "secrets.json"
        bad.write_bytes(b"{}")
        result = validate_audio_path(str(bad), [str(tmp_path)])
        assert result is None

    def test_rejects_symlink_escape(self, tmp_path):
        from tidal_dl.gui.security import validate_audio_path

        target = tmp_path.parent / "outside.flac"
        target.write_bytes(b"fake")
        link = tmp_path / "escape.flac"
        link.symlink_to(target)

        result = validate_audio_path(str(link), [str(tmp_path)])
        assert result is None

    def test_rejects_dot_dot_traversal(self, tmp_path):
        from tidal_dl.gui.security import validate_audio_path

        path = str(tmp_path / ".." / ".." / "etc" / "passwd")
        result = validate_audio_path(path, [str(tmp_path)])
        assert result is None

    def test_rejects_nonexistent_file(self, tmp_path):
        from tidal_dl.gui.security import validate_audio_path

        result = validate_audio_path(str(tmp_path / "nope.flac"), [str(tmp_path)])
        assert result is None

    def test_library_resolver_allows_scanned_audio_outside_allowed_dirs(self, tmp_path):
        from tidal_dl.gui.security import resolve_library_audio_path

        outside = tmp_path.parent / "scanned.flac"
        outside.write_bytes(b"fake")

        result = resolve_library_audio_path(
            str(outside),
            [str(tmp_path)],
            trusted_library_path=outside.resolve(),
        )

        assert result == outside.resolve()

    def test_library_resolver_rejects_non_audio_even_when_scanned(self, tmp_path):
        from tidal_dl.gui.security import resolve_library_audio_path

        outside = tmp_path.parent / "scanned.txt"
        outside.write_text("fake")

        result = resolve_library_audio_path(
            str(outside),
            [str(tmp_path)],
            trusted_library_path=outside.resolve(),
        )

        assert result is None

    def test_validates_download_path_change(self):
        from pathlib import Path

        from tidal_dl.gui.security import validate_download_path

        # Home dir should be allowed
        assert validate_download_path(str(Path.home())) is True
        # System dirs should be rejected
        assert validate_download_path("/etc") is False
        assert validate_download_path("/usr/bin") is False
        # Nonexistent should be rejected
        assert validate_download_path("/nonexistent/path") is False


class TestStreamUrlValidation:
    def test_allows_tidal_cdn(self):
        from tidal_dl.gui.security import validate_stream_url

        assert validate_stream_url("https://sp-pr-cf.audio.tidal.com/some/path") is True
        assert validate_stream_url("https://fa-cf.audio.tidal.com/stream") is True

    def test_rejects_http(self):
        from tidal_dl.gui.security import validate_stream_url

        assert validate_stream_url("http://sp-pr-cf.audio.tidal.com/path") is False

    def test_rejects_unknown_host(self):
        from tidal_dl.gui.security import validate_stream_url

        assert validate_stream_url("https://evil.com/audio") is False
        assert validate_stream_url("https://tidal.com.evil.com/audio") is False

    def test_rejects_garbage(self):
        from tidal_dl.gui.security import validate_stream_url

        assert validate_stream_url("") is False
        assert validate_stream_url("not-a-url") is False
