"""Settings and auth status endpoints."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from tidal_dl import __version__
from tidal_dl.config import Settings, Tidal

router = APIRouter()


def get_tidal_instance():
    return Tidal()


def get_settings() -> dict:
    s = Settings()
    d = s.data
    return {
        "download_base_path": d.download_base_path,
        "quality_audio": str(d.quality_audio),
        "format_track": d.format_track,
        "format_album": d.format_album,
        "format_playlist": d.format_playlist,
        "cover_album_file": d.cover_album_file,
        "metadata_cover_embed": d.metadata_cover_embed,
        "lyrics_embed": d.lyrics_embed,
        "lyrics_file": d.lyrics_file,
        "skip_existing": d.skip_existing,
        "skip_duplicate_isrc": d.skip_duplicate_isrc,
        "downloads_concurrent_max": d.downloads_concurrent_max,
        "download_source": str(d.download_source),
        "download_source_fallback": d.download_source_fallback,
        "scan_paths": d.scan_paths,
        "upgrade_target_quality": d.upgrade_target_quality,
        "extract_flac": d.extract_flac,
        "download_delay": d.download_delay,
    }


def _safe_expand_path(path_str: str) -> str:
    try:
        return str(Path(path_str).expanduser())
    except (OSError, RuntimeError, ValueError):
        return path_str



def _configured_paths(s: Settings) -> list[str]:
    raw_scan_paths = [p.strip() for p in (s.data.scan_paths or "").split(",") if p.strip()]
    combined = [s.data.download_base_path, *raw_scan_paths]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in combined:
        if not item:
            continue
        expanded = _safe_expand_path(item)
        if expanded not in seen:
            seen.add(expanded)
            normalized.append(expanded)
    return normalized



def _path_access_info(path_str: str) -> dict:
    info = {
        "path": path_str,
        "exists": False,
        "is_dir": False,
        "readable": False,
        "writable": False,
        "ok": False,
        "reason": "unavailable",
    }

    try:
        path = Path(path_str).expanduser()
        info["path"] = str(path)
        exists = path.exists()
        is_dir = path.is_dir() if exists else False
        readable = bool(os.access(path, os.R_OK)) if exists and is_dir else False
        writable = bool(os.access(path, os.W_OK)) if exists and is_dir else False
    except (OSError, PermissionError, ValueError):
        info["reason"] = "access_denied"
        return info

    info.update({
        "exists": exists,
        "is_dir": is_dir,
        "readable": readable,
        "writable": writable,
        "ok": bool(exists and is_dir and readable),
    })

    if info["ok"] and writable:
        info["reason"] = None
    elif exists and not is_dir:
        info["reason"] = "not_a_directory"
    elif exists and is_dir and not readable:
        info["reason"] = "access_denied"
    elif exists and is_dir and readable and not writable:
        info["reason"] = "read_only"

    return info



def settings_status() -> dict:
    s = Settings()
    paths = [_path_access_info(path) for path in _configured_paths(s)]
    primary_path = _safe_expand_path(s.data.download_base_path) if s.data.download_base_path else ""
    blocked = next(
        (
            path
            for path in paths
            if path["path"] == primary_path and (not path["ok"] or not path["writable"])
        ),
        None,
    )
    read_only = blocked is not None
    banner_message = None
    if blocked:
        banner_message = (
            f"Music folder unavailable: {blocked['path']}. "
            "Settings are read-only until access is restored or you choose a new folder."
        )

    return {
        "version": __version__,
        "read_only": read_only,
        "banner_message": banner_message,
        "paths": paths,
    }


TOKEN_KEEPALIVE_WINDOW_SEC = 1800
TOKEN_KEEPALIVE_INTERVAL_SEC = 1800
_LOGIN_REFRESH_WINDOW_SEC = 30 * 24 * 3600


def keep_tidal_session_alive(
    tidal: Tidal | None = None,
    refresh_window_sec: int = TOKEN_KEEPALIVE_WINDOW_SEC,
) -> bool:
    """Refresh and persist when a stored refresh_token can still revive the session."""
    try:
        instance = tidal if tidal is not None else get_tidal_instance()
        ensure = getattr(instance, "_ensure_token_fresh", None)
        if not callable(ensure):
            return False
        return bool(ensure(refresh_window_sec=refresh_window_sec))
    except Exception:
        return False


def run_token_keepalive(
    stop_event: threading.Event,
    interval_sec: int = TOKEN_KEEPALIVE_INTERVAL_SEC,
) -> None:
    """Server-side keep-alive so a closed UI still refreshes overnight."""
    while not stop_event.wait(interval_sec):
        keep_tidal_session_alive()


def _persisted_refresh_token(tidal: Tidal):
    data_token = getattr(getattr(tidal, "data", None), "refresh_token", None)
    session_token = getattr(getattr(tidal, "session", None), "refresh_token", None)
    return data_token or session_token


def _revive_from_refresh_token(tidal: Tidal, refresh_window_sec: int = TOKEN_KEEPALIVE_WINDOW_SEC) -> bool:
    refresh_token = _persisted_refresh_token(tidal)
    if not refresh_token:
        return False
    ensure = getattr(tidal, "_ensure_token_fresh", None)
    if callable(ensure):
        try:
            return bool(ensure(refresh_window_sec=refresh_window_sec))
        except Exception:
            return False
    token_refresh = getattr(getattr(tidal, "session", None), "token_refresh", None)
    persist = getattr(tidal, "token_persist", None)
    if not callable(token_refresh):
        return False
    try:
        if token_refresh(refresh_token) is False:
            return False
        if callable(persist):
            persist()
        return True
    except Exception:
        return False


@router.get("/auth/status")
def auth_status(tidal: Tidal = Depends(get_tidal_instance)) -> dict:
    """Return OAuth state from local tokens, refreshing when a refresh_token can revive."""
    return _local_auth_status(tidal)


def _cached_account_quality(tidal: Tidal) -> str | None:
    quality = getattr(tidal.data, "account_quality", None)
    if not isinstance(quality, str):
        return None
    quality = quality.strip().upper()
    return quality or None


def _auth_status_payload(
    logged_in: bool,
    username: str,
    auth_state: str,
    account_quality: str | None = None,
) -> dict:
    return {
        "logged_in": logged_in,
        "username": username,
        "auth_state": auth_state,
        "account_quality": account_quality if logged_in else None,
    }


def _token_expiry(tidal: Tidal):
    try:
        raw_expiry = getattr(tidal.data, "expiry_time", 0) or 0
        return raw_expiry.timestamp() if hasattr(raw_expiry, "timestamp") else float(raw_expiry)
    except (TypeError, ValueError):
        return None


def _local_auth_status(tidal: Tidal) -> dict:
    username = ""
    access_token = getattr(tidal.data, "access_token", None)
    refresh_token = _persisted_refresh_token(tidal)
    if not access_token and not refresh_token:
        return _auth_status_payload(False, username, "not_configured")

    expiry_time = _token_expiry(tidal)
    if expiry_time is None and not refresh_token:
        return _auth_status_payload(False, username, "unavailable")

    expired = expiry_time is not None and expiry_time > 0 and expiry_time <= time.time()
    needs_revive = bool(refresh_token) and (not access_token or expired or expiry_time == 0)
    if needs_revive:
        _revive_from_refresh_token(tidal)
        access_token = getattr(tidal.data, "access_token", None)
        expiry_time = _token_expiry(tidal)
        expired = expiry_time is not None and expiry_time > 0 and expiry_time <= time.time()

    if expiry_time is None:
        return _auth_status_payload(False, username, "unavailable")
    if not access_token:
        return _auth_status_payload(False, username, "expired" if refresh_token else "not_configured")
    if expired:
        return _auth_status_payload(False, username, "expired")

    user = getattr(tidal.session, "user", None)
    username = getattr(user, "name", "") or ""
    return _auth_status_payload(True, username, "credentials_ready", _cached_account_quality(tidal))


_login_lock = threading.Lock()
_login_state = {"status": "idle"}  # idle | pending | success | failed
_login_generation = 0


def _replace_login_state(status: str) -> None:
    _login_state.clear()
    _login_state.update({"status": status})


def _wait_for_login(tidal: Tidal, future, generation: int) -> None:
    try:
        future.result(timeout=300)  # 5 min timeout
    except TimeoutError:
        status = "timeout"
    except Exception:
        status = "failed"
    else:
        with _login_lock:
            if generation != _login_generation:
                return
            try:
                status = "success" if tidal.login_finalize() else "failed"
            except Exception:
                status = "failed"
            _replace_login_state(status)
        return

    with _login_lock:
        if generation == _login_generation:
            _replace_login_state(status)


def _mark_already_logged_in(tidal: Tidal) -> dict:
    refresh_quality = getattr(tidal, "refresh_account_quality", None)
    if callable(refresh_quality):
        refresh_quality()
    _login_state["status"] = "success"
    return {"status": "already_logged_in"}


@router.post("/auth/login")
def auth_login(tidal: Tidal = Depends(get_tidal_instance)) -> dict:  # noqa: B008
    """Reuse a persisted refresh_token before starting a new device-code OAuth flow."""
    global _login_generation
    with _login_lock:
        if _revive_from_refresh_token(tidal, refresh_window_sec=_LOGIN_REFRESH_WINDOW_SEC):
            return _mark_already_logged_in(tidal)

        if not _persisted_refresh_token(tidal):
            try:
                if tidal.session.check_login():
                    return _mark_already_logged_in(tidal)
            except Exception:
                pass

        if _login_state["status"] == "pending":
            return _login_state.copy()

        try:
            tidal.refresh_api_keys()
            link_login, future = tidal.session.login_oauth()
            uri = link_login.verification_uri_complete or ""
            if uri and not uri.startswith("http"):
                uri = "https://" + uri

            _login_generation += 1
            generation = _login_generation
            _login_state.clear()
            _login_state.update({
                "status": "pending",
                "verification_uri": uri,
                "user_code": link_login.user_code,
                "expires_in": link_login.expires_in,
            })
        except Exception as exc:
            _login_state["status"] = "failed"
            raise HTTPException(status_code=500, detail=f"Login failed: {exc}") from exc

    threading.Thread(target=_wait_for_login, args=(tidal, future, generation), daemon=True).start()
    with _login_lock:
        return _login_state.copy()


@router.post("/auth/keepalive")
def auth_keepalive() -> dict:
    """Refresh the token only when local expiry data says it is near expiry.

    Sidecar startup and a server interval call the same helper so a closed UI
    still keeps the session. Older clients may POST this endpoint directly.
    """
    try:
        return {"refreshed": keep_tidal_session_alive()}
    except Exception:
        return {"refreshed": False, "reason": "refresh_error"}


@router.get("/auth/login/status")
def auth_login_status() -> dict:
    """Poll login progress."""
    with _login_lock:
        return _login_state.copy()


@router.get("/auth/account")
def auth_account(tidal: Tidal = Depends(get_tidal_instance)) -> dict:
    """Refresh the cached Tidal account quality. Status stays local-only."""
    status = _local_auth_status(tidal)
    if not status["logged_in"]:
        return status
    refresh_quality = getattr(tidal, "refresh_account_quality", None)
    if callable(refresh_quality):
        status["account_quality"] = refresh_quality()
    return status


@router.post("/auth/reset")
def auth_reset(tidal: Tidal = Depends(get_tidal_instance)) -> dict:
    """Remove local OAuth credentials without starting a provider request."""
    global _login_generation
    with _login_lock:
        try:
            if not tidal.logout():
                raise RuntimeError("Tidal logout returned false")
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Could not reset Tidal connection") from exc
        _login_generation += 1
        _replace_login_state("idle")
    return {"status": "reset", "auth_state": "not_configured"}


@router.get("/hifi/status")
def hifi_status() -> dict:
    """Check HiFi API server availability."""
    from tidal_dl.hifi_api import HiFiApiClient

    try:
        client = HiFiApiClient(timeout=5)
        live = client.live_instances()
        return {"alive": len(live), "instances": live, "configured": client.instances}
    except Exception:
        return {"alive": 0, "instances": [], "configured": []}


@router.get("/settings")
def read_settings() -> dict:
    """Return current settings."""
    return get_settings()


@router.get("/settings/status")
def read_settings_status() -> dict:
    """Return access status for configured music paths plus app version."""
    return settings_status()


@router.get("/settings/update-check")
def check_for_update() -> dict:
    """Check GitHub releases for a newer version."""
    from tidal_dl import update_available

    available, info = update_available()
    return {
        "current_version": __version__,
        "update_available": available,
        "latest_version": info.version.lstrip("v"),
        "release_url": info.url,
        "release_notes": info.release_info,
    }


class SettingsUpdate(BaseModel):
    download_base_path: str | None = None
    quality_audio: str | None = None
    cover_album_file: bool | None = None
    metadata_cover_embed: bool | None = None
    lyrics_embed: bool | None = None
    lyrics_file: bool | None = None
    skip_existing: bool | None = None
    skip_duplicate_isrc: bool | None = None
    downloads_concurrent_max: int | None = None
    download_source: str | None = None
    download_source_fallback: bool | None = None
    scan_paths: str | None = None
    format_track: str | None = None
    format_album: str | None = None
    format_playlist: str | None = None
    extract_flac: bool | None = None
    download_delay: bool | None = None
    upgrade_target_quality: str | None = None


@router.post("/browse-directory")
def browse_directory() -> dict:
    """Open a native OS directory picker and return the selected path."""
    import platform
    import subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            result = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select download directory")'],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip().rstrip("/")
                return {"path": path}
            raise HTTPException(status_code=400, detail="No directory selected")
        else:
            # Linux/Windows fallback via tkinter
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(title="Select download directory")
            root.destroy()
            if path:
                return {"path": path}
            raise HTTPException(status_code=400, detail="No directory selected")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Directory picker failed: {exc}") from exc


@router.patch("/settings")
def update_settings(update: SettingsUpdate) -> dict:
    """Update settings. Only provided fields are changed."""
    from tidal_dl.gui.security import validate_download_path

    updates = update.model_dump(exclude_none=True)

    _VALID_QUALITIES = {"NORMAL", "HIGH", "LOSSLESS", "HI_RES", "HI_RES_LOSSLESS"}
    if "quality_audio" in updates and updates["quality_audio"] not in _VALID_QUALITIES:
        raise HTTPException(status_code=400, detail="Invalid quality_audio value")

    if "download_base_path" in updates:
        path = updates["download_base_path"]
        if not validate_download_path(path):
            raise HTTPException(status_code=400, detail="Invalid download path")
        if path and not os.access(path, os.W_OK):
            raise HTTPException(status_code=400, detail="Download path is not writable")

    if settings_status().get("read_only"):
        recovery_fields = {"download_base_path", "scan_paths"}
        if any(field not in recovery_fields for field in updates):
            raise HTTPException(
                status_code=423,
                detail="Settings are read-only until access is restored or you choose a new folder",
            )

    s = Settings()
    for field, value in updates.items():
        if hasattr(s.data, field):
            setattr(s.data, field, value)
    s.save()
    return get_settings()
