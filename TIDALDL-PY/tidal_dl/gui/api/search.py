"""GET /api/search — Tidal search with ISRC cross-reference."""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Query

from tidal_dl.config import Tidal
from tidal_dl.helper.isrc_index import IsrcIndex
from tidal_dl.helper.path import path_config_base

router = APIRouter()
_isrc_index: IsrcIndex | None = None
_isrc_lock = threading.Lock()


def _get_isrc_index() -> IsrcIndex:
    global _isrc_index
    with _isrc_lock:
        if _isrc_index is None:
            from pathlib import Path

            _isrc_index = IsrcIndex(Path(path_config_base()) / "isrc_index.json")
            _isrc_index.load()
        return _isrc_index


def get_tidal_session():
    tidal = Tidal()
    return tidal.session


def _serialize_track(track: Any, isrc_index: IsrcIndex) -> dict:
    artists = track.artists or []
    artist_name = ", ".join(a.name for a in artists if a.name)
    album = track.album
    album_name = album.name if album else ""
    album_id = album.id if album else None

    cover_url = ""
    if album:
        try:
            cover_url = album.image(320)
        except Exception:
            pass

    isrc = getattr(track, "isrc", "") or ""
    is_local = isrc_index.contains(isrc) if isrc else False

    # Derive best available quality from media_metadata_tags
    tags = getattr(track, "media_metadata_tags", None) or []
    if "HIRES_LOSSLESS" in tags:
        quality = "HI_RES_LOSSLESS"
    elif "HIRES" in tags:
        quality = "HI_RES"
    elif "DOLBY_ATMOS" in tags:
        quality = "DOLBY_ATMOS"
    else:
        quality = getattr(track, "audio_quality", "") or ""

    return {
        "id": track.id,
        "name": track.full_name or track.name,
        "artist": artist_name,
        "album": album_name,
        "album_id": album_id,
        "cover_url": cover_url,
        "duration": track.duration or 0,
        "quality": quality,
        "isrc": isrc,
        "is_local": is_local,
    }


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, description="Search query"),
    type: str = Query(
        "tracks", description="Search type: tracks, albums, artists, playlists"
    ),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    from fastapi import HTTPException

    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    try:
        results = session.search(
            q, models=[_model_for_type(type)], limit=limit, offset=offset
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tidal search failed: {exc}") from exc
    isrc_index = _get_isrc_index()

    if type == "tracks":
        tracks = results.get("tracks", []) or []
        serialized = [_serialize_track(t, isrc_index) for t in tracks]
        serialized.sort(key=lambda t: (not t["is_local"],))
        return {
            "tracks": serialized,
            "total": len(serialized),
        }

    items = results.get(type, []) or []
    return {type: [_serialize_item(item) for item in items], "total": len(items)}


def _model_for_type(type_str: str):
    from tidalapi.album import Album
    from tidalapi.artist import Artist
    from tidalapi.media import Track
    from tidalapi.playlist import Playlist

    return {"tracks": Track, "albums": Album, "artists": Artist, "playlists": Playlist}.get(
        type_str, Track
    )


def _serialize_item(item: Any) -> dict:
    cover_url = ""
    try:
        cover_url = item.image(320)
    except Exception:
        pass
    result = {"id": item.id, "name": getattr(item, "name", ""), "cover_url": cover_url}
    # Album: include artist name
    if hasattr(item, "artist") and item.artist:
        result["artist"] = getattr(item.artist, "name", str(item.artist))
    # Artist: include roles
    if hasattr(item, "roles") and item.roles:
        try:
            roles = [r.value if hasattr(r, "value") else str(r) for r in item.roles]
            result["roles"] = ", ".join(r.replace("_", " ").title() for r in roles[:3])
        except Exception:
            pass
    # Playlist: include track count
    if hasattr(item, "num_tracks"):
        result["num_tracks"] = item.num_tracks
    return result
