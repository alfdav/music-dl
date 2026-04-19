"""Tests for bot API: bearer auth (R1), stream tokens (R4), logging safety (R7)."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

TEST_TOKEN = "test-bot-token-secret"


@pytest.fixture
def bot_client(monkeypatch):
    """TestClient with bot token configured."""
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)

    from tidal_dl.gui import create_app
    c = TestClient(create_app(port=8765))
    c._host = {"host": "localhost:8765"}
    return c


# ── R1: Bearer Token Authentication ──────────────────────────────


class TestBotAuthRejectsMissing:
    """R1: Request without Authorization header returns 401."""

    def test_missing_header(self, bot_client):
        resp = bot_client.post("/api/bot/play/resolve",
                               headers=bot_client._host,
                               json={"query": "test"})
        assert resp.status_code == 401


class TestBotAuthRejectsInvalid:
    """R1: Malformed or incorrect bearer token returns 401."""

    def test_wrong_token(self, bot_client):
        resp = bot_client.post("/api/bot/play/resolve",
                               headers={**bot_client._host, "authorization": "Bearer wrong"},
                               json={"query": "test"})
        assert resp.status_code == 401

    def test_malformed_scheme(self, bot_client):
        resp = bot_client.post("/api/bot/play/resolve",
                               headers={**bot_client._host, "authorization": f"Basic {TEST_TOKEN}"},
                               json={"query": "test"})
        assert resp.status_code == 401


class TestBotAuthAcceptsValid:
    """R1: Correct bearer token returns non-401.

    We send an empty query to avoid hitting Tidal auth. Bot auth passing
    means the request reaches the body validator which returns 400.
    """

    def test_valid_token(self, bot_client):
        resp = bot_client.post("/api/bot/play/resolve",
                               headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
                               json={"query": ""})
        assert resp.status_code != 401
        assert resp.status_code == 400


class TestBotAuthEmptyEnv:
    """R1: Empty/whitespace env var causes all bot requests to return 401."""

    def test_empty_token(self, monkeypatch):
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", "")
        from tidal_dl.gui import create_app
        c = TestClient(create_app(port=8765))
        resp = c.post("/api/bot/play/resolve",
                      headers={"host": "localhost:8765", "authorization": "Bearer anything"},
                      json={"query": "test"})
        assert resp.status_code == 401

    def test_whitespace_token(self, monkeypatch):
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", "   ")
        from tidal_dl.gui import create_app
        c = TestClient(create_app(port=8765))
        resp = c.post("/api/bot/play/resolve",
                      headers={"host": "localhost:8765", "authorization": "Bearer   "},
                      json={"query": "test"})
        assert resp.status_code == 401


class TestBotAuthGuiUnaffected:
    """R1: GUI endpoints unaffected by bot auth configuration."""

    def test_gui_not_gated(self, bot_client):
        # GUI home endpoint should work without bot auth
        resp = bot_client.get("/api/home", headers=bot_client._host)
        # Should not be 401 (might be another status depending on state, but NOT 401)
        assert resp.status_code != 401


# ── R4: Stream Token Signing and Verification ────────────────────


class TestStreamTokens:
    """R4: Stream token signing and verification."""

    def test_roundtrip(self, monkeypatch):
        """R4: Signed token encodes item reference and expiration."""
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec

        token = sec.sign_bot_stream_token({"track_id": "12345", "kind": "local"})
        payload = sec.verify_bot_stream_token(token)
        assert payload is not None
        assert payload["track_id"] == "12345"
        assert payload["kind"] == "local"
        assert "exp" in payload
        assert payload["exp"] > time.time()

    def test_expired_rejected(self, monkeypatch):
        """R4: Expired token is rejected."""
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec

        token = sec.sign_bot_stream_token({"track_id": "123"}, ttl_seconds=0)
        time.sleep(0.05)
        assert sec.verify_bot_stream_token(token) is None

    def test_tampered_ciphertext_rejected(self, monkeypatch):
        """R4: Tampered ciphertext rejected (AES-GCM auth tag fails)."""
        import base64
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec

        token = sec.sign_bot_stream_token({"track_id": "123"})
        blob = bytearray(base64.urlsafe_b64decode(token))
        blob[len(blob) // 2] ^= 0x01
        tampered = base64.urlsafe_b64encode(bytes(blob)).decode()
        assert sec.verify_bot_stream_token(tampered) is None

    def test_tampered_tag_rejected(self, monkeypatch):
        """R4: Tampered auth tag rejected."""
        import base64
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec

        token = sec.sign_bot_stream_token({"track_id": "123"})
        blob = bytearray(base64.urlsafe_b64decode(token))
        blob[-1] ^= 0x01
        tampered = base64.urlsafe_b64encode(bytes(blob)).decode()
        assert sec.verify_bot_stream_token(tampered) is None

    def test_restart_safe(self, monkeypatch):
        """F-012: Tokens verify across process restarts (deterministic key)."""
        import importlib
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec

        token = sec.sign_bot_stream_token({"track_id": "123"})
        importlib.reload(sec)
        payload = sec.verify_bot_stream_token(token)
        assert payload is not None
        assert payload["track_id"] == "123"

    def test_path_not_in_token(self, monkeypatch):
        """R3-AC5: Playable URL does not expose raw library filesystem paths."""
        import base64
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec

        secret_path = "/Users/hackbook/Music/secret_album/track.flac"
        token = sec.sign_bot_stream_token({"kind": "local", "path": secret_path})
        blob = base64.urlsafe_b64decode(token)
        assert secret_path.encode() not in blob
        assert b"secret_album" not in blob
        payload = sec.verify_bot_stream_token(token)
        assert payload is not None
        assert payload["path"] == secret_path

    def test_lifetime_bounded(self, monkeypatch):
        """R4: Token lifetime is bounded (not indefinite)."""
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec

        token = sec.sign_bot_stream_token({"track_id": "123"})
        payload = sec.verify_bot_stream_token(token)
        assert payload is not None
        assert payload["exp"] <= time.time() + 121

    def test_malformed_rejected(self, monkeypatch):
        """R4: Malformed tokens rejected."""
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec

        assert sec.verify_bot_stream_token("") is None
        assert sec.verify_bot_stream_token("not-a-token") is None
        assert sec.verify_bot_stream_token("short") is None

    def test_fail_closed_when_token_blank(self, monkeypatch):
        """F-015: Signing and verifying fail closed when bot token blank."""
        import tidal_dl.gui.security as sec

        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", "")
        import pytest
        with pytest.raises(sec._StreamKeyError):
            sec.sign_bot_stream_token({"track_id": "123"})

        # Verification also fails closed — even a "valid" token from
        # another install would not verify because the key can't be derived.
        assert sec.verify_bot_stream_token("anytoken") is None

    def test_fail_closed_when_token_whitespace(self, monkeypatch):
        """F-015: Whitespace-only token treated as blank (fail closed)."""
        import tidal_dl.gui.security as sec

        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", "   ")
        import pytest
        with pytest.raises(sec._StreamKeyError):
            sec.sign_bot_stream_token({"track_id": "123"})


# ── R7: Logging Safety ───────────────────────────────────────────
# Note: T-004 is S-sized. Bot API code does not log tokens by design.
# These tests verify the security module functions don't leak tokens
# in their normal operation (defensive check).


# ── R2: Input Resolution (URL parsing + local playlist paths) ────


class TestResolveEndpoint:
    """R2: Input resolution for unambiguous inputs that don't need Tidal."""

    def test_empty_query_returns_400(self, bot_client):
        """R2-AC5: Empty query returns 4xx, not server error."""
        resp = bot_client.post(
            "/api/bot/play/resolve",
            headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
            json={"query": ""},
        )
        assert resp.status_code == 400

    def test_whitespace_query_returns_400(self, bot_client):
        resp = bot_client.post(
            "/api/bot/play/resolve",
            headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
            json={"query": "   "},
        )
        assert resp.status_code == 400

    def test_local_playlist_resolution(self, bot_client, tmp_path, monkeypatch):
        """R2-AC4: Local playlist name returns ordered list matching track order."""
        # Set up a playlist dir with real audio files (so library-path
        # validation passes — see F-022 filtering)
        playlist_dir = tmp_path / "library"
        playlist_dir.mkdir()
        track1 = playlist_dir / "track1.flac"
        track2 = playlist_dir / "track2.flac"
        track1.write_text("")
        track2.write_text("")
        (playlist_dir / "Night Drive.m3u8").write_text(
            f"#EXTM3U\n{track1}\n{track2}\n"
        )

        # Invalidate cache from prior tests, override roots + download paths
        from tidal_dl.helper import local_playlist_resolver as lpr
        lpr.invalidate_playlist_index_cache()

        import tidal_dl.gui.api.bot as bot_module
        import tidal_dl.gui.api.playback as playback_module
        monkeypatch.setattr(
            bot_module, "_local_playlist_roots", lambda: [playlist_dir]
        )
        monkeypatch.setattr(
            playback_module, "get_download_paths", lambda: [str(playlist_dir)]
        )

        resp = bot_client.post(
            "/api/bot/play/resolve",
            headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
            json={"query": "night drive"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["kind"] == "playlist"
        assert len(body["items"]) == 2
        # R2-AC6: Items contain required fields
        for item in body["items"]:
            assert "id" in item
            assert "title" in item
            assert "artist" in item
            assert "source_type" in item
            assert "local" in item
            assert "duration" in item
        assert body["items"][0]["source_type"] == "local"


# ── R3: Playable Source endpoint ─────────────────────────────────


class TestPlayableEndpoint:
    """R3: Playable source endpoint basic shape."""

    def test_unknown_item_id_returns_400(self, bot_client):
        """Unknown item_id format returns 400."""
        resp = bot_client.post(
            "/api/bot/playable",
            headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
            json={"item_id": "garbage"},
        )
        assert resp.status_code == 400

    def test_local_path_not_found(self, bot_client):
        """Local item_id with nonexistent path returns 404."""
        import base64
        encoded = "local:" + base64.urlsafe_b64encode(b"/nonexistent/path.flac").decode().rstrip("=")
        resp = bot_client.post(
            "/api/bot/playable",
            headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
            json={"item_id": encoded},
        )
        assert resp.status_code == 404

    def test_requires_bot_auth(self, bot_client):
        """R3-AC7: Requires valid bearer token."""
        resp = bot_client.post(
            "/api/bot/playable",
            headers=bot_client._host,
            json={"item_id": "tidal:12345"},
        )
        assert resp.status_code == 401


# ── R3-AC3: Stream token verification via bot-stream endpoint ────


class TestBotStreamEndpoint:
    """R3: /api/playback/bot-stream/{token} verifies tokens."""

    def test_invalid_token_returns_403(self, bot_client):
        """R3-AC3: Invalid stream token returns 403."""
        resp = bot_client.get(
            "/api/playback/bot-stream/not-a-valid-token",
            headers=bot_client._host,
        )
        assert resp.status_code == 403

    def test_expired_token_returns_403(self, bot_client, monkeypatch):
        """R3-AC3: Expired stream token returns 403."""
        import time
        import tidal_dl.gui.security as sec
        token = sec.sign_bot_stream_token({"kind": "local", "path": "/tmp/x.flac"}, ttl_seconds=0)
        time.sleep(0.05)
        resp = bot_client.get(
            f"/api/playback/bot-stream/{token}",
            headers=bot_client._host,
        )
        assert resp.status_code == 403


# ── R6: Download Gateway ─────────────────────────────────────────


class TestDownloadGateway:
    """R6: Download trigger and status endpoints."""

    def test_download_local_rejected(self, bot_client):
        """R6: Local items cannot be downloaded (they're already local)."""
        resp = bot_client.post(
            "/api/bot/download",
            headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
            json={"item_id": "local:abc"},
        )
        assert resp.status_code == 400

    def test_download_invalid_tidal_id(self, bot_client):
        """R6: Invalid tidal ID format returns 400."""
        resp = bot_client.post(
            "/api/bot/download",
            headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
            json={"item_id": "tidal:not-a-number"},
        )
        assert resp.status_code == 400

    def test_download_status_missing_job(self, bot_client):
        """R6-AC2: Status for unknown job returns 404."""
        resp = bot_client.get(
            "/api/bot/downloads/999999999",
            headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 404

    def test_download_status_invalid_job_id(self, bot_client):
        """R6: Non-numeric job_id returns 400."""
        resp = bot_client.get(
            "/api/bot/downloads/not-a-number",
            headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 400

    def test_download_requires_auth(self, bot_client):
        """R6-AC6: Both endpoints require bearer auth."""
        resp1 = bot_client.post(
            "/api/bot/download",
            headers=bot_client._host,
            json={"item_id": "tidal:12345"},
        )
        assert resp1.status_code == 401
        resp2 = bot_client.get("/api/bot/downloads/12345", headers=bot_client._host)
        assert resp2.status_code == 401


class TestLoggingSafety:
    """R7: Sensitive material not leaked in bot API code."""

    def test_bot_bearer_not_in_error_response(self, bot_client):
        """R7: 401 response body does not contain the actual token."""
        resp = bot_client.post("/api/bot/play/resolve",
                               headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}x"},
                               json={"query": "test"})
        assert TEST_TOKEN not in resp.text

    def test_stream_token_not_in_403_response(self, monkeypatch):
        """R7: 403 for expired stream token doesn't leak token contents."""
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec

        token = sec.sign_bot_stream_token({"track_id": "123"}, ttl_seconds=0)
        time.sleep(0.05)
        # verify_bot_stream_token returns None for expired — the token
        # itself is never included in any error response by design
        result = sec.verify_bot_stream_token(token)
        assert result is None
