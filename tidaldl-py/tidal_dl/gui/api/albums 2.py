"""Album detail endpoint — tracks for a given album."""

from __future__ import annotations

import re
import unicodedata
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
    """Accent-insensitive, token-friendly normalization for fuzzy comparison."""
    if not s:
        return ""
    folded = unicodedata.normalize("NFKD", s)
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^\w]+", " ", stripped.casefold())
    return " ".join(cleaned.split())



def _token_set(s: str) -> set[str]:
    return set(_normalize(s).split())



def _token_overlap(a: str, b: str) -> float:
    left = _token_set(a)
    right = _token_set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))



def _album_metadata_score(candidate_album: str, candidate_artist: str, target_album: str, target_artist: str) -> float:
    score = 0.0

    cand_album = _normalize(candidate_album)
    cand_artist = _normalize(candidate_artist)
    want_album = _normalize(target_album)
    want_artist = _normalize(target_artist)

    if cand_album and want_album:
        if cand_album == want_album:
            score += 6.0
        elif want_album in cand_album or cand_album in want_album:
            score += 3.0
        else:
            score += 3.0 * _token_overlap(cand_album, want_album)

    if cand_artist and want_artist:
        if cand_artist == want_artist:
            score += 4.0
        elif want_artist in cand_artist or cand_artist in want_artist:
            score += 2.0
        else:
            score += 2.0 * _token_overlap(cand_artist, want_artist)

    return score



def _local_album_rows(artist: str, album: str) -> list[dict]:
    try:
        db = _get_library_db()
        try:
            return db.album_tracks(artist, album)
        finally:
            db.close()
    except Exception:
        return []



def _track_title_variants(track: object) -> set[str]:
    variants = {
        _normalize(getattr(track, "name", "")),
        _normalize(getattr(track, "full_name", "")),
    }
    return {value for value in variants if value}



def _track_artist(track: object) -> str:
    artists = getattr(track, "artists", None) or []
    names = [getattr(artist, "name", "") for artist in artists if getattr(artist, "name", "")]
    return _normalize(", ".join(names))



def _track_match_keys(track: object) -> set[tuple[str, str]]:
    artist = _track_artist(track)
    if not artist:
        return set()
    return {(title, artist) for title in _track_title_variants(track) if title}


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

    # --- 2. Rank candidates by metadata, then verify with local track overlap ---
    local_rows = _local_album_rows(artist, album)
    local_track_keys = {
        (
            title,
            artist_name,
        )
        for row in local_rows
        for title in [_normalize(row.get("title") or "")]
        for artist_name in [_normalize(row.get("artist") or "")]
        if title and artist_name
    }
    local_titles = {
        (
            _normalize(row.get("title") or ""),
            _normalize(row.get("artist") or ""),
            _normalize(row.get("album") or ""),
        )
        for row in local_rows
        if _normalize(row.get("title") or "")
    }

    ranked = sorted(
        albums,
        key=lambda a: _album_metadata_score(
            getattr(a, "name", ""),
            getattr(getattr(a, "artist", None), "name", ""),
            album,
            artist,
        ),
        reverse=True,
    )

    best = None
    best_tracks = None
    best_score = float("-inf")
    best_overlap = 0

    for candidate in ranked[:5]:
        try:
            candidate_tracks = candidate.tracks() or []
        except Exception:
            continue

        metadata_score = _album_metadata_score(
            getattr(candidate, "name", ""),
            getattr(getattr(candidate, "artist", None), "name", ""),
            album,
            artist,
        )
        candidate_keys = {
            key
            for track in candidate_tracks
            for key in _track_match_keys(track)
        }
        overlap = len(candidate_keys & local_track_keys) if local_track_keys else 0
        overlap_score = (overlap / max(len(local_track_keys), 1)) * 8.0 if local_track_keys else 0.0
        total_score = metadata_score + overlap_score

        if local_track_keys and overlap == 0:
            total_score -= 100.0

        if total_score > best_score:
            best = candidate
            best_tracks = candidate_tracks
            best_score = total_score
            best_overlap = overlap

    if best is None or best_tracks is None:
        raise HTTPException(status_code=404, detail="No matching album found on Tidal")

    if local_track_keys and best_overlap == 0:
        raise HTTPException(status_code=404, detail="No confident album match found on Tidal")

    if not local_track_keys and best_score < 4.5:
        raise HTTPException(status_code=404, detail="No confident album match found on Tidal")

    tidal_tracks = best_tracks

    # --- 3. Build local-match sets (ISRC + title/artist) ---
    isrc_index = _get_isrc_index()

    # --- 5. Serialize with is_local annotation (album-scoped only) ---
    serialized = []
    missing_count = 0
    for t in tidal_tracks:
        data = _serialize_track(t, isrc_index)
        # Override ISRC-based is_local — ISRC is global and causes false positives
        # across albums (same track on different albums shares an ISRC).
        # Only trust album-scoped triple match: (title, artist, album).
        data["is_local"] = False
        t_title = _normalize(data.get("name", ""))
        t_artist = _normalize(data.get("artist", ""))
        t_album = _normalize(data.get("album", ""))
        if t_title and (t_title, t_artist, t_album) in local_titles:
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
