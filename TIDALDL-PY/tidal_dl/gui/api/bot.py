"""Bot-facing API endpoints.

All routes live under /bot and are gated by bearer-token authentication
via the require_bot_auth dependency. See cavekit-bot-api.md for the
full requirements.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from tidal_dl.gui.security import (
    sign_bot_stream_token,
    validate_bot_bearer,
)
from tidal_dl.helper.local_playlist_resolver import (
    parse_playlist_file,
    resolve_playlist_name,
)

router = APIRouter(prefix="/bot")

# --- Auth dependency -------------------------------------------------------


def require_bot_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency that enforces bot bearer-token auth."""
    if not validate_bot_bearer(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized bot client")


# --- URL pattern detection -------------------------------------------------

# Matches Tidal track URLs: tidal.com/track/123, tidal.com/browse/track/123,
# listen.tidal.com/track/123, desktop.tidal.com/track/123
_TIDAL_TRACK_URL = re.compile(
    r"https?://(?:[a-z-]+\.)?tidal\.com/(?:browse/)?track/(\d+)",
    re.IGNORECASE,
)

# Matches Tidal playlist URLs (UUID format)
_TIDAL_PLAYLIST_URL = re.compile(
    r"https?://(?:[a-z-]+\.)?tidal\.com/(?:browse/)?playlist/([a-f0-9-]{36})",
    re.IGNORECASE,
)


# --- Request models --------------------------------------------------------


class ResolveRequest(BaseModel):
    query: str


class PlayableRequest(BaseModel):
    item_id: str


class DownloadRequest(BaseModel):
    item_id: str


# --- Helpers ---------------------------------------------------------------


def _local_playlist_roots() -> list[Path]:
    """Directories to search for local .m3u/.m3u8 files."""
    from tidal_dl.config import Settings

    settings = Settings()
    roots: list[Path] = []
    if settings.data.download_base_path:
        roots.append(Path(settings.data.download_base_path).expanduser())
    if settings.data.scan_paths:
        for p in settings.data.scan_paths.split(","):
            p = p.strip()
            if p:
                roots.append(Path(p).expanduser())
    return roots


def _encode_local_id(path: str) -> str:
    """Encode a local audio path as a stable bot-item identifier."""
    return "local:" + base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")


def _decode_local_id(item_id: str) -> str | None:
    """Decode a local: item_id back into its filesystem path."""
    if not item_id.startswith("local:"):
        return None
    raw = item_id[len("local:"):]
    # Restore padding
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode()).decode()
    except Exception:
        return None


def _lookup_local_metadata(path: str) -> dict[str, Any]:
    """Look up scanned metadata for a local audio path. Returns empty-ish defaults on miss."""
    from tidal_dl.helper.library_db import LibraryDB
    from tidal_dl.helper.path import path_config_base

    db = LibraryDB(Path(path_config_base()) / "library.db")
    try:
        db.open()
        row = db._conn.execute(
            "SELECT title, artist, duration FROM scanned WHERE path = ?", (path,)
        ).fetchone()
    except Exception:
        row = None
    finally:
        try:
            db.close()
        except Exception:
            pass

    if row:
        return {
            "title": row["title"] or Path(path).stem,
            "artist": row["artist"] or "",
            "duration": row["duration"] or 0,
        }
    return {"title": Path(path).stem, "artist": "", "duration": 0}


def _serialize_tidal_track(track: Any, isrc_index: Any | None = None) -> dict:
    """Turn a tidalapi Track into a bot queue item."""
    from tidal_dl.gui.api.search import _get_isrc_index

    if isrc_index is None:
        isrc_index = _get_isrc_index()

    artists = track.artists or []
    artist_name = ", ".join(a.name for a in artists if a.name)
    isrc = getattr(track, "isrc", "") or ""
    is_local = isrc_index.contains(isrc) if isrc else False

    return {
        "id": f"tidal:{track.id}",
        "title": track.full_name or track.name,
        "artist": artist_name,
        "source_type": "tidal",
        "local": is_local,
        "duration": track.duration or 0,
        "isrc": isrc,
    }


def _serialize_local_item(path: str) -> dict:
    """Turn a local audio path into a bot queue item."""
    meta = _lookup_local_metadata(path)
    return {
        "id": _encode_local_id(path),
        "title": meta["title"],
        "artist": meta["artist"],
        "source_type": "local",
        "local": True,
        "duration": meta["duration"],
    }


# --- Resolve endpoint (R2) -------------------------------------------------


