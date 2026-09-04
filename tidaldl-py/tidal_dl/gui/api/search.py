"""GET /api/search — Tidal search with ISRC cross-reference."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from tidal_dl.config import Tidal
from tidal_dl.gui.services.db import get_library_db
from tidal_dl.gui.tidal_ref import TidalRef, looks_like_web_url, parse_tidal_ref
from tidal_dl.helper.library_scanner import path_has_skipped_scan_dir

router = APIRouter()


def _get_library_db():
    return get_library_db()


def _live_library_row(db: Any, isrc: str) -> dict | None:
    """Prefer a live library file. Never rank a `#recycle` / trash path first."""
    if not isrc:
        return None
    for row in db.tracks_by_isrc(isrc):
        path = row.get("path") or ""
        if path_has_skipped_scan_dir(path):
            continue
        if Path(path).is_file():
            return row
    return None


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
        local_row = _live_library_row(db, isrc)
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

    artist_id = getattr(artists[0], "id", None) if artists else None
    result = {
        "id": track.id,
        "name": track.full_name or track.name,
        "artist": artist_name,
        "album": album_name,
        "album_id": album_id,
        "artist_id": artist_id,
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


def _empty(type_str: str, error: str) -> dict:
    key = type_str if type_str in {"tracks", "albums", "artists", "playlists"} else "tracks"
    return {key: [], "total": 0, "error": error}


def _fold(value: str) -> str:
    if not value:
        return ""
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )
    cleaned = re.sub(r"[^\w]+", " ", stripped.casefold())
    return " ".join(cleaned.split())


def _token_overlap(left: str, right: str) -> float:
    a = set(_fold(left).split())
    b = set(_fold(right).split())
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a), len(b))


def _name_score(query: str, name: str) -> float:
    q = _fold(query)
    n = _fold(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if q in n or n in q:
        return 0.85
    return _token_overlap(q, n)


def _strong_title_match(query: str, tracks: list[Any]) -> bool:
    return any(
        _name_score(query, getattr(track, "full_name", None) or getattr(track, "name", "") or "")
        >= 0.7
        for track in tracks
    )


def _track_artist_names(track: Any) -> list[str]:
    artists = getattr(track, "artists", None) or []
    names = [getattr(artist, "name", "") or "" for artist in artists]
    if not names:
        artist = getattr(track, "artist", None)
        if artist is not None:
            names = [getattr(artist, "name", None) or str(artist)]
    return [name for name in names if name]


def _strong_artist_match(query: str, tracks: list[Any]) -> bool:
    return any(
        _name_score(query, name) >= 0.7
        for track in tracks
        for name in _track_artist_names(track)
    )


def _use_album_title_fallback(query: str, tracks: list[Any]) -> bool:
    """Album-title fallback only when track search missed, or the query is an album title."""
    if not tracks:
        return True
    if _strong_title_match(query, tracks):
        return False
    return not _strong_artist_match(query, tracks)


def _session_get(session: Any, kind: str, item_id: str) -> Any:
    if kind == "track":
        try:
            return session.track(item_id, with_album=True)
        except TypeError:
            return session.track(item_id)
    if kind == "album":
        return session.album(item_id)
    if kind == "artist":
        return session.artist(item_id)
    if kind == "playlist":
        return session.playlist(item_id)
    raise ValueError(f"unsupported Tidal kind: {kind}")


def _resolve_ref(tidal: Any, ref: TidalRef) -> dict:
    from fastapi import HTTPException

    from tidal_dl.gui.api.settings import call_tidal

    try:
        item = call_tidal(tidal, lambda: _session_get(tidal.session, ref.kind, ref.id))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        return _empty(
            {"track": "tracks", "album": "albums", "artist": "artists", "playlist": "playlists"}[
                ref.kind
            ],
            f"Tidal {ref.kind} not found",
        )

    if ref.kind == "track":
        serialized = _serialize_track(item)
        album_id = serialized.get("album_id")
        return {
            "tracks": [serialized],
            "total": 1,
            "resolve": {"kind": "track", "id": item.id, "album_id": album_id},
        }
    if ref.kind == "album":
        serialized = _serialize_album(item)
        return {
            "albums": [serialized],
            "total": 1,
            "resolve": {"kind": "album", "id": item.id, "name": serialized.get("name")},
        }
    if ref.kind == "artist":
        serialized = _serialize_item(item)
        return {
            "artists": [serialized],
            "total": 1,
            "resolve": {
                "kind": "artist",
                "id": item.id,
                "name": serialized.get("name"),
            },
        }
    serialized = _serialize_item(item)
    return {
        "playlists": [serialized],
        "total": 1,
        "resolve": {
            "kind": "playlist",
            "id": item.id,
            "name": serialized.get("name"),
            "cover_url": serialized.get("cover_url"),
            "num_tracks": serialized.get("num_tracks"),
        },
    }


def _album_tracks_for_query(tidal: Any, query: str, limit: int) -> list[Any] | None:
    from fastapi import HTTPException
    from tidalapi.album import Album

    from tidal_dl.gui.api.settings import call_tidal

    try:
        results = call_tidal(
            tidal,
            lambda: tidal.session.search(query, models=[Album], limit=min(limit, 10)),
        )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        return None

    albums = results.get("albums", []) or []
    ranked = sorted(
        albums,
        key=lambda album: _name_score(query, getattr(album, "name", "") or ""),
        reverse=True,
    )
    best = next(
        (album for album in ranked if _name_score(query, getattr(album, "name", "") or "") >= 0.7),
        None,
    )
    if best is None:
        return None

    def _load_tracks():
        loaded = tidal.session.album(best.id)
        return loaded.tracks() or []

    try:
        return call_tidal(tidal, _load_tracks)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        try:
            return list(best.tracks() or [])
        except Exception:  # noqa: BLE001
            return None


def _serialize_track_hits(tracks: list[Any]) -> list[dict]:
    serialized = [_serialize_track(track) for track in tracks]
    serialized.sort(key=lambda item: (
        path_has_skipped_scan_dir(item.get("path") or item.get("local_path") or ""),
        not item["is_local"],
    ))
    return serialized


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

    from tidal_dl.gui.api.settings import (
        _login_required_error,
        _persisted_refresh_token,
        _session_logged_in,
        call_tidal,
    )

    tidal = get_tidal()
    if not _persisted_refresh_token(tidal) and not _session_logged_in(
        getattr(tidal, "session", None)
    ):
        raise _login_required_error()

    ref = parse_tidal_ref(q, type_hint=type)
    if ref:
        return _resolve_ref(tidal, ref)
    if looks_like_web_url(q):
        return _empty(type, "Not a recognized Tidal URL")
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
        if _use_album_title_fallback(q, tracks):
            album_tracks = _album_tracks_for_query(tidal, q, limit)
            if album_tracks:
                serialized = _serialize_track_hits(album_tracks)
                return {"tracks": serialized, "total": len(serialized)}
        serialized = _serialize_track_hits(tracks)
        return {"tracks": serialized, "total": len(serialized)}

    items = results.get(type, []) or []
    serializer = _serialize_album if type == "albums" else _serialize_item
    return {type: [serializer(item) for item in items], "total": len(items)}


@router.get("/artists/{artist_id}/albums")
def artist_albums(artist_id: int) -> dict:
    """Tidal discography for an artist id — used by the hybrid artist gallery."""
    from fastapi import HTTPException

    from tidal_dl.gui.api.settings import call_tidal

    tidal = get_tidal()

    def _load():
        artist = tidal.session.artist(artist_id)
        albums: list[Any] = []
        for getter_name in ("get_albums", "get_ep_singles"):
            getter = getattr(artist, getter_name, None)
            if not callable(getter):
                continue
            try:
                albums.extend(getter(limit=50) or [])
            except TypeError:
                albums.extend(getter() or [])
        return artist, albums

    try:
        artist, albums = call_tidal(tidal, _load)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Artist not found: {exc}") from exc

    serialized = [_serialize_album(album) for album in albums]
    return {
        "artist": _serialize_item(artist),
        "albums": serialized,
        "total": len(serialized),
    }


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
