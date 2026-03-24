"""Home view API — play tracking and stats aggregation."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter
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
    if event.path:
        db.increment_play(event.path)
    db.log_play_event(
        path=event.path,
        artist=event.artist,
        genre=event.genre,
        duration=event.duration,
    )
    db.commit()
    return Response(status_code=204)


@router.get("/home")
def home_stats():
    """Return aggregated stats for the Home view."""
    db = _get_db()
    stats = db.home_stats()

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