@router.post("/play/resolve")
def resolve_play_request(
    payload: ResolveRequest, _: None = Depends(require_bot_auth)
) -> dict:
    """Resolve a /play input into choices or queueable items.

    Supports four input forms:
      - Tidal track URL → single-item list
      - Tidal playlist URL → ordered items
      - Local playlist name → ordered items
      - Free text → up to 5 candidates
    """
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    # 1. Tidal track URL
    track_match = _TIDAL_TRACK_URL.search(query)
    if track_match:
        from tidal_dl.gui.api.search import get_tidal_session

        session = get_tidal_session()
        if not session.check_login():
            raise HTTPException(status_code=401, detail="Tidal session not logged in")
        try:
            track = session.track(int(track_match.group(1)))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Tidal track lookup failed: {exc}") from exc
        return {"kind": "track", "items": [_serialize_tidal_track(track)]}

    # 2. Tidal playlist URL
    playlist_match = _TIDAL_PLAYLIST_URL.search(query)
    if playlist_match:
        from tidal_dl.gui.api.search import _get_isrc_index, get_tidal_session

        session = get_tidal_session()
        if not session.check_login():
            raise HTTPException(status_code=401, detail="Tidal session not logged in")
        try:
            playlist = session.playlist(playlist_match.group(1))
            tracks = playlist.tracks()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Tidal playlist lookup failed: {exc}") from exc
        isrc_index = _get_isrc_index()
        items = [_serialize_tidal_track(t, isrc_index) for t in tracks]
        return {"kind": "playlist", "items": items}

    # 3. Local playlist name (only if no URL scheme present)
    if "://" not in query:
        roots = _local_playlist_roots()
        match_path = resolve_playlist_name(query, roots)
        if match_path is not None:
            track_paths = parse_playlist_file(match_path)
            items = [_serialize_local_item(p) for p in track_paths]
            return {"kind": "playlist", "items": items}

    # 4. Free-text search — 5 candidates, locals first
    from tidal_dl.gui.api.search import _get_isrc_index, get_tidal_session

    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Tidal session not logged in")

    try:
        from tidalapi.media import Track

        results = session.search(query, models=[Track], limit=10, offset=0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tidal search failed: {exc}") from exc

    tracks = results.get("tracks", []) or []
    isrc_index = _get_isrc_index()
    candidates = [_serialize_tidal_track(t, isrc_index) for t in tracks]
    # Prioritize local matches (Option A — matches existing search.py behavior)
    candidates.sort(key=lambda c: (not c["local"],))
    return {"kind": "choices", "choices": candidates[:5]}


# --- Playable source endpoint (R3) -----------------------------------------


@router.post("/playable")
def get_playable_source(
    payload: PlayableRequest, _: None = Depends(require_bot_auth)
) -> dict:
    """Turn a resolved item into a bot-consumable playable source.

    Returns a short-lived stream URL that the bot fetches audio from.
    The URL is signed — the /bot-stream/{token} endpoint verifies it.
    """
    item_id = payload.item_id

    # Local item
    local_path = _decode_local_id(item_id)
    if local_path is not None:
        if not Path(local_path).is_file():
            raise HTTPException(status_code=404, detail="Local file not found")
        meta = _lookup_local_metadata(local_path)
        token = sign_bot_stream_token(
            {"kind": "local", "path": local_path}, ttl_seconds=300
        )
        return {
            "url": f"/api/playback/bot-stream/{token}",
            "content_type": "audio/flac",
            "title": meta["title"],
            "artist": meta["artist"],
            "duration": meta["duration"],
        }

    # Tidal item: id is "tidal:<track_id>"
    if item_id.startswith("tidal:"):
        try:
            track_id = int(item_id[len("tidal:"):])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Tidal item_id")
        from tidal_dl.gui.api.search import get_tidal_session

        session = get_tidal_session()
        if not session.check_login():
            raise HTTPException(status_code=401, detail="Tidal session not logged in")
        try:
            track = session.track(track_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Tidal track lookup failed: {exc}") from exc

        token = sign_bot_stream_token(
            {"kind": "tidal", "track_id": str(track_id)}, ttl_seconds=300
        )
        return {
            "url": f"/api/playback/bot-stream/{token}",
            "content_type": "audio/flac",
            "title": track.full_name or track.name,
            "artist": ", ".join(a.name for a in (track.artists or []) if a.name),
            "duration": track.duration or 0,
        }

    raise HTTPException(status_code=400, detail="Unknown item_id format")


# --- Download gateway endpoints (R6) ---------------------------------------


@router.post("/download")
def trigger_bot_download(
    payload: DownloadRequest, _: None = Depends(require_bot_auth)
) -> dict:
    """Trigger an explicit download for a resolved item."""
    item_id = payload.item_id

    # Only Tidal items can be downloaded (locals are already local)
    if not item_id.startswith("tidal:"):
        raise HTTPException(status_code=400, detail="Only Tidal items can be downloaded")
    try:
        track_id = int(item_id[len("tidal:"):])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Tidal item_id")

    from tidal_dl.gui.api.downloads import _active, _lock
    from tidal_dl.gui.api.search import get_tidal_session

    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Tidal session not logged in")

    try:
        track = session.track(track_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tidal track lookup failed: {exc}") from exc

    # Delegate to existing download subsystem by placing into _active map
    # The background download thread picks up queued entries
    from tidal_dl.gui.api.downloads import DownloadEntry

    with _lock:
        if track_id not in _active:
            entry = DownloadEntry(track_id, track.full_name or track.name)
            entry.artist = ", ".join(a.name for a in (track.artists or []) if a.name)
            entry.status = "queued"
            _active[track_id] = entry
        status = _active[track_id].status

    return {"job_id": str(track_id), "status": status}


@router.get("/downloads/{job_id}")
def get_bot_download_status(
    job_id: str, _: None = Depends(require_bot_auth)
) -> dict:
    """Poll the status of a bot-triggered download."""
    try:
        track_id = int(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job_id")

    from tidal_dl.gui.api.downloads import _active, _lock

    with _lock:
        entry = _active.get(track_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "job_id": job_id,
            "status": entry.status,
            "progress": entry.progress,
            "title": entry.name,
            "artist": entry.artist,
            "started_at": entry.started_at,
            "finished_at": entry.finished_at,
        }
