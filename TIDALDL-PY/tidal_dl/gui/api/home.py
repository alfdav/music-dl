"""Home view API — play tracking and stats aggregation."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

router = APIRouter()

_db: LibraryDB | None = None


def _get_db() -> LibraryDB:
    global _db
    if _db is None:
        _db = LibraryDB(Path(path_config_base()) / "library.db")
        _db.open()
    else:
        try:
            _db._conn.execute("SELECT 1")
        except Exception:
            _db = LibraryDB(Path(path_config_base()) / "library.db")
            _db.open()
    return _db


class PlayEvent(BaseModel):
    path: Optional[str] = None
    artist: Optional[str] = None
    genre: Optional[str] = None
    duration: Optional[int] = None


@router.post("/home/play", status_code=204)
def record_play(event: PlayEvent):
    """Record a play event. Increments scanned.play_count if path matches."""
    db = _get_db()
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

    # Signal whether the music volume is currently reachable
    from tidal_dl.gui.api.library import _scan_directories
    stats["volume_available"] = len(_scan_directories()) > 0

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

    # Remove internal cover_path from response — only expose cover_url
    if stats.get("top_artist"):
        stats["top_artist"].pop("cover_path", None)
    for a in stats.get("top_artists", []):
        a.pop("cover_path", None)
    if stats.get("most_replayed"):
        stats["most_replayed"].pop("cover_path", None)

    return stats


@router.get("/home/artist-image")
def artist_image(name: str = Query(..., description="Artist name")):
    """Return a Tidal artist photo URL, with DB cache."""
    db = _get_db()
    cached = db.get_artist_image(name)
    if cached is not None:
        # Empty string = cached miss
        return {"image_url": cached or None}

    # Look up on Tidal
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

    # Fallback: try Deezer (no auth required)
    try:
        import json
        import urllib.parse
        import urllib.request

        deezer_url = (
            "https://api.deezer.com/search/artist?q="
            + urllib.parse.quote(name)
            + "&limit=1"
        )
        resp = urllib.request.urlopen(deezer_url, timeout=5)
        data = json.loads(resp.read())
        if data.get("data"):
            url = data["data"][0].get("picture_xl") or data["data"][0].get("picture_big")
            if url:
                db.set_artist_image(name, url)
                db.commit()
                return {"image_url": url}
    except Exception:
        pass

    # No image found — cache the miss so we don't retry
    db.set_artist_image(name, "")
    db.commit()
    return {"image_url": None}
