import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _NeverCompletes:
    def result(self, timeout=None):
        threading.Event().wait(60)


def test_gui_auth_login_refreshes_api_keys_before_oauth():
    from tidal_dl.gui.api import settings as settings_api

    calls = []

    class Session:
        def check_login(self):
            return False

        def login_oauth(self):
            calls.append("login_oauth")
            return (
                SimpleNamespace(
                    verification_uri_complete="login.tidal.com/device",
                    user_code="ABCD",
                    expires_in=300,
                ),
                _NeverCompletes(),
            )

    class Tidal:
        session = Session()

        def refresh_api_keys(self):
            calls.append("refresh_api_keys")

        def login_finalize(self):
            return False

    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "idle"})
    result = settings_api.auth_login(Tidal())

    assert result["status"] == "pending"
    assert calls == ["refresh_api_keys", "login_oauth"]


def test_gui_auth_login_repairs_valid_existing_session():
    from tidal_dl.gui.api import settings as settings_api

    calls = []

    class Session:
        refresh_token = "legacy-refresh"

        def check_login(self):
            calls.append("check_login")
            return True

        def token_refresh(self, refresh_token):
            calls.append(("token_refresh", refresh_token))
            return True

    class Tidal:
        session = Session()

        def token_persist(self):
            calls.append("token_persist")

    tidal = Tidal()
    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "idle"})

    result = settings_api.auth_login(tidal)

    assert result == {"status": "already_logged_in"}
    assert settings_api._login_state == {"status": "success"}
    assert calls == [("token_refresh", "legacy-refresh"), "token_persist"]


def test_gui_auth_login_uses_oauth_when_refresh_cannot_repair():
    from tidal_dl.gui.api import settings as settings_api

    calls = []

    class Session:
        refresh_token = "expired-refresh"

        def check_login(self):
            calls.append("check_login")
            return True

        def token_refresh(self, refresh_token):
            calls.append(("token_refresh", refresh_token))
            return False

        def login_oauth(self):
            calls.append("login_oauth")
            return (
                SimpleNamespace(verification_uri_complete="", user_code="ABCD", expires_in=300),
                _NeverCompletes(),
            )

    class Tidal:
        session = Session()

        def refresh_api_keys(self):
            calls.append("refresh_api_keys")

    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "idle"})

    result = settings_api.auth_login(Tidal())

    assert result["status"] == "pending"
    assert calls == [("token_refresh", "expired-refresh"), "refresh_api_keys", "login_oauth"]


class _ImmediateFuture:
    def result(self, timeout=None):
        return None


class _ResetTidal:
    def __init__(self, *, logout_error=None, finalize=True):
        self.logout_error = logout_error
        self.finalize = finalize
        self.calls = []

    def logout(self):
        self.calls.append("logout")
        if self.logout_error:
            raise self.logout_error
        return True

    def login_finalize(self):
        self.calls.append("login_finalize")
        return self.finalize


def test_auth_reset_is_local_and_replaces_login_state():
    from tidal_dl.gui.api import settings as settings_api

    tidal = _ResetTidal()
    tidal.session = SimpleNamespace(
        check_login=lambda: pytest.fail("reset called check_login"),
        token_refresh=lambda *_: pytest.fail("reset refreshed token"),
        login_oauth=lambda: pytest.fail("reset started OAuth"),
    )
    settings_api._login_generation = 4
    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "pending", "user_code": "OLD"})

    result = settings_api.auth_reset(tidal)

    assert result == {"status": "reset", "auth_state": "not_configured"}
    assert settings_api._login_generation == 5
    assert settings_api._login_state == {"status": "idle"}
    assert tidal.calls == ["logout"]


def test_stale_oauth_worker_cannot_restore_reset_credentials():
    from tidal_dl.gui.api import settings as settings_api

    tidal = _ResetTidal()
    settings_api._login_generation = 8
    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "idle"})

    settings_api._wait_for_login(tidal, _ImmediateFuture(), generation=7)

    assert tidal.calls == []
    assert settings_api._login_state == {"status": "idle"}


