"""Tests for Tidal._ensure_token_fresh token refresh logic."""

import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from tidalapi.media import Quality, VideoQuality

from tidal_dl.config import reset_singletons

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
    reset_singletons()
    yield
    reset_singletons()


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

    def test_refreshes_when_expiry_zero_and_refresh_token_present(self, tidal):
        tidal.data.expiry_time = 0.0
        tidal.data.refresh_token = "some-refresh-token"
        with patch.object(tidal, "token_persist"):
            assert tidal._ensure_token_fresh() is True
        tidal.session.token_refresh.assert_called_once_with("some-refresh-token")

    def test_refreshes_when_expiry_none_like_and_refresh_token_present(self, tidal):
        tidal.data.expiry_time = None
        tidal.data.refresh_token = "some-refresh-token"
        with patch.object(tidal, "token_persist"):
            assert tidal._ensure_token_fresh() is True
        tidal.session.token_refresh.assert_called_once_with("some-refresh-token")

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

    def test_token_persist_not_called_when_token_refresh_returns_false(self, tidal):
        tidal.data.expiry_time = time.time() + 60
        tidal.data.refresh_token = "rejected-token"
        tidal.session.token_refresh.return_value = False

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
    def test_token_persist_treats_naive_expiry_as_utc(self, tidal):
        class NaiveExpiry(datetime):
            def timestamp(self):
                assert self.tzinfo is UTC
                return super().timestamp()

        expiry = NaiveExpiry.fromisoformat("2026-01-02T03:04:05")
        tidal.session.token_type = "Bearer"
        tidal.session.access_token = "access"
        tidal.session.refresh_token = "refresh"
        tidal.session.expiry_time = expiry

        tidal.token_persist()

        assert tidal.data.expiry_time == expiry.replace(tzinfo=UTC).timestamp()

    def test_token_persist_preserves_aware_expiry_instant(self, tidal):
        expiry = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=9)))
        tidal.session.token_type = "Bearer"
        tidal.session.access_token = "access"
        tidal.session.refresh_token = "refresh"
        tidal.session.expiry_time = expiry

        tidal.token_persist()

        assert tidal.data.expiry_time == expiry.timestamp()

    def test_stored_epoch_round_trips_without_timezone_shift(self, tidal):
        stored_epoch = 1_800_000_000.0
        tidal.token_from_storage = True
        tidal.data.token_type = "Bearer"
        tidal.data.access_token = "access"
        tidal.data.refresh_token = "refresh"
        tidal.data.expiry_time = stored_epoch
        tidal.session.load_oauth_session.return_value = True

        assert tidal.login_token() is True

        loaded_expiry = tidal.session.load_oauth_session.call_args.args[3]
        assert loaded_expiry.tzinfo is UTC
        tidal.session.token_type = "Bearer"
        tidal.session.access_token = "access"
        tidal.session.refresh_token = "refresh"
        tidal.session.expiry_time = loaded_expiry

        tidal.token_persist()

        assert tidal.data.expiry_time == stored_epoch

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


class TestLoginTokenDoesNotWipeRefresh:
    def test_login_token_does_not_delete_file_when_refresh_token_present(self, tidal):
        tidal.token_from_storage = True
        tidal.data.token_type = "Bearer"
        tidal.data.access_token = "expired-access"
        tidal.data.refresh_token = "persist-refresh"
        tidal.data.expiry_time = time.time() - 60
        tidal.session.load_oauth_session.side_effect = RuntimeError("network")
        tidal.file_path_obj = Path(tidal.file_path)
        tidal.file_path_obj.write_text("token", encoding="utf-8")

        with patch.object(tidal, "_ensure_token_fresh", return_value=False):
            assert tidal.login_token(delete_on_failure=True, quiet=True) is False

        assert tidal.file_path_obj.exists()

    def test_login_token_refreshes_when_access_missing_but_refresh_present(self, tidal):
        tidal.token_from_storage = True
        tidal.data.token_type = "Bearer"
        tidal.data.access_token = None
        tidal.data.refresh_token = "persist-refresh"
        tidal.data.expiry_time = 0.0

        with patch.object(tidal, "_ensure_token_fresh", return_value=True) as ensure:
            assert tidal.login_token(quiet=True) is True
        ensure.assert_called_once()

    def test_interactive_login_does_not_oauth_while_refresh_token_exists(self, tidal):
        tidal.data.refresh_token = "persist-refresh"
        tidal.session.login_oauth.side_effect = AssertionError("login started login_oauth")

        with patch.object(tidal, "_try_login_with_key_rotation", return_value=False):
            assert tidal.login(fn_print=lambda _msg: None) is False

        tidal.session.login_oauth.assert_not_called()


class TestLogoutReset:
    def _prepare(self, tidal):
        tidal.data.access_token = "access"
        tidal.data.refresh_token = "refresh"
        tidal.data.token_type = "Bearer"
        tidal.data.expiry_time = time.time() + 3600
        tidal.token_from_storage = True
        tidal.is_atmos_session = True
        tidal.settings = SimpleNamespace(data=SimpleNamespace(quality_audio=Quality.high_lossless))
        tidal.file_path_obj = Path(tidal.file_path)
        tidal.file_path_obj.write_text("token", encoding="utf-8")
        return tidal.session, tidal.data

    def test_logout_rebuilds_usable_unauthenticated_session(self, tidal):
        import certifi

        old_session, old_data = self._prepare(tidal)
        key = {"valid": "True", "clientId": "managed-id", "clientSecret": "managed-secret"}

        with patch("tidal_dl.config._api.getItem", return_value=key):
            assert tidal.logout() is True

        assert tidal.session is not old_session
        assert tidal.data is not old_data
        assert tidal.session.check_login() is False
        assert tidal.session.config.item_limit == 10000
        assert tidal.session.request_session.verify == certifi.where()
        assert tidal.session.config.client_id == "managed-id"
        assert tidal.session.audio_quality == Quality.high_lossless
        assert tidal.session.video_quality == VideoQuality.high
        assert tidal.data.access_token is None
        assert tidal.data.refresh_token is None
        assert tidal.token_from_storage is False
        assert tidal.is_atmos_session is False
        tidal.api_cache.clear.assert_called_once_with()
        assert not tidal.file_path_obj.exists()

    def test_logout_preserves_state_when_session_construction_fails(self, tidal):
        old_session, old_data = self._prepare(tidal)

        with patch("tidal_dl.config.Session", side_effect=RuntimeError("construction failed")):
            with pytest.raises(RuntimeError, match="construction failed"):
                tidal.logout()

        assert tidal.session is old_session
        assert tidal.data is old_data
        assert tidal.token_from_storage is True
        assert tidal.is_atmos_session is True
        tidal.api_cache.clear.assert_not_called()
        assert tidal.file_path_obj.exists()

    def test_logout_preserves_state_when_token_delete_fails(self, tidal):
        old_session, old_data = self._prepare(tidal)

        with patch("tidal_dl.config.Path.unlink", side_effect=PermissionError("read-only")):
            with pytest.raises(PermissionError, match="read-only"):
                tidal.logout()

        assert tidal.session is old_session
        assert tidal.data is old_data
        assert tidal.token_from_storage is True
        assert tidal.is_atmos_session is True
        tidal.api_cache.clear.assert_not_called()
        assert tidal.file_path_obj.exists()
