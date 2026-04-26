"""Tests for Tidal._ensure_token_fresh token refresh logic."""

import time
from unittest.mock import MagicMock, patch, call
import pytest

from tidal_dl.helper.decorator import SingletonMeta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tidal(tmp_path):
    """Instantiate a Tidal config object with no real filesystem side-effects."""
    from tidal_dl.config import Tidal
    from tidal_dl.model.cfg import Token

    tidal = Tidal.__new__(Tidal)
    tidal.data = Token()
    tidal.session = MagicMock()
    tidal.file_path = str(tmp_path / "token.json")
    tidal.path_base = str(tmp_path)
    tidal.cls_model = Token
    tidal.token_from_storage = False
    tidal.is_pkce = False
    tidal.is_atmos_session = False
    tidal.stream_lock = MagicMock()
    tidal._active_key_index = 0
    tidal.api_cache = MagicMock()
    return tidal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singletons():
    SingletonMeta._instances.clear()
    yield
    SingletonMeta._instances.clear()


@pytest.fixture
def tidal(tmp_path):
    return _make_tidal(tmp_path)


# ---------------------------------------------------------------------------
# Test: guard – token expiry_time is 0 or unset
# ---------------------------------------------------------------------------

class TestEnsureTokenFreshGuards:
    def test_tidal_session_uses_certifi_ca_bundle(self, clear_singletons):
        import certifi

        from tidal_dl.config import Tidal

        tidal = Tidal()

        assert tidal.session.request_session.verify == certifi.where()

    def test_returns_false_when_expiry_zero(self, tidal):
        tidal.data.expiry_time = 0.0
        tidal.data.refresh_token = "some-refresh-token"
        assert tidal._ensure_token_fresh() is False

    def test_returns_false_when_expiry_none_like(self, tidal):
        tidal.data.expiry_time = None
        tidal.data.refresh_token = "some-refresh-token"
        # None should be treated as 0
        # _ensure_token_fresh does: _raw_exp or 0 then float()
        assert tidal._ensure_token_fresh() is False

    def test_returns_false_when_no_refresh_token(self, tidal):
        # Token is expiring soon, but no refresh token available
        tidal.data.expiry_time = time.time() + 60  # within 300s window
        tidal.data.refresh_token = None
        assert tidal._ensure_token_fresh() is False

    def test_returns_false_when_refresh_token_empty_string(self, tidal):
        tidal.data.expiry_time = time.time() + 60
        tidal.data.refresh_token = ""
        assert tidal._ensure_token_fresh() is False

    def test_returns_false_when_token_not_near_expiry(self, tidal):
        # Token expires well beyond the default 300s window
        tidal.data.expiry_time = time.time() + 3600
        tidal.data.refresh_token = "some-refresh-token"
        assert tidal._ensure_token_fresh() is False
        tidal.session.token_refresh.assert_not_called()


# ---------------------------------------------------------------------------
# Test: refresh fires when token is near expiry
# ---------------------------------------------------------------------------

class TestEnsureTokenFreshRefreshFires:
    def test_calls_token_refresh_with_refresh_token(self, tidal):
        tidal.data.expiry_time = time.time() + 60  # 60s left, inside 300s window
        tidal.data.refresh_token = "my-refresh-token"

        with patch.object(tidal, "token_persist") as mock_persist:
            result = tidal._ensure_token_fresh()

        assert result is True
        tidal.session.token_refresh.assert_called_once_with("my-refresh-token")
        mock_persist.assert_called_once()

    def test_calls_token_refresh_when_already_expired(self, tidal):
        tidal.data.expiry_time = time.time() - 100  # already expired
        tidal.data.refresh_token = "expired-but-refreshable"

        with patch.object(tidal, "token_persist"):
            result = tidal._ensure_token_fresh()

        assert result is True
        tidal.session.token_refresh.assert_called_once_with("expired-but-refreshable")

    def test_respects_custom_refresh_window(self, tidal):
        # Token has 400s left — outside default 300s window but inside 500s custom window
        tidal.data.expiry_time = time.time() + 400
        tidal.data.refresh_token = "custom-window-token"

        with patch.object(tidal, "token_persist"):
            result = tidal._ensure_token_fresh(refresh_window_sec=500)

        assert result is True
        tidal.session.token_refresh.assert_called_once_with("custom-window-token")

    def test_no_refresh_outside_custom_window(self, tidal):
        # Token has 400s left, custom window is 300s — should NOT refresh
        tidal.data.expiry_time = time.time() + 400
        tidal.data.refresh_token = "fresh-token"

        result = tidal._ensure_token_fresh(refresh_window_sec=300)

        assert result is False
        tidal.session.token_refresh.assert_not_called()


# ---------------------------------------------------------------------------
# Test: token_persist is called after successful refresh
# ---------------------------------------------------------------------------

class TestTokenPersistOnRefresh:
    def test_token_persist_called_after_refresh(self, tidal):
        tidal.data.expiry_time = time.time() + 60
        tidal.data.refresh_token = "valid-refresh-token"
        call_order = []

        tidal.session.token_refresh.side_effect = lambda _: call_order.append("refresh")

        with patch.object(tidal, "token_persist", side_effect=lambda: call_order.append("persist")):
            tidal._ensure_token_fresh()

        assert call_order == ["refresh", "persist"], "token_persist must be called after token_refresh"

    def test_token_persist_not_called_on_refresh_failure(self, tidal):
        tidal.data.expiry_time = time.time() + 60
        tidal.data.refresh_token = "bad-token"
        tidal.session.token_refresh.side_effect = Exception("network error")

        with patch.object(tidal, "token_persist") as mock_persist:
            result = tidal._ensure_token_fresh()

        assert result is False
        mock_persist.assert_not_called()


# ---------------------------------------------------------------------------
# Test: exception handling in refresh path
# ---------------------------------------------------------------------------

class TestEnsureTokenFreshErrorHandling:
    def test_returns_false_on_token_refresh_exception(self, tidal):
        tidal.data.expiry_time = time.time() + 60
        tidal.data.refresh_token = "some-token"
        tidal.session.token_refresh.side_effect = RuntimeError("TIDAL API error")

        result = tidal._ensure_token_fresh()

        assert result is False

    def test_does_not_propagate_exception(self, tidal):
        """_ensure_token_fresh must not raise — callers depend on bool return."""
        tidal.data.expiry_time = time.time() + 60
        tidal.data.refresh_token = "some-token"
        tidal.session.token_refresh.side_effect = Exception("unexpected")

        # Must not raise
        result = tidal._ensure_token_fresh()
        assert result is False


# ---------------------------------------------------------------------------
# Test: datetime expiry_time is handled correctly
# ---------------------------------------------------------------------------

class TestDatetimeExpiryHandling:
    def test_datetime_expiry_near_triggers_refresh(self, tidal):
        """expiry_time as a datetime object within the refresh window fires refresh."""
        from datetime import datetime

        tidal.data.expiry_time = datetime.fromtimestamp(time.time() + 60)
        tidal.data.refresh_token = "datetime-token"

        with patch.object(tidal, "token_persist"):
            result = tidal._ensure_token_fresh()

        assert result is True
        tidal.session.token_refresh.assert_called_once_with("datetime-token")

    def test_datetime_expiry_far_skips_refresh(self, tidal):
        """expiry_time as a datetime far in the future does not trigger refresh."""
        from datetime import datetime

        tidal.data.expiry_time = datetime.fromtimestamp(time.time() + 3600)
        tidal.data.refresh_token = "fresh-datetime-token"

        result = tidal._ensure_token_fresh()

        assert result is False
        tidal.session.token_refresh.assert_not_called()
