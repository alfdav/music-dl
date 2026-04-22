"""Home view API — play tracking and stats aggregation."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

router = APIRouter()

# First-call latency on /home is dominated by the NAS probe in
# _scan_directories() (stat() on a cold-mounted remote volume). Cache the
# boolean outcome for a short window so navigating away and back — or the
# Tauri webview's race between initial /home and a second navigate() —
# doesn't pay the probe cost twice. 2s is short enough that legitimate
# mount/unmount events surface quickly.
_VOLUME_CACHE_TTL_S = 2.0
_volume_cache = {"ts": 0.0, "ok": False}
_volume_cache_lock = threading.Lock()


def _volume_available_cached() -> bool:
    """Return whether any scan directory exists, cached for _VOLUME_CACHE_TTL_S."""
    from tidal_dl.gui.api.library import _scan_directories

    now = time.monotonic()
    with _volume_cache_lock:
        if now - _volume_cache["ts"] < _VOLUME_CACHE_TTL_S:
            return _volume_cache["ok"]
    ok = len(_scan_directories()) > 0
    with _volume_cache_lock:
        _volume_cache["ts"] = now
        _volume_cache["ok"] = ok
    return ok


_db: LibraryDB | None = None  # Compatibility alias for tests/debugging.
_db_local = threading.local()
_db_generation = 0
_db_generation_lock = threading.Lock()


def _close_thread_db() -> None:
    db = getattr(_db_local, "db", None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
    _db_local.db = None
    _db_local.generation = -1


def _invalidate_db_cache() -> None:
    global _db, _db_generation
    _close_thread_db()
    _db = None
    with _db_generation_lock:
        _db_generation += 1


def _get_db() -> LibraryDB:
    global _db
    db_path = Path(path_config_base()) / "library.db"
    db = getattr(_db_local, "db", None)
    generation = getattr(_db_local, "generation", -1)

    if db is not None and (generation != _db_generation or db._path != db_path):
        _close_thread_db()
        db = None

    if db is None:
        db = LibraryDB(db_path)
        db.open()
        _db_local.db = db
        _db_local.generation = _db_generation
    else:
        try:
            db._conn.execute("SELECT 1")
        except Exception:
            _close_thread_db()
            db = LibraryDB(db_path)
            db.open()
            _db_local.db = db
            _db_local.generation = _db_generation

    _db = db
    return db


class PlayEvent(BaseModel):
    path: Optional[str] = None
    artist: Optional[str] = None
    genre: Optional[str] = None
    duration: Optional[int] = None


@router.post("/home/play", status_code=204)
def record_play(event: PlayEvent):
    """Record a play event. Increments scanned.play_count if path matches.

    Server-side dedup: rejects duplicate plays for the same path within 60s.
    """
    db = _get_db()

    # --- Dedup guard: same path within 60 seconds is rejected silently ---
    if event.path:
        last = db._conn.execute(
            "SELECT MAX(played_at) FROM play_events WHERE path = ?",
            (event.path,),
        ).fetchone()
        if last and last[0] and (time.time() - last[0]) < 60:
            return Response(status_code=204)

    genre = event.genre
    # If genre missing but we have a file path, read it from the file
    if not genre and event.path:
        row = db.get(event.path)
        if row and row.get("genre"):
            genre = row["genre"]
        else:
            # Try reading genre from file tags directly
            try:
                from tidal_dl.gui.api.library import _normalize_genre
                from mutagen import File as MutagenFile

                audio = MutagenFile(event.path, easy=True)
                if audio and audio.tags:
                    raw = audio.tags.get("genre")
                    if raw and isinstance(raw, list):
                        genre = _normalize_genre(str(raw[0]))
                    elif raw:
                        genre = _normalize_genre(str(raw))
                    # Update the scanned table so future plays have it
                    if genre:
                        db._conn.execute(
                            "UPDATE scanned SET genre = ? WHERE path = ? AND (genre IS NULL OR genre = '')",
                            (genre, event.path),
                        )
            except Exception:
                pass
    # Fallback: infer genre from the artist's other tracks in the library
    if not genre and event.artist:
        try:
            artist_genre = db._conn.execute(
                """SELECT genre FROM scanned
                   WHERE artist = ? AND genre IS NOT NULL AND genre != ''
                   GROUP BY genre ORDER BY COUNT(*) DESC LIMIT 1""",
                (event.artist,),
            ).fetchone()
            if artist_genre:
                genre = artist_genre[0]
        except Exception:
            pass
    if event.path:
        db.increment_play(event.path)
    db.log_play_event(
        path=event.path,
        artist=event.artist,
        genre=genre,
        duration=event.duration,
    )
    db.commit()
    return Response(status_code=204)


@router.get("/home")
def home_stats():
    """Return aggregated stats for the Home view."""
    db = _get_db()
    stats = db.home_stats()

    # Signal whether the music volume is currently reachable. Cached so a
    # cold NAS stat() call doesn't stall every /home request.
    stats["volume_available"] = _volume_available_cached()

    # Convert cover_path to cover_url for artist tiles
    from urllib.parse import quote

    if stats["top_artist"] and stats["top_artist"].get("cover_path"):
        stats["top_artist"]["cover_url"] = (
            "/api/library/art?path=" + quote(stats["top_artist"]["cover_path"], safe="")
        )
    for a in stats.get("top_artists", []):
        if a.get("cover_path"):
            a["cover_url"] = "/api/library/art?path=" + quote(a["cover_path"], safe="")

    if stats["most_replayed"] and stats["most_replayed"].get("cover_path"):
        stats["most_replayed"]["cover_url"] = (
            "/api/library/art?path=" + quote(stats["most_replayed"]["cover_path"], safe="")
        )

    # Convert recent_albums cover paths
    for a in stats.get("recent_albums", []):
        if a.get("cover_path"):
            a["cover_url"] = "/api/library/art?path=" + quote(a["cover_path"], safe="")

    # Inject cached artist image URLs so frontend doesn't need a second fetch
    def _inject_artist_image(artist_dict):
        if not artist_dict or not artist_dict.get("name"):
            return
        cached = db.get_artist_image(artist_dict["name"])
        if cached:  # truthy = real URL (not empty-string miss)
            artist_dict["artist_image_url"] = cached

    if stats.get("top_artist"):
        _inject_artist_image(stats["top_artist"])
    for a in stats.get("top_artists", []):
        _inject_artist_image(a)

    # Remove internal cover_path from response — only expose cover_url
    if stats.get("top_artist"):
        stats["top_artist"].pop("cover_path", None)
    for a in stats.get("top_artists", []):
        a.pop("cover_path", None)
    if stats.get("most_replayed"):
        stats["most_replayed"].pop("cover_path", None)
    for a in stats.get("recent_albums", []):
        a.pop("cover_path", None)

    # Convert this_week cover paths to URLs
    tw = stats.get("this_week", {})
    if tw.get("top_artist") and tw["top_artist"].get("cover_path"):
        tw["top_artist"]["cover_url"] = (
            "/api/library/art?path=" + quote(tw["top_artist"]["cover_path"], safe="")
        )
    for a in tw.get("top_artists", []):
        if a.get("cover_path"):
            a["cover_url"] = "/api/library/art?path=" + quote(a["cover_path"], safe="")
    if tw.get("most_replayed") and tw["most_replayed"].get("cover_path"):
        tw["most_replayed"]["cover_url"] = (
            "/api/library/art?path=" + quote(tw["most_replayed"]["cover_path"], safe="")
        )
    # Inject cached artist images for this_week too
    if tw.get("top_artist"):
        _inject_artist_image(tw["top_artist"])
    for a in tw.get("top_artists", []):
        _inject_artist_image(a)

    # Strip internal cover_path from this_week
    if tw.get("top_artist"):
        tw["top_artist"].pop("cover_path", None)
    for a in tw.get("top_artists", []):
        a.pop("cover_path", None)
    if tw.get("most_replayed"):
        tw["most_replayed"].pop("cover_path", None)

    return stats


@router.get("/home/artist-image")
def artist_image(name: str = Query(..., description="Artist name")):
    """Return a Tidal artist photo URL, with DB cache."""
    try:
        db = _get_db()
    except Exception:
        return {"image_url": None}

    cached = db.get_artist_image(name)
    if cached is not None:
        # Empty string = cached miss
        return {"image_url": cached or None}

    # Deezer first — no auth, fast, no session overhead
    try:
        import json
        import urllib.parse
        import urllib.request

        deezer_url = (
            "https://api.deezer.com/search/artist?q="
            + urllib.parse.quote(name)
            + "&limit=1"
        )
        resp = urllib.request.urlopen(deezer_url, timeout=3)
        data = json.loads(resp.read())
        if data.get("data"):
            url = data["data"][0].get("picture_xl") or data["data"][0].get("picture_big")
            if url:
                db.set_artist_image(name, url)
                db.commit()
                return {"image_url": url}
    except Exception:
        pass

    # Tidal fallback — only if session is already active (avoid cold-start)
    try:
        from tidalapi.artist import Artist as TidalArtist

        from tidal_dl.gui.api.search import get_tidal_session

        session = get_tidal_session()
        if session.check_login():
            results = session.search(name, models=[TidalArtist], limit=1)
            artists = results.get("artists", [])
            if artists:
                url = artists[0].image(480)
                db.set_artist_image(name, url)
                db.commit()
                return {"image_url": url}
    except Exception:
        pass

    # No image found — cache the miss so we don't retry
    try:
        db.set_artist_image(name, "")
        db.commit()
    except Exception:
        pass
    return {"image_url": None}
