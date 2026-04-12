"""Settings and auth status endpoints."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
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


@router.get("/auth/status")
def auth_status() -> dict:
    """Return OAuth session status."""
    tidal = get_tidal_instance()
    logged_in = tidal.session.check_login()
    username = ""
    if logged_in:
        try:
            user = tidal.session.user
            username = getattr(user, "name", "") or ""
        except Exception:
            pass
    return {"logged_in": logged_in, "username": username}


import threading

_login_lock = threading.Lock()
_login_state = {"status": "idle"}  # idle | pending | success | failed


@router.post("/auth/login")
def auth_login() -> dict:
    """Start OAuth login. Opens a Tidal link, polls in background until confirmed."""
    tidal = get_tidal_instance()
    with _login_lock:
        if tidal.session.check_login():
            _login_state["status"] = "success"
            return {"status": "already_logged_in"}

        if _login_state["status"] == "pending":
            return _login_state.copy()

        try:
            link_login, future = tidal.session.login_oauth()
            uri = link_login.verification_uri_complete or ""
            if uri and not uri.startswith("http"):
                uri = "https://" + uri

            _login_state.update({
                "status": "pending",
                "verification_uri": uri,
                "user_code": link_login.user_code,
                "expires_in": link_login.expires_in,
            })
        except Exception as exc:
            _login_state["status"] = "failed"
            raise HTTPException(status_code=500, detail=f"Login failed: {exc}") from exc

    def _wait_for_login():
        try:
            future.result(timeout=300)  # 5 min timeout
            with _login_lock:
                if tidal.login_finalize():
                    _login_state["status"] = "success"
                else:
                    _login_state["status"] = "failed"
        except TimeoutError:
            with _login_lock:
                _login_state["status"] = "timeout"
        except Exception:
            with _login_lock:
                _login_state["status"] = "failed"

    threading.Thread(target=_wait_for_login, daemon=True).start()
    with _login_lock:
        return _login_state.copy()


@router.get("/auth/login/status")
def auth_login_status() -> dict:
    """Poll login progress."""
    with _login_lock:
        return _login_state.copy()


@router.get("/hifi/status")
def hifi_status() -> dict:
    """Check HiFi API server availability."""
    from tidal_dl.hifi_api import HiFiApiClient

    try:
        client = HiFiApiClient(timeout=5)
        instances = client.instances
        alive = len(instances)
        return {"alive": alive, "instances": instances}
    except Exception:
        return {"alive": 0, "instances": []}


@router.get("/settings")
def read_settings() -> dict:
    """Return current settings."""
    return get_settings()


@router.get("/settings/status")
def read_settings_status() -> dict:
    """Return access status for configured music paths plus app version."""
    return settings_status()


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
        raise HTTPException(status_code=400, detail=f"Invalid quality_audio value")

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
