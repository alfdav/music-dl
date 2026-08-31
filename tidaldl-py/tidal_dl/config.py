"""Configuration management for music-dl.

Provides:
  - Settings: User preferences singleton backed by settings.json.
  - Tidal: TIDAL session singleton with OAuth login and Dolby Atmos credential switching.
  - HandlingApp: Application-lifecycle events (abort / run).
"""

import contextlib
import json
import os
import shutil
import time
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from threading import Event, Lock, RLock
from typing import Any, Generic, Protocol, Self, TypeVar

import certifi
import typer
from rich.console import Console as RichConsole
from tidalapi.media import Quality, VideoQuality
from tidalapi.session import Config as TidalConfig
from tidalapi.session import Session

from tidal_dl import api as _api
from tidal_dl.constants import (
    ATMOS_CLIENT_ID,
    ATMOS_CLIENT_SECRET,
    ATMOS_REQUEST_QUALITY,
    QUALITY_PROBE_TRACK_ID,
    QUALITY_RANK,
    SOURCE_RESOLVE_TIMEOUT_SEC,
    DownloadSource,
    quality_name,
)
from tidal_dl.helper.cache import TTLCache
from tidal_dl.helper.path import path_config_base, path_file_settings, path_file_token
from tidal_dl.hifi_api import HiFiApiClient
from tidal_dl.model.cfg import DEFAULT_FORMAT_PLAYLIST, LEGACY_DEFAULT_FORMAT_PLAYLIST
from tidal_dl.model.cfg import Settings as ModelSettings
from tidal_dl.model.cfg import Token as ModelToken

_console = RichConsole()

_singleton_lock = Lock()
_token_fresh_lock = RLock()
_settings_instance: "Settings | None" = None
_tidal_instance: "Tidal | None" = None
_handling_app_instance: "HandlingApp | None" = None


def reset_singletons() -> None:
    """Clear module singletons (tests and cfg reset)."""
    global _settings_instance, _tidal_instance, _handling_app_instance
    with _singleton_lock:
        _settings_instance = None
        _tidal_instance = None
        _handling_app_instance = None


class JsonConfigModel(Protocol):
    @classmethod
    def from_json(cls, s: str) -> Self: ...

    def to_json(self) -> str: ...


ConfigModelT = TypeVar("ConfigModelT", bound=JsonConfigModel)


class MessagePrinter(Protocol):
    def __call__(self, message: str) -> object: ...


class BaseConfig(Generic[ConfigModelT]):
    """Base class for JSON-backed configuration objects."""

    data: ConfigModelT
    file_path: str
    cls_model: type[ConfigModelT]
    path_base: str = ""

    def __init__(self, cls_model: type[ConfigModelT], file_path: str) -> None:
        self.cls_model = cls_model
        self.file_path = file_path
        self.data = cls_model()
        if not self.path_base:
            self.path_base = path_config_base()

    def save(self, config_to_compare: str | None = None) -> None:
        """Persist current config to disk.

        Args:
            config_to_compare (str | None): If provided, skip write when unchanged.
        """
        data_json = self.data.to_json()

        if config_to_compare == data_json:
            return

        os.makedirs(self.path_base, exist_ok=True)

        with open(self.file_path, encoding="utf-8", mode="w") as f:
            json.dump(json.loads(data_json), f, indent=4)

    def set_option(self, key: str, value: Any) -> None:
        """Set a configuration option, coercing type as needed.

        Args:
            key (str): Attribute name on the data model.
            value: New value (will be coerced to match the existing type).
        """
        value_old: Any = getattr(self.data, key)

        if type(value_old) is bool:
            value = value.lower() in ("true", "1", "yes", "y") if isinstance(value, str) else bool(value)
        elif type(value_old) is int and not isinstance(value, int):
            value = int(value)

        setattr(self.data, key, value)

    def read(self, path: str) -> bool:
        """Load configuration from a JSON file.

        Args:
            path (str): Path to the JSON config file.

        Returns:
            bool: True if the file was loaded successfully.
        """
        result: bool = False
        settings_json: str = ""

        try:
            with open(path, encoding="utf-8") as f:
                settings_json = f.read()

            self.data = self._load_json(settings_json)
            result = True
        except (JSONDecodeError, TypeError, FileNotFoundError) as e:
            if isinstance(e, FileNotFoundError):
                self.data = self.cls_model()
            else:
                # Truly corrupt JSON — attempt recovery from backup
                self.data = self._recover_from_corrupt(path, settings_json)

        self.save(settings_json)

        return result

    def _load_json(self, raw_json: str) -> ConfigModelT:
        """Deserialize JSON into the config model."""
        try:
            return self.cls_model.from_json(raw_json)
        except (ValueError, KeyError, JSONDecodeError, TypeError):
            return self.cls_model()

    def _recover_from_corrupt(self, path: str, _broken_json: str) -> ConfigModelT:
        """Back up a corrupt config and restore from .bak or defaults."""
        path_bak = path + ".bak"

        try:
            if os.path.exists(path_bak):
                os.remove(path_bak)
            shutil.move(path, path_bak)
        except OSError:
            pass

        try:
            with open(path_bak, encoding="utf-8") as f:
                data = self._load_json(f.read())
            _console.print(
                f"[yellow]Warning:[/yellow] Config was corrupt. Recovered settings from backup '{path_bak}'."
            )
            return data
        except (FileNotFoundError, JSONDecodeError, TypeError, ValueError):
            pass

        _console.print(
            f"[yellow]Warning:[/yellow] Config was corrupt. Using defaults. Backup saved to '{path_bak}'."
        )
        return self.cls_model()


