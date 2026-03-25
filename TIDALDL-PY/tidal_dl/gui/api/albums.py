"""Album detail endpoint — tracks for a given album."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from tidal_dl.config import Tidal
from tidal_dl.gui.api.search import _get_isrc_index, _serialize_track
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

router = APIRouter()


def _get_library_db() -> LibraryDB:
    """Open a read-only handle to the library DB for local-match queries."""
    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    return db


def _normalize(s: str) -> str:
    """Lowercase, strip whitespace for fuzzy comparison."""
    return s.strip().lower()


@router.get("/albums/{album_id}/tracks")
def album_tracks(album_id: int) -> dict:
    """Get tracks for a specific album with local-match flags."""
    tidal = Tidal()
    session = tidal.session
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    try:
        album = session.album(album_id)
        tracks = album.tracks() or []
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Album not found: {exc}") from exc

    isrc_index = _get_isrc_index()

    cover_url = ""
    try:
        cover_url = album.image(320)
    except Exception:
        pass

    return {
        "album": {
            "id": album.id,
            "name": getattr(album, "name", ""),
            "artist": getattr(album, "artist", None) and album.artist.name or "",
            "cover_url": cover_url,
            "num_tracks": getattr(album, "num_tracks", 0),
        },
        "tracks": [_serialize_track(t, isrc_index) for t in tracks],
        "total": len(tracks),
    }


@router.get("/albums/lookup")
def album_lookup(
    artist: str = Query(..., min_length=1),
    album: str = Query(..., min_length=1),
) -> dict:
    """Search Tidal for a matching album and return its full track listing.

    Each track is annotated with ``is_local`` — True when the track already
    exists in the user's scanned library (matched by ISRC first, then by
    normalised title + artist).
    """
    from tidalapi.album import Album as TidalAlbum

    session = Tidal().session
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    # --- 1. Search Tidal for the album ---
    query = f"{artist} {album}"
    try:
        results = session.search(query, models=[TidalAlbum], limit=20)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Tidal search failed: {exc}") from exc

    albums = results.get("albums", []) or []
    if not albums:
        raise HTTPException(status_code=404, detail="No matching album found on Tidal")

    # --- 2. Fuzzy-match best album ---
    target_album = _normalize(album)
    target_artist = _normalize(artist)

    def _score(a) -> float:
        """Lower is better. Exact match = 0."""
        a_name = _normalize(getattr(a, "name", ""))
        a_artist = _normalize(
            getattr(a.artist, "name", "") if getattr(a, "artist", None) else ""
        )
        # Simple containment / equality scoring
        score = 0.0
        if a_name == target_album:
            score += 0.0
        elif target_album in a_name or a_name in target_album:
            score += 0.3
        else:
            score += 1.0
        if a_artist == target_artist:
            score += 0.0
        elif target_artist in a_artist or a_artist in target_artist:
            score += 0.3
        else:
            score += 1.0
        return score

    albums.sort(key=_score)
    best = albums[0]

    # --- 3. Fetch full track list ---
    try:
        tidal_tracks = best.tracks() or []
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to fetch album tracks: {exc}"
        ) from exc

    # --- 4. Build local-match sets (ISRC + title/artist) ---
    isrc_index = _get_isrc_index()

    # Also query the scanned table for title+artist matches
    local_titles: set[tuple[str, str]] = set()
    try:
        db = _get_library_db()
        conn = db._conn
        rows = conn.execute(
            "SELECT title, artist FROM scanned WHERE status != 'unreadable'"
        ).fetchall()
        for r in rows:
            t = _normalize(r["title"] or "")
            a = _normalize(r["artist"] or "")
            if t:
                local_titles.add((t, a))
        db.close()
    except Exception:
        pass  # If DB is unavailable, fall back to ISRC-only matching

    # --- 5. Serialize with is_local annotation ---
    serialized = []
    missing_count = 0
    for t in tidal_tracks:
        data = _serialize_track(t, isrc_index)
        # Enhance is_local with title+artist fallback
        if not data["is_local"]:
            t_title = _normalize(data.get("name", ""))
            t_artist = _normalize(data.get("artist", ""))
            if t_title and (t_title, t_artist) in local_titles:
                data["is_local"] = True
        if not data["is_local"]:
            missing_count += 1
        serialized.append(data)

    cover_url = ""
    try:
        cover_url = best.image(320)
    except Exception:
        pass

    return {
        "album": {
            "id": best.id,
            "name": getattr(best, "name", ""),
            "artist": getattr(best, "artist", None) and best.artist.name or "",
            "cover_url": cover_url,
            "num_tracks": getattr(best, "num_tracks", 0),
        },
        "tracks": serialized,
        "missing_count": missing_count,
    }
