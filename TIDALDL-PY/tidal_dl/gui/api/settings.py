"""Settings and auth status endpoints."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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


_login_state = {"status": "idle"}  # idle | pending | success | failed


@router.post("/auth/login")
def auth_login() -> dict:
    """Start OAuth login. Opens a Tidal link, polls in background until confirmed."""
    import threading

    tidal = get_tidal_instance()
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

        def _wait_for_login():
            try:
                future.result(timeout=300)  # 5 min timeout
                if tidal.login_finalize():
                    _login_state["status"] = "success"
                else:
                    _login_state["status"] = "failed"
            except TimeoutError:
                _login_state["status"] = "timeout"
            except Exception:
                _login_state["status"] = "failed"

        threading.Thread(target=_wait_for_login, daemon=True).start()
        return _login_state.copy()
    except Exception as exc:
        _login_state["status"] = "failed"
        raise HTTPException(status_code=500, detail=f"Login failed: {exc}") from exc


@router.get("/auth/login/status")
def auth_login_status() -> dict:
    """Poll login progress."""
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

    if "download_base_path" in updates:
        path = updates["download_base_path"]
        if not validate_download_path(path):
            raise HTTPException(status_code=400, detail="Invalid download path")
        if path and not os.access(path, os.W_OK):
            raise HTTPException(status_code=400, detail="Download path is not writable")

    s = Settings()
    for field, value in updates.items():
        if hasattr(s.data, field):
            setattr(s.data, field, value)
    s.save()
    return get_settings()