class Settings(BaseConfig[ModelSettings]):
    """Singleton holding user preferences loaded from settings.json."""

    data: ModelSettings

    def __new__(cls) -> Self:
        global _settings_instance
        with _singleton_lock:
            if _settings_instance is None:
                _settings_instance = super().__new__(cls)
        return _settings_instance

    def __init__(self) -> None:
        if getattr(self, "_singleton_ready", False):
            return
        self._singleton_ready = True
        super().__init__(ModelSettings, path_file_settings())
        self.read(self.file_path)
        self._migrate_legacy_playlist_template()

    def _migrate_legacy_playlist_template(self) -> None:
        """Upgrade the untouched legacy playlist template to the current default."""
        if self.data.format_playlist != LEGACY_DEFAULT_FORMAT_PLAYLIST:
            return

        self.data.format_playlist = DEFAULT_FORMAT_PLAYLIST
        self.save()


class Tidal(BaseConfig[ModelToken]):
    """Singleton wrapping a tidalapi Session with OAuth and Dolby Atmos support."""

    data: ModelToken
    session: Session
    token_from_storage: bool = False
    settings: Settings
    is_pkce: bool
    api_cache: TTLCache
    _active_key_index: int

    @staticmethod
    def _new_session() -> Session:
        session = Session(TidalConfig(item_limit=10000))
        session.request_session.verify = certifi.where()
        return session

    def __new__(cls, settings: Settings | None = None) -> Self:
        global _tidal_instance
        with _singleton_lock:
            if _tidal_instance is None:
                _tidal_instance = super().__new__(cls)
        return _tidal_instance

    def __init__(self, settings: Settings | None = None) -> None:
        if getattr(self, "_singleton_ready", False):
            if settings is not None:
                self.settings = settings
                self.settings_apply(settings)
            return
        self._singleton_ready = True
        super().__init__(ModelToken, path_file_token())
        self.session = self._new_session()
        self.original_client_id = self.session.config.client_id
        self.original_client_secret = self.session.config.client_secret
        # Serialize all stream-fetch operations to prevent race conditions
        # when switching between Atmos and normal session credentials.
        self.stream_lock = Lock()
        self.is_atmos_session = False
        self.is_pkce = False  # default; updated by login_token()
        self.active_source = DownloadSource.OAUTH
        self.hifi_client: HiFiApiClient | None = None
        self._active_key_index = 0
        self.token_from_storage = self.read(self.file_path)

        # Apply the first valid API key from the managed key list.
        self._apply_api_key(0)

        # Initialise the response cache (TTL applied after settings load).
        ttl = settings.data.api_cache_ttl_sec if settings else 300
        self.api_cache = TTLCache(ttl_sec=ttl)

        if settings:
            self.settings = settings
            self.settings_apply()

    def settings_apply(self, settings: Settings | None = None) -> bool:
        """Apply quality settings from the Settings singleton to the session.

        Args:
            settings (Settings | None): If provided, replace stored settings.

        Returns:
            bool: Always True.
        """
        if settings:
            self.settings = settings

        if not self.is_atmos_session:
            self.session.audio_quality = Quality(self.settings.data.quality_audio)

        self.session.video_quality = VideoQuality.high

        return True

    def _configured_hifi_instances(self) -> list[str]:
        raw = getattr(self.settings.data, "hifi_api_instances", "") if hasattr(self, "settings") else ""
        if not raw:
            return []
        return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]

    def resolve_source(self, fn_print: MessagePrinter, allow_interactive_login: bool = True) -> bool:
        """Resolve the active download source.

        Hi-Fi API handles audio streaming; OAuth is always needed for metadata
        (playlist/album browsing, track info, cover art, lyrics).  When Hi-Fi
        API is the preferred source we still attempt a silent token restore so
        that collection downloads work.  If the token restore fails the user
        can still download individual tracks by URL but playlist/album browsing
        will be unavailable.
        """
        preferred = DownloadSource(self.settings.data.download_source)
        allow_fallback = bool(self.settings.data.download_source_fallback)

        if preferred == DownloadSource.HIFI_API:
            self.hifi_client = HiFiApiClient(
                instances=self._configured_hifi_instances() or None,
                timeout=SOURCE_RESOLVE_TIMEOUT_SEC,
            )
            health = self.hifi_client.health_check()

            if health:
                self.active_source = DownloadSource.HIFI_API
                fn_print(f"Using Hi-Fi API source via {health}")

                # Hi-Fi API provides audio streams; OAuth is still needed for
                # metadata (playlist contents, track objects, cover art, lyrics).
                # Attempt a silent token restore — non-blocking, best-effort.
                is_token = self._try_login_with_key_rotation(quiet=True)
                if is_token:
                    fn_print("OAuth session restored (available as fallback).")
                    self._probe_subscription_quality()
                else:
                    fn_print("Not logged in. Run 'music-dl login' for OAuth fallback and favourites.")
                return True

            if not allow_fallback:
                fn_print("Hi-Fi API source is unavailable and source fallback is disabled.")
                return False

            fn_print("Hi-Fi API source unavailable. Falling back to OAuth source.")

        # OAuth preferred or fallback path
        is_login = (
            self.login(fn_print=fn_print)
            if allow_interactive_login
            else self._try_login_with_key_rotation(quiet=True)
        )
        if is_login:
            self.active_source = DownloadSource.OAUTH
        return is_login

    # ------------------------------------------------------------------
    # API key management
    # ------------------------------------------------------------------

    def refresh_api_keys(self, timeout: float | None = None) -> bool:
        """Refresh managed API keys and apply the first valid key."""
        refreshed = _api.refresh_api_keys(
            timeout=SOURCE_RESOLVE_TIMEOUT_SEC if timeout is None else timeout
        )
        index = _api.first_valid_index()
        if index < 0:
            return False
        applied = self._apply_api_key(index)
        return refreshed and applied

    def _apply_api_key(self, index: int) -> bool:
        """Apply the API key at *index* from the managed key list to the session config.

        Args:
            index (int): Zero-based index into the key list returned by :mod:`tidal_dl.api`.

        Returns:
            bool: True if a valid key was applied, False if index is out of range or invalid.
        """
        key = _api.getItem(index)
        if key.get("valid") != "True" or not key.get("clientId"):
            return False

        self.session.config.client_id = key["clientId"]
        self.session.config.client_secret = key["clientSecret"]
        self._active_key_index = index
        return True

    def _try_login_with_key_rotation(self, quiet: bool = False) -> bool:
        """Attempt token login, rotating through all available API keys on failure.

        Iterates :func:`tidal_dl.api.getItems` in order.  The first key that
        allows a successful ``login_token()`` call wins and is recorded as the
        active key.  Falls back to the original ``tidalapi`` credentials if
        the managed list is exhausted.

        Args:
            quiet (bool): Suppress per-key failure messages (used when Hi-Fi is
                primary and OAuth is only a best-effort fallback).

        Returns:
            bool: True if login succeeded with any key.
        """
        self.refresh_api_keys()
        keys = _api.getItems()

        for index, key in enumerate(keys):
            if key.get("valid") != "True" or not key.get("clientId"):
                continue

            self._apply_api_key(index)

            if self.login_token(do_pkce=self.is_pkce, quiet=quiet):
                if not quiet:
                    _console.print(f"[dim]API key [{index}] ({key.get('platform', 'unknown')}) accepted.[/dim]")
                return True

            if not quiet:
                _console.print(
                    f"[yellow]API key [{index}] ({key.get('platform', 'unknown')}) failed, trying next...[/yellow]"
                )

        # All managed keys exhausted — restore original tidalapi credentials
        # and attempt one final login with them.  Only this last-resort attempt
        # is allowed to delete the token file on failure.
        self.session.config.client_id = self.original_client_id
        self.session.config.client_secret = self.original_client_secret
        return self.login_token(do_pkce=self.is_pkce, delete_on_failure=not quiet, quiet=quiet)

    def login_token(self, do_pkce: bool = False, delete_on_failure: bool = False, quiet: bool = False) -> bool:
        """Attempt to restore a session from a stored token.

        Args:
            do_pkce (bool): Use PKCE flow. Defaults to False.
            delete_on_failure (bool): If True, delete the token file when restoration
                fails.  Should only be set after ALL API keys have been exhausted.
            quiet (bool): Suppress error messages on failure.

        Returns:
            bool: True if the session was restored.
        """
        self.is_pkce = do_pkce
        result = False

        if self.token_from_storage:
            try:
                token_type: str | None = self.data.token_type
                access_token: str | None = self.data.access_token
                refresh_token: str = self.data.refresh_token or ""
                _raw_exp = self.data.expiry_time
                if isinstance(_raw_exp, datetime):
                    expiry_time = _raw_exp if _raw_exp.tzinfo is not None else _raw_exp.replace(tzinfo=UTC)
                elif _raw_exp and _raw_exp > 0:
                    expiry_time = datetime.fromtimestamp(_raw_exp, tz=UTC)
                else:
                    expiry_time = None

                if token_type is None or access_token is None:
                    if refresh_token and self._ensure_token_fresh(refresh_window_sec=30 * 24 * 3600):
                        return self._reload_oauth_session()
                    return False

                result = self.session.load_oauth_session(
                    token_type,
                    access_token,
                    refresh_token,
                    expiry_time,
                    is_pkce=do_pkce,
                )
            except Exception:
                result = False

                if not quiet:
                    print(
                        "Either there is something wrong with your credentials / account or some server problems on TIDAL's "
                        "side. Try logging in again by re-running this app."
                    )

            if not result and (self.data.refresh_token or refresh_token):
                if self._ensure_token_fresh(refresh_window_sec=30 * 24 * 3600):
                    result = self._reload_oauth_session()

            if (
                not result
                and delete_on_failure
                and not self.data.refresh_token
                and os.path.exists(self.file_path)
            ):
                os.remove(self.file_path)

        return result

    def _reload_oauth_session(self) -> bool:
        """Load stored tokens into the session after a refresh. Never starts OAuth."""
        token_type: str | None = getattr(self.data, "token_type", None)
        access_token: str | None = getattr(self.data, "access_token", None)
        refresh_token: str = getattr(self.data, "refresh_token", None) or ""
        if token_type is None or access_token is None:
            return False
        _raw_exp = getattr(self.data, "expiry_time", None)
        if isinstance(_raw_exp, datetime):
            expiry_time = _raw_exp if _raw_exp.tzinfo is not None else _raw_exp.replace(tzinfo=UTC)
        elif _raw_exp and _raw_exp > 0:
            expiry_time = datetime.fromtimestamp(_raw_exp, tz=UTC)
        else:
            expiry_time = None
        try:
            loaded = self.session.load_oauth_session(
                token_type,
                access_token,
                refresh_token,
                expiry_time,
                is_pkce=self.is_pkce,
            )
        except Exception:
            return False
        if not loaded:
            return False
        check = getattr(self.session, "check_login", None)
        if callable(check):
            try:
                return bool(check())
            except Exception:
                return False
        return True

    def login_finalize(self) -> bool:
        """Check and persist a newly-established login session.

        Returns:
            bool: True if login was successful.
        """
        result = self.session.check_login()

        if result:
            self.token_persist()
            self.refresh_account_quality()

        return result

    def token_persist(self) -> None:
        """Save the current session token to disk."""
        with _token_fresh_lock:
            self.set_option("token_type", self.session.token_type)
            self.set_option("access_token", self.session.access_token)
            self.set_option("refresh_token", self.session.refresh_token)
            _exp = self.session.expiry_time
            if isinstance(_exp, datetime) and _exp.tzinfo is None:
                _exp = _exp.replace(tzinfo=UTC)
            self.set_option("expiry_time", _exp.timestamp() if hasattr(_exp, "timestamp") else _exp)
            self.save()

            with contextlib.suppress(OSError, NotImplementedError):
                os.chmod(self.file_path, 0o600)

    def refresh_account_quality(self) -> str | None:
        """Read the account's highest Tidal quality and cache it on the token."""
        cached = getattr(self.data, "account_quality", None) or None
        try:
            user = getattr(self.session, "user", None)
            uid = getattr(user, "id", None)
            request = getattr(getattr(self.session, "request", None), "request", None)
            if not uid or not callable(request):
                return cached
            resp = request("GET", f"users/{uid}/subscription")
            data = resp.json() if hasattr(resp, "json") else resp
            if not isinstance(data, dict):
                return cached
            quality = str(data.get("highestSoundQuality") or "").upper() or None
            if quality:
                self.set_option("account_quality", quality)
                self.save()
            return quality or cached
        except Exception:
            return cached

    def _ensure_token_fresh(self, refresh_window_sec: int = 300) -> bool:
        with _token_fresh_lock:
            self._last_refresh_error = None
            self._last_refresh_outcome = None
            refresh_token = self.data.refresh_token
            if not refresh_token:
                self._last_refresh_outcome = "skipped"
                return False

            try:
                _raw_exp = getattr(self.data, "expiry_time", 0) or 0
                expiry_time = _raw_exp.timestamp() if hasattr(_raw_exp, "timestamp") else float(_raw_exp)
            except (TypeError, ValueError):
                expiry_time = 0
            if expiry_time > 0 and expiry_time - time.time() > refresh_window_sec:
                self._last_refresh_outcome = "skipped"
                return False

            try:
                refreshed = self.session.token_refresh(refresh_token)
                if refreshed is False:
                    self._last_refresh_outcome = "rejected"
                    return False
                self.token_persist()
                self._last_refresh_outcome = "ok"
                return True
            except Exception as exc:
                self._last_refresh_error = exc
                self._last_refresh_outcome = "failed"
                _console.print("[yellow]Warning:[/yellow] Token refresh failed; proceeding with current token.")
                return False

    def switch_to_atmos_session(self) -> bool:
        """Re-authenticate the session with Dolby Atmos credentials.

        Returns:
            bool: True if successful or already in Atmos mode.
        """
        if self.is_atmos_session:
            return True

        _console.print("[cyan]Switching session context to Dolby Atmos...[/cyan]")
        self.session.config.client_id = ATMOS_CLIENT_ID
        self.session.config.client_secret = ATMOS_CLIENT_SECRET
        self.session.audio_quality = ATMOS_REQUEST_QUALITY

        if not self.login_token(do_pkce=self.is_pkce):
            _console.print("[yellow]Warning:[/yellow] Atmos session authentication failed.")
            self.restore_normal_session(force=True)
            return False

        self.is_atmos_session = True
        _console.print("[cyan]Session is now in Atmos mode.[/cyan]")
        return True

    def restore_normal_session(self, force: bool = False) -> bool:
        """Restore the session to original user credentials.

        Args:
            force (bool): Force restoration even if already in normal mode.

        Returns:
            bool: True if successful or already in normal mode.
        """
        if not self.is_atmos_session and not force:
            return True

        _console.print("[cyan]Restoring session context to Normal...[/cyan]")
        # Restore the active managed key (not the raw tidalapi default),
        # so the session stays consistent with the key that succeeded at login.
        if not self._apply_api_key(self._active_key_index):
            self.session.config.client_id = self.original_client_id
            self.session.config.client_secret = self.original_client_secret
        self.session.audio_quality = Quality(self.settings.data.quality_audio)

        if not self.login_token(do_pkce=self.is_pkce):
            _console.print(
                "[yellow]Warning:[/yellow] Restoring original session failed. Please restart the application."
            )
            return False

        self.is_atmos_session = False
        _console.print("[cyan]Session is now in Normal mode.[/cyan]")
        return True

    def login(self, fn_print: MessagePrinter) -> bool:
        """Perform an interactive login.

        Tries the stored token first (rotating through managed API keys on
        failure); if all keys fail, launches a device-link OAuth flow.
        The browser is opened automatically; a clickable fallback link is also
        printed for headless / SSH environments.

        Args:
            fn_print (Callable): Output function for user messages.

        Returns:
            bool: True if logged in successfully.
        """
        is_token = self._try_login_with_key_rotation()

        if is_token:
            fn_print("Yep, looks good! You are logged in.")
            self._probe_subscription_quality()
            return True

        if self.data.refresh_token or getattr(self.session, "refresh_token", None):
            fn_print("Saved Tidal session could not be restored. Not starting a new login.")
            return False

        fn_print("You either do not have a token or your token is invalid.")
        fn_print("No worries, we will handle this...")

        # Use the lower-level login_oauth() so we can open the browser ourselves
        # before blocking on future.result().
        link_login, future = self.session.login_oauth()
        url: str = f"https://{link_login.verification_uri_complete}"

        # Try to auto-open the browser; fall back gracefully on headless systems.
        try:
            typer.launch(url)
            _console.print("[green]Browser opened.[/green] If it did not open, visit:")
        except Exception:
            _console.print("[yellow]Could not open browser automatically.[/yellow] Visit:")

        _console.print(
            f"  [link={url}][bold cyan]{url}[/bold cyan][/link]\n"
            f"  [dim]Link expires in {link_login.expires_in} seconds.[/dim]"
        )

        future.result()  # blocks until the user completes the browser login
        is_login = self.login_finalize()

        if is_login:
            fn_print("The login was successful. I have stored your credentials (token).")
            self._probe_subscription_quality()
            return True

        fn_print("Something went wrong. Did you complete the browser login? You may try again.")
        return False

    def _probe_subscription_quality(self) -> None:
        """Report the account's observed quality without changing the selection."""
        configured = Quality(self.settings.data.quality_audio)
        configured_rank = QUALITY_RANK.get(quality_name(configured), 0)

        try:
            import concurrent.futures

            def _run_probe():
                track = self.session.track(QUALITY_PROBE_TRACK_ID)
                return track.get_stream()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                stream = pool.submit(_run_probe).result(timeout=SOURCE_RESOLVE_TIMEOUT_SEC)
            delivered = stream.audio_quality
            delivered_rank = QUALITY_RANK.get(quality_name(delivered), 0)
        except Exception:
            # Non-fatal: if the probe fails we just keep the configured quality.
            _console.print(
                "[dim]Could not probe subscription quality (network or track unavailable). "
                "Keeping configured quality.[/dim]"
            )
            return

        # Quality may be a StrEnum member or a plain str depending on tidalapi version;
        # normalise to string for display and enum for comparison.
        delivered_str = quality_name(delivered)
        configured_str = quality_name(configured)

        if delivered_str not in QUALITY_RANK:
            _console.print(
                f"[yellow]Warning:[/yellow] Requested quality [bold]{configured_str}[/bold] "
                f"but the provider reported unknown delivery quality [bold]{delivered_str}[/bold]. "
                "Keeping configured quality."
            )
            return

        if delivered_rank >= configured_rank:
            _console.print(
                f"[green]Audio quality check passed:[/green] "
                f"account supports {delivered_str} (requested {configured_str})."
            )
            return

        _console.print(
            f"[yellow]Warning:[/yellow] Requested quality [bold]{configured_str}[/bold] "
            f"but your subscription only delivers [bold]{delivered_str}[/bold]. "
            "Keeping configured quality."
        )

    def logout(self) -> bool:
        """Remove the stored token and replace the current session.

        Returns:
            bool: Always True.
        """
        with _token_fresh_lock:
            session = self._new_session()
            original_client_id = session.config.client_id
            original_client_secret = session.config.client_secret
            key = _api.getItem(0)
            if key.get("valid") == "True" and key.get("clientId"):
                session.config.client_id = key["clientId"]
                session.config.client_secret = key["clientSecret"]

            if hasattr(self, "settings"):
                session.audio_quality = Quality(self.settings.data.quality_audio)
            session.video_quality = VideoQuality.high

            Path(self.file_path).unlink(missing_ok=True)
            self.session = session
            self.original_client_id = original_client_id
            self.original_client_secret = original_client_secret
            self.data = ModelToken()
            self.token_from_storage = False
            self.is_atmos_session = False
            self._active_key_index = 0
            self.api_cache.clear()
            return True


class HandlingApp:
    """Singleton that owns the application abort / run events."""

    event_abort: Event = Event()
    event_run: Event = Event()

    def __new__(cls) -> Self:
        global _handling_app_instance
        with _singleton_lock:
            if _handling_app_instance is None:
                _handling_app_instance = super().__new__(cls)
        return _handling_app_instance

    def __init__(self) -> None:
        if getattr(self, "_singleton_ready", False):
            return
        self._singleton_ready = True
        self.event_run.set()
