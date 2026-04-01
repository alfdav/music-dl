"""Local lyrics API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from tidal_dl.gui.api.playback import get_download_paths
from tidal_dl.gui.lyrics_local import read_local_lyrics
from tidal_dl.gui.security import resolve_local_audio_path

router = APIRouter(prefix="/lyrics")


@router.get("/local")
def get_local_lyrics(path: str | None = Query(None, description="Absolute path to local audio file")):
    resolution = resolve_local_audio_path(path, get_download_paths())
    if resolution.kind == "bad_request":
        raise HTTPException(status_code=400, detail="Missing or invalid path")
    if resolution.kind == "forbidden":
        raise HTTPException(status_code=403, detail="Access denied")
    if resolution.kind in {"not_found", "not_audio"}:
        raise HTTPException(status_code=404, detail="Track not found")
    if resolution.kind != "ok" or resolution.path is None:
        raise HTTPException(status_code=500, detail="Unexpected local lyrics resolution failure")
    return read_local_lyrics(resolution.path)
