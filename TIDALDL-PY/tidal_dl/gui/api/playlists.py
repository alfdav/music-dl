"""Playlist endpoints — list, tracks, sync."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from tidal_dl.config import Tidal
from tidal_dl.gui.api.search import _get_isrc_index, _serialize_track
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

router = APIRouter()

_CACHE_TTL = 300  # 5 minutes

_playlist_list_cache: dict = {"data": None, "ts": 0.0}
# playlist_id → {"data": dict, "ts": float}
_playlist_tracks_cache: dict[str, dict] = {}


def get_tidal_session():
    tidal = Tidal()
    return tidal.session


def _get_playlist_db() -> LibraryDB:
    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    return db


def _normalize(value: str | None) -> str:
    return (value or "").strip().casefold()


def _title_artist_key(title: str | None, artist: str | None) -> tuple[str, str] | None:
    left = _normalize(title)
    right = _normalize(artist)
    if not left or not right:
        return None
    return left, right


def _build_title_artist_index(all_tracks: list[dict]) -> dict[tuple[str, str], list[dict]]:
    index: dict[tuple[str, str], list[dict]] = {}
    for row in all_tracks:
        key = _title_artist_key(row.get("title"), row.get("artist"))
        if key is None:
            continue
        index.setdefault(key, []).append(row)
    return index


def _best_local_row(
    track_data: dict,
    db: LibraryDB,
    all_tracks: list[dict],
    fallback_index: dict[tuple[str, str], list[dict]] | None = None,
) -> dict | None:
    isrc = track_data.get("isrc") or ""
    candidates: list[dict] = []

    if isrc:
        candidates = db.tracks_by_isrc(isrc)

    target_album = _normalize(track_data.get("album"))

    if not candidates:
        key = _title_artist_key(track_data.get("name"), track_data.get("artist"))
        if key is not None:
            if fallback_index is not None:
                candidates = list(fallback_index.get(key, []))
            else:
                candidates = [
                    row for row in all_tracks
                    if _title_artist_key(row.get("title"), row.get("artist")) == key
                ]

            if len(candidates) > 1 and target_album:
                album_matches = [
                    row for row in candidates
                    if _normalize(row.get("album")) == target_album
                ]
                if album_matches:
                    candidates = album_matches
                else:
                    return None

    if not candidates:
        return None

    candidates.sort(key=lambda row: (
        0 if _normalize(row.get("album")) == target_album else 1,
        len(row.get("path") or ""),
        row.get("path") or "",
    ))
    return candidates[0]



def _serialize_playlist_tracks(session, playlist_id: str) -> list[dict]:
    try:
        playlist = session.playlist(playlist_id)
        tracks = playlist.tracks() or []
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Playlist not found: {exc}") from exc

    isrc_index = _get_isrc_index()
    db = _get_playlist_db()
    try:
        all_tracks = db.all_tracks()
        fallback_index = _build_title_artist_index(all_tracks)
        serialized = []
        for track in tracks:
            data = _serialize_track(track, isrc_index)
            local_row = _best_local_row(data, db, all_tracks, fallback_index=fallback_index)
            data["is_local"] = bool(local_row)
            if local_row:
                data["local_path"] = local_row.get("path") or ""
                data["path"] = local_row.get("path") or ""
                if local_row.get("quality"):
                    data["quality"] = local_row["quality"]
                if local_row.get("format"):
                    data["format"] = local_row["format"]
            serialized.append(data)
    finally:
        db.close()

    return serialized



def _playlist_tracks_data(session, playlist_id: str) -> dict:
    now = time.time()
    cached = _playlist_tracks_cache.get(playlist_id)
    if cached is not None and (now - cached["ts"]) < _CACHE_TTL:
        return cached["data"]

    tracks = _serialize_playlist_tracks(session, playlist_id)
    result = {
        "tracks": tracks,
        "total": len(tracks),
    }
    _playlist_tracks_cache[playlist_id] = {"data": result, "ts": now}
    return result


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

    # Use DB-cached playlist covers to survive server restarts
    db = _get_playlist_db()
    try:
        items = []
        for pl in playlists:
            pl_id = str(pl.id)
            cover = db.get_playlist_cover(pl_id)
            if cover is None:
                cover = _safe_image(pl)
                db.set_playlist_cover(pl_id, cover)
            items.append({
                "id": pl_id,
                "name": getattr(pl, "name", ""),
                "num_tracks": getattr(pl, "num_tracks", 0),
                "cover_url": cover,
                "last_updated": getattr(pl, "last_updated", None),
            })
        db.commit()
    finally:
        db.close()

    result = {"playlists": items}
    _playlist_list_cache["data"] = result
    _playlist_list_cache["ts"] = now
    return result


@router.get("/playlists/{playlist_id}/tracks")
def playlist_tracks(playlist_id: str) -> dict:
    """Get tracks for a specific playlist with local-match flags."""
    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    return _playlist_tracks_data(session, playlist_id)


@router.post("/playlists/{playlist_id}/sync")
def sync_playlist(playlist_id: str) -> dict:
    """Trigger sync for a playlist — download tracks missing from the local library."""
    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    tracks_data = _playlist_tracks_data(session, playlist_id)["tracks"]
    missing_ids = [t["id"] for t in tracks_data if not t.get("is_local") and t.get("id")]
    total = len(tracks_data)

    # Invalidate tracks cache — after sync, local state changes so next load re-fetches.
    _playlist_tracks_cache.pop(playlist_id, None)

    if not missing_ids:
        return {"status": "up_to_date", "missing": 0, "total": total}

    from tidal_dl.gui.api.downloads import trigger_download

    trigger_download(missing_ids)

    return {"status": "syncing", "missing": len(missing_ids), "total": total}


def _safe_image(obj: Any) -> str:
    try:
        return obj.image(320)
    except Exception:
        return ""