def test_failed_reset_preserves_pending_login_generation_and_worker():
    from tidal_dl.gui.api import settings as settings_api

    tidal = _ResetTidal(logout_error=PermissionError("read-only"))
    settings_api._login_generation = 11
    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "pending", "user_code": "ABCD"})

    with pytest.raises(HTTPException) as exc_info:
        settings_api.auth_reset(tidal)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Could not reset Tidal connection"
    assert settings_api._login_generation == 11
    assert settings_api._login_state == {"status": "pending", "user_code": "ABCD"}

    tidal.logout_error = None
    settings_api._wait_for_login(tidal, _ImmediateFuture(), generation=11)
    assert tidal.calls == ["logout", "login_finalize"]
    assert settings_api._login_state == {"status": "success"}


def test_auth_keepalive_uses_local_expiry_guard_without_check_login(monkeypatch):
    from tidal_dl.gui.api import settings as settings_api

    calls = []
    tidal = SimpleNamespace(
        session=SimpleNamespace(check_login=lambda: pytest.fail("keepalive called check_login")),
        _ensure_token_fresh=lambda refresh_window_sec: calls.append(refresh_window_sec) or False,
    )
    monkeypatch.setattr(settings_api, "get_tidal_instance", lambda: tidal)

    result = settings_api.auth_keepalive()

    assert result == {"refreshed": False}
    assert calls == [1800]


def test_auth_status_revives_expired_access_from_refresh_token_without_oauth():
    from tidal_dl.gui.api import settings as settings_api

    class ReviveTidal:
        def __init__(self):
            self.data = SimpleNamespace(
                access_token="expired-access",
                refresh_token="valid-refresh",
                expiry_time=time.time() - 60,
                account_quality="HI_RES",
            )
            self.session = SimpleNamespace(
                user=SimpleNamespace(name="Ada"),
                refresh_token="valid-refresh",
                login_oauth=lambda: pytest.fail("status started login_oauth"),
            )
            self.ensure_calls = []

        def _ensure_token_fresh(self, refresh_window_sec=300):
            self.ensure_calls.append(refresh_window_sec)
            self.data.access_token = "fresh-access"
            self.data.expiry_time = time.time() + 3600
            return True

    tidal = ReviveTidal()
    status = settings_api._local_auth_status(tidal)

    assert status == {
        "logged_in": True,
        "username": "Ada",
        "auth_state": "credentials_ready",
        "account_quality": "HI_RES",
    }
    assert tidal.ensure_calls


def test_auth_status_missing_tokens_is_not_configured():
    from tidal_dl.gui.api import settings as settings_api

    tidal = SimpleNamespace(
        data=SimpleNamespace(access_token=None, refresh_token=None, expiry_time=0, account_quality=None),
        session=SimpleNamespace(user=None, refresh_token=None),
        _ensure_token_fresh=lambda refresh_window_sec=300: pytest.fail("no tokens to refresh"),
    )

    status = settings_api._local_auth_status(tidal)

    assert status == {
        "logged_in": False,
        "username": "",
        "auth_state": "not_configured",
        "account_quality": None,
    }


def test_auth_status_refresh_failure_requires_login_not_not_configured():
    from tidal_dl.gui.api import settings as settings_api

    class DeadRefreshTidal:
        def __init__(self):
            self.data = SimpleNamespace(
                access_token="expired-access",
                refresh_token="dead-refresh",
                expiry_time=time.time() - 60,
                account_quality=None,
            )
            self.session = SimpleNamespace(user=None, refresh_token="dead-refresh")

        def _ensure_token_fresh(self, refresh_window_sec=300):
            return False

    status = settings_api._local_auth_status(DeadRefreshTidal())

    assert status["logged_in"] is False
    assert status["auth_state"] == "expired"
    assert status["auth_state"] != "not_configured"


