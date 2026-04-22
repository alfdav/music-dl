"""Setup status and onboarding validation endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


@router.get("/setup/status")
def setup_status() -> dict:
    """Return whether the app is configured: auth and scan paths."""
    from tidal_dl.config import Settings, Tidal

    tidal = Tidal()
    try:
        logged_in = tidal.session.check_login()
    except Exception:
        logged_in = False

    s = Settings()
    scan_paths = (s.data.scan_paths or "").strip()
    scan_paths_configured = len(scan_paths) > 0

    return {
        "logged_in": logged_in,
        "scan_paths_configured": scan_paths_configured,
        "setup_complete": logged_in and scan_paths_configured,
    }


class ValidatePathRequest(BaseModel):
    path: str


@router.post("/setup/validate-path")
def validate_path(body: ValidatePathRequest) -> dict:
    """Check whether a proposed download path is safe and usable."""
    from tidal_dl.gui.security import validate_download_path

    path_str = body.path.strip()
    if not path_str:
        raise HTTPException(status_code=400, detail="Path must not be empty")

    resolved = str(Path(path_str).expanduser())
    valid = validate_download_path(resolved)
    return {
        "path": resolved,
        "valid": valid,
        "reason": None if valid else "Path does not exist or is not a writable directory",
    }
