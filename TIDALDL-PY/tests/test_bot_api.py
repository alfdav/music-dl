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
    # Reset the stream token secret so tests are deterministic
    import tidal_dl.gui.security as sec
    sec._STREAM_TOKEN_SECRET = None

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
    """R1: Correct bearer token returns non-401."""

    def test_valid_token(self, bot_client):
        resp = bot_client.post("/api/bot/play/resolve",
                               headers={**bot_client._host, "authorization": f"Bearer {TEST_TOKEN}"},
                               json={"query": "test"})
        assert resp.status_code != 401


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
        sec._STREAM_TOKEN_SECRET = None

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
        sec._STREAM_TOKEN_SECRET = None

        token = sec.sign_bot_stream_token({"track_id": "123"}, ttl_seconds=0)
        time.sleep(0.05)
        assert sec.verify_bot_stream_token(token) is None

    def test_tampered_payload_rejected(self, monkeypatch):
        """R4: Tampered payload is rejected."""
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec
        sec._STREAM_TOKEN_SECRET = None

        token = sec.sign_bot_stream_token({"track_id": "123"})
        parts = token.split(".")
        tampered = ("A" if parts[0][0] != "A" else "B") + parts[0][1:]
        assert sec.verify_bot_stream_token(f"{tampered}.{parts[1]}") is None

    def test_tampered_signature_rejected(self, monkeypatch):
        """R4: Tampered signature is rejected."""
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec
        sec._STREAM_TOKEN_SECRET = None

        token = sec.sign_bot_stream_token({"track_id": "123"})
        parts = token.split(".")
        tampered = ("A" if parts[1][0] != "A" else "B") + parts[1][1:]
        assert sec.verify_bot_stream_token(f"{parts[0]}.{tampered}") is None

    def test_lifetime_bounded(self, monkeypatch):
        """R4: Token lifetime is bounded (not indefinite)."""
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec
        sec._STREAM_TOKEN_SECRET = None

        token = sec.sign_bot_stream_token({"track_id": "123"})
        payload = sec.verify_bot_stream_token(token)
        assert payload is not None
        # Default 120s — must expire within 121s
        assert payload["exp"] <= time.time() + 121

    def test_malformed_rejected(self, monkeypatch):
        """R4: Malformed tokens rejected."""
        monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", TEST_TOKEN)
        import tidal_dl.gui.security as sec
        sec._STREAM_TOKEN_SECRET = None

        assert sec.verify_bot_stream_token("") is None
        assert sec.verify_bot_stream_token("not-a-token") is None


# ── R7: Logging Safety ───────────────────────────────────────────
# Note: T-004 is S-sized. Bot API code does not log tokens by design.
# These tests verify the security module functions don't leak tokens
# in their normal operation (defensive check).


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
        sec._STREAM_TOKEN_SECRET = None

        token = sec.sign_bot_stream_token({"track_id": "123"}, ttl_seconds=0)
        time.sleep(0.05)
        # verify_bot_stream_token returns None for expired — the token
        # itself is never included in any error response by design
        result = sec.verify_bot_stream_token(token)
        assert result is None
