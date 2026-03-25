"""Playlist endpoints — list, tracks, sync."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from tidal_dl.config import Tidal
from tidal_dl.gui.api.search import _get_isrc_index, _serialize_track

router = APIRouter()

_CACHE_TTL = 300  # 5 minutes

_playlist_list_cache: dict = {"data": None, "ts": 0.0}
# playlist_id → {"data": dict, "ts": float}
_playlist_tracks_cache: dict[str, dict] = {}


def get_tidal_session():
    tidal = Tidal()
    return tidal.session


@router.get("/playlists")
def list_playlists() -> dict:
    """List user's Tidal playlists."""
    now = time.time()
    if _playlist_list_cache["data"] is not None and (now - _playlist_list_cache["ts"]) < _CACHE_TTL:
        return _playlist_list_cache["data"]

    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    playlists = session.user.playlists() or []
    result = {
        "playlists": [
            {
                "id": str(pl.id),
                "name": getattr(pl, "name", ""),
                "num_tracks": getattr(pl, "num_tracks", 0),
                "cover_url": _safe_image(pl),
                "last_updated": getattr(pl, "last_updated", None),
            }
            for pl in playlists
        ]
    }
    _playlist_list_cache["data"] = result
    _playlist_list_cache["ts"] = now
    return result


@router.get("/playlists/{playlist_id}/tracks")
def playlist_tracks(playlist_id: str) -> dict:
    """Get tracks for a specific playlist with local-match flags."""
    now = time.time()
    cached = _playlist_tracks_cache.get(playlist_id)
    if cached is not None and (now - cached["ts"]) < _CACHE_TTL:
        return cached["data"]

    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    try:
        playlist = session.playlist(playlist_id)
        tracks = playlist.tracks() or []
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Playlist not found: {exc}") from exc

    isrc_index = _get_isrc_index()
    result = {
        "tracks": [_serialize_track(t, isrc_index) for t in tracks],
        "total": len(tracks),
    }
    _playlist_tracks_cache[playlist_id] = {"data": result, "ts": now}
    return result


@router.post("/playlists/{playlist_id}/sync")
def sync_playlist(playlist_id: str) -> dict:
    """Trigger sync for a playlist — download missing tracks.

    Invalidates the tracks cache for this playlist so the next load
    reflects any newly downloaded tracks.
    """
    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    # Use cached tracks if fresh — avoids a redundant Tidal round-trip on sync.
    now = time.time()
    cached = _playlist_tracks_cache.get(playlist_id)
    if cached is not None and (now - cached["ts"]) < _CACHE_TTL:
        tracks_data = cached["data"]["tracks"]
        # Reconstruct minimal track objects needed for isrc check + trigger_download.
        # The cache stores serialized dicts, so work from those directly.
        isrc_index = _get_isrc_index()
        missing_ids = [
            t["id"] for t in tracks_data
            if not isrc_index.contains(t.get("isrc", "") or "")
        ]
        total = len(tracks_data)
    else:
        try:
            playlist = session.playlist(playlist_id)
            raw_tracks = playlist.tracks() or []
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        isrc_index = _get_isrc_index()
        missing_ids = [
            t.id for t in raw_tracks
            if not isrc_index.contains(getattr(t, "isrc", "") or "")
        ]
        total = len(raw_tracks)

    # Invalidate tracks cache — after sync, local state changes so next load re-fetches.
    _playlist_tracks_cache.pop(playlist_id, None)

    if not missing_ids:
        return {"status": "up_to_date", "missing": 0}

    from tidal_dl.gui.api.downloads import trigger_download

    trigger_download(missing_ids)

    return {"status": "syncing", "missing": len(missing_ids), "total": total}


def _safe_image(obj: Any) -> str:
    try:
        return obj.image(320)
    except Exception:
        return ""