def test_gui_auth_login_refreshes_persisted_token_before_oauth_when_session_looks_dead():
    from tidal_dl.gui.api import settings as settings_api

    calls = []

    class Session:
        refresh_token = "disk-refresh"

        def check_login(self):
            return False

        def login_oauth(self):
            calls.append("login_oauth")
            return (
                SimpleNamespace(
                    verification_uri_complete="login.tidal.com/device",
                    user_code="ABCD",
                    expires_in=300,
                ),
                _NeverCompletes(),
            )

        def token_refresh(self, refresh_token):
            calls.append(("token_refresh", refresh_token))
            return True

    class Tidal:
        session = Session()
        data = SimpleNamespace(
            access_token="expired-access",
            refresh_token="disk-refresh",
            expiry_time=time.time() - 60,
        )

        def _ensure_token_fresh(self, refresh_window_sec=300):
            calls.append(("ensure", refresh_window_sec))
            return True

        def token_persist(self):
            calls.append("token_persist")

        def refresh_api_keys(self):
            calls.append("refresh_api_keys")

        def refresh_account_quality(self):
            calls.append("refresh_account_quality")

    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "idle"})
    result = settings_api.auth_login(Tidal())

    assert result == {"status": "already_logged_in"}
    assert settings_api._login_state == {"status": "success"}
    assert "login_oauth" not in calls
    assert calls[0][0] == "ensure"


def test_gui_auth_login_starts_oauth_only_after_refresh_failure():
    from tidal_dl.gui.api import settings as settings_api

    calls = []

    class Session:
        refresh_token = "dead-refresh"

        def check_login(self):
            return False

        def login_oauth(self):
            calls.append("login_oauth")
            return (
                SimpleNamespace(verification_uri_complete="", user_code="ABCD", expires_in=300),
                _NeverCompletes(),
            )

        def token_refresh(self, refresh_token):
            calls.append(("token_refresh", refresh_token))
            return False

    class Tidal:
        session = Session()
        data = SimpleNamespace(access_token="expired-access", refresh_token="dead-refresh", expiry_time=time.time() - 60)

        def _ensure_token_fresh(self, refresh_window_sec=300):
            calls.append(("ensure", refresh_window_sec))
            return False

        def refresh_api_keys(self):
            calls.append("refresh_api_keys")

    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "idle"})
    result = settings_api.auth_login(Tidal())

    assert result["status"] == "pending"
    assert "login_oauth" in calls
    assert calls[0][0] == "ensure"
    assert calls.index("login_oauth") > calls.index(("ensure", calls[0][1]))


def test_gui_auth_login_reuses_unexpired_access_without_oauth_when_refresh_fails():
    from tidal_dl.gui.api import settings as settings_api

    calls = []

    class Session:
        refresh_token = "disk-refresh"

        def login_oauth(self):
            calls.append("login_oauth")
            return (
                SimpleNamespace(verification_uri_complete="", user_code="ABCD", expires_in=300),
                _NeverCompletes(),
            )

    class Tidal:
        session = Session()
        data = SimpleNamespace(
            access_token="still-good",
            refresh_token="disk-refresh",
            expiry_time=time.time() + 3600,
        )

        def _ensure_token_fresh(self, refresh_window_sec=300):
            calls.append("ensure")
            return False

        def refresh_api_keys(self):
            calls.append("refresh_api_keys")

    settings_api._login_state.clear()
    settings_api._login_state.update({"status": "idle"})
    result = settings_api.auth_login(Tidal())

    assert result == {"status": "already_logged_in"}
    assert "login_oauth" not in calls
    assert calls == ["ensure"]


def test_token_keepalive_loop_calls_ensure_until_stopped(monkeypatch):
    from tidal_dl.gui.api import settings as settings_api

    calls = []
    stop = threading.Event()

    def fake_keep():
        calls.append("keep")
        stop.set()

    monkeypatch.setattr(settings_api, "keep_tidal_session_alive", fake_keep)
    settings_api.run_token_keepalive(stop, interval_sec=0.01)

    assert calls == ["keep"]
