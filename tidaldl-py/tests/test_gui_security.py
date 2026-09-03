"""Security tests for the GUI server."""

import secrets
from pathlib import Path

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
        from tidal_dl.gui.security import resolve_local_audio_path

        outside = tmp_path.parent / "scanned.flac"
        outside.write_bytes(b"fake")

        result = resolve_local_audio_path(
            str(outside),
            [str(tmp_path)],
            library_trusts_raw_path=True,
            library_resolved_path=outside.resolve(),
        )

        assert result.kind == "ok"
        assert result.path == outside.resolve()

    def test_library_resolver_rejects_non_audio_even_when_scanned(self, tmp_path):
        from tidal_dl.gui.security import resolve_local_audio_path

        outside = tmp_path.parent / "scanned.txt"
        outside.write_text("fake")

        result = resolve_local_audio_path(
            str(outside),
            [str(tmp_path)],
            library_trusts_raw_path=True,
            library_resolved_path=outside.resolve(),
        )

        assert result.kind == "not_audio"
        assert result.path is None

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

    def test_lexically_under_roots_rejects_traversal_and_encoding(self, tmp_path):
        from tidal_dl.gui.api.library import _lexically_under_roots

        root = tmp_path / "Music"
        root.mkdir()
        inside = f"{root}/Artist/Album/song.flac"
        assert _lexically_under_roots(inside, [str(root)]) == inside
        assert _lexically_under_roots("/etc/passwd", [str(root)]) is None
        assert _lexically_under_roots(f"{root}/../escape.flac", [str(root)]) is None
        assert _lexically_under_roots(f"{root}/%2e%2e/escape.flac", [str(root)]) is None
        assert _lexically_under_roots(f"{root}/%2e%2e%2fescape.flac", [str(root)]) is None
        assert _lexically_under_roots(f"{root}/song.flac\x00.flac", [str(root)]) is None
        assert _lexically_under_roots("~/Music/song.flac", [str(root)]) is None
        assert _lexically_under_roots(f"{root}/notes.txt", [str(root)]) is None

    def test_trusted_library_path_uses_allowlisted_db_value(self, tmp_path, monkeypatch):
        from tidal_dl.gui.api import library as library_api
        from tidal_dl.helper.library_db import LibraryDB

        root = tmp_path / "Music"
        audio = root / "A" / "song.wav"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b"RIFF")
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        db.record(str(audio), status="tagged", artist="A", title="Song", album="LP")
        db.commit()
        db.close()

        class FakeSettings:
            data = type("S", (), {"download_base_path": str(root), "scan_paths": ""})()

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))

        stored = library_api._exact_scanned_path(str(audio))
        assert stored == str(audio)
        assert library_api._trusted_library_path(str(audio)) == audio.resolve()
        assert library_api._trusted_library_path(str(root / ".." / "escape.wav")) is None
        assert library_api._library_row_under_roots("/etc/passwd") is False
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        db.record("/etc/passwd.wav", status="tagged", artist="X", title="X", album="X")
        db.commit()
        db.close()
        assert library_api._exact_scanned_path("/etc/passwd.wav") == "/etc/passwd.wav"
        assert library_api._library_row_under_roots("/etc/passwd.wav") is False
        assert library_api._trusted_library_path("/etc/passwd.wav") is None


class TestLocalAudioResolution:
    def test_rejects_blank_input(self, tmp_path):
        from tidal_dl.gui.security import resolve_local_audio_path

        result = resolve_local_audio_path("   ", [str(tmp_path)])

        assert result.kind == "bad_request"
        assert result.path is None

    def test_reports_forbidden_for_untrusted_path(self, tmp_path):
        from tidal_dl.gui.security import resolve_local_audio_path

        result = resolve_local_audio_path("/etc/passwd", [str(tmp_path)])

        assert result.kind == "forbidden"
        assert result.path is None

    def test_reports_not_found_for_db_trusted_missing_path(self, tmp_path):
        from tidal_dl.gui.security import resolve_local_audio_path

        result = resolve_local_audio_path(
            str(tmp_path / "missing.flac"),
            [str(tmp_path)],
            library_trusts_raw_path=True,
            library_resolved_path=None,
        )

        assert result.kind == "not_found"
        assert result.path is None

    def test_reports_not_audio_for_db_trusted_non_audio(self, tmp_path):
        from tidal_dl.gui.security import resolve_local_audio_path

        bad = tmp_path / "notes.txt"
        bad.write_text("x")

        result = resolve_local_audio_path(
            str(bad),
            [str(tmp_path)],
            library_trusts_raw_path=True,
            library_resolved_path=bad.resolve(),
        )

        assert result.kind == "not_audio"
        assert result.path is None

    def test_returns_ok_for_allowed_audio(self, tmp_path):
        from tidal_dl.gui.security import resolve_local_audio_path

        audio = tmp_path / "track.flac"
        audio.write_bytes(b"fake")

        result = resolve_local_audio_path(str(audio), [str(tmp_path)])

        assert result.kind == "ok"
        assert result.path == audio.resolve()

    def test_rejects_symlink_raw_path_in_db_fallback(self, tmp_path):
        """Even if the DB trusts a path, a symlink raw path must never resolve —
        guards against race conditions or stale DB entries past the scan-time skip.
        """
        from tidal_dl.gui.security import resolve_local_audio_path

        # Normalize tmp_path so outer-directory symlinks (e.g. GHA runner's
        # /tmp mount layout) don't leak into containment checks.
        tmp_path = tmp_path.resolve()

        # Real file OUTSIDE allowed_dirs (so primary validate_audio_path fails)
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        real_file = outside_dir / "track.flac"
        real_file.write_bytes(b"fake")

        # Symlink INSIDE allowed_dir pointing at the outside real file
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        symlink_path = allowed_dir / "track.flac"
        symlink_path.symlink_to(real_file)

        # Sanity — if any of these fail, the diagnostic tells us why
        # the resolver's logic would diverge on this host.
        assert symlink_path.is_symlink(), f"symlink creation failed at {symlink_path}"
        assert symlink_path.resolve(strict=True) == real_file.resolve(), (
            f"resolve mismatch: {symlink_path.resolve(strict=True)} != {real_file.resolve()}"
        )
        assert not symlink_path.resolve(strict=True).is_relative_to(allowed_dir.resolve()), (
            f"resolved target unexpectedly inside allowed_dir: "
            f"target={symlink_path.resolve(strict=True)} allowed={allowed_dir.resolve()}"
        )

        # Without the symlink guard, DB fallback would return "ok" here
        result = resolve_local_audio_path(
            str(symlink_path),
            [str(allowed_dir)],
            library_trusts_raw_path=True,
            library_resolved_path=real_file.resolve(),
        )

        assert result.kind == "forbidden", (
            f"expected forbidden, got kind={result.kind} path={result.path}; "
            f"raw is_symlink={Path(str(symlink_path)).is_symlink()}"
        )
        assert result.path is None


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
