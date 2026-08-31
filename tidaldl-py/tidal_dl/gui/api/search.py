"""GET /api/search — Tidal search with ISRC cross-reference."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from tidal_dl.config import Tidal
from tidal_dl.gui.services.db import get_library_db

router = APIRouter()


def _get_library_db():
    return get_library_db()


def get_tidal():
    return Tidal()


def get_tidal_session():
    from tidal_dl.gui.api.settings import ensure_tidal_logged_in

    tidal = get_tidal()
    ensure_tidal_logged_in(tidal)
    return tidal.session


def _serialize_track(track: Any, isrc_index: Any = None) -> dict:
    artists = track.artists or []
    artist_name = ", ".join(a.name for a in artists if a.name)
    album = track.album
    album_name = album.name if album else ""
    album_id = album.id if album else None

    cover_url = ""
    if album:
        try:
            cover_url = album.image(320)
        except Exception:  # noqa: BLE001, S110
            pass

    isrc = getattr(track, "isrc", "") or ""
    local_path = None
    local_row = None
    if isrc:
        db = _get_library_db()
        local_row = next(
            (row for row in db.tracks_by_isrc(isrc) if Path(row.get("path") or "").is_file()),
            None,
        )
        if local_row:
            local_path = local_row["path"]
    is_local = bool(local_path)

    tags = getattr(track, "media_metadata_tags", None) or []
    if "HIRES_LOSSLESS" in tags:
        quality = "HI_RES_LOSSLESS"
    elif "HIRES" in tags:
        quality = "HI_RES"
    elif "DOLBY_ATMOS" in tags:
        quality = "DOLBY_ATMOS"
    else:
        quality = getattr(track, "audio_quality", "") or ""

    result = {
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
    if local_row:
        result.update({
            "local_path": local_path,
            "path": local_path,
            "quality": local_row.get("quality") or quality,
            "format": local_row.get("format") or "",
            "codec": local_row.get("codec") or "unknown",
        })
    return result


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

    from tidal_dl.gui.api.settings import call_tidal

    tidal = get_tidal()
    try:
        results = call_tidal(
            tidal,
            lambda: tidal.session.search(
                q, models=[_model_for_type(type)], limit=limit, offset=offset
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tidal search failed: {exc}") from exc

    if type == "tracks":
        tracks = results.get("tracks", []) or []
        serialized = [_serialize_track(t) for t in tracks]
        serialized.sort(key=lambda t: (not t["is_local"],))
        return {
            "tracks": serialized,
            "total": len(serialized),
        }

    items = results.get(type, []) or []
    serializer = _serialize_album if type == "albums" else _serialize_item
    return {type: [serializer(item) for item in items], "total": len(items)}


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
    except Exception:  # noqa: BLE001, S110
        pass
    result = {"id": item.id, "name": getattr(item, "name", ""), "cover_url": cover_url}
    if hasattr(item, "artist") and item.artist:
        result["artist"] = getattr(item.artist, "name", str(item.artist))
    if hasattr(item, "roles") and item.roles:
        try:
            roles = [r.value if hasattr(r, "value") else str(r) for r in item.roles]
            result["roles"] = ", ".join(r.replace("_", " ").title() for r in roles[:3])
        except Exception:  # noqa: BLE001, S110
            pass
    if hasattr(item, "num_tracks"):
        result["num_tracks"] = item.num_tracks
    return result


def _serialize_album(item: Any) -> dict:
    result = _serialize_item(item)
    tags = {
        str(tag).upper()
        for tag in (getattr(item, "media_metadata_tags", None) or [])
    }
    modes = {
        str(mode).upper() for mode in (getattr(item, "audio_modes", None) or [])
    }
    raw_quality = str(getattr(item, "audio_quality", "") or "").upper()

    if "HIRES_LOSSLESS" in tags:
        quality = "HI_RES_LOSSLESS"
    elif "HIRES" in tags:
        quality = "HI_RES"
    elif raw_quality in {"HI_RES_LOSSLESS", "HI_RES", "LOSSLESS", "HIGH", "LOW"}:
        quality = raw_quality
    else:
        quality = "UNKNOWN"

    explicit = getattr(item, "explicit", None)
    result.update(
        {
            "quality": quality,
            "atmos": "DOLBY_ATMOS" in tags or "DOLBY_ATMOS" in modes,
            "explicit": explicit if isinstance(explicit, bool) else None,
        }
    )
    return result
