"""Album detail endpoint — tracks for a given album."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from tidal_dl.config import Tidal
from tidal_dl.gui.api.search import _get_isrc_index, _serialize_track

router = APIRouter()


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
