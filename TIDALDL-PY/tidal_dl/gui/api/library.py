"""GET /api/library — local file metadata backed by LibraryDB cache.

The library lives on a NAS (/Volumes/Music), so scanning is slow. Strategy:
- GET /api/library returns whatever is in the DB instantly.
- POST /api/library/scan kicks off a background thread that walks the disk,
  reads tags for new files, prunes deleted ones, and updates the DB.
- The frontend calls scan on first visit (if DB is empty) or on Sync click,
  then polls /api/library to pick up results as they stream in.
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, Query
from mutagen import File as MutagenFile

from tidal_dl.config import Settings
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

router = APIRouter()

_AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}

_GENRE_MAP = {
    "electronica/dance": "Electronic",
    "electronica": "Electronic",
    "electronic/dance": "Electronic",
    "hip-hop/rap": "Hip-Hop",
    "hip hop": "Hip-Hop",
    "r&b/soul": "R&B",
    "alternative rock": "Alt Rock",
    "alt-rock": "Alt Rock",
    "indie rock": "Alt Rock",
}


def _normalize_genre(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    g = raw.strip()
    return _GENRE_MAP.get(g.lower(), g)


_db: LibraryDB | None = None
_scan_lock = threading.Lock()
_scan_running = False
_scan_progress = {"scanned": 0, "total": 0, "done": True}


def _get_db() -> LibraryDB:
    global _db
    if _db is None:
        _db = LibraryDB(Path(path_config_base()) / "library.db")
        _db.open()
    else:
        # Validate the connection is still alive (NAS mounts can drop)
        try:
            _db._conn.execute("SELECT 1")
        except Exception:
            _db = LibraryDB(Path(path_config_base()) / "library.db")
            _db.open()
    return _db


def get_download_path() -> str:
    settings = Settings()
    return settings.data.download_base_path


def _read_metadata(file_path: Path) -> dict | None:
    try:
        # easy=True gives uniform tag keys across ID3, MP4, Vorbis, etc.
        audio = MutagenFile(file_path, easy=True)
        if audio is None:
            return None

        def _tag(key: str, fallback: str = "") -> str:
            val = audio.get(key)
            if val and isinstance(val, list):
                return str(val[0])
            return str(val) if val else fallback

        # Need raw audio for info (bitrate, sample rate) — easy mode still has .info
        quality = file_path.suffix[1:].upper()
        if audio.info and hasattr(audio.info, "bits_per_sample"):
            quality = f"{audio.info.sample_rate}Hz/{audio.info.bits_per_sample}bit"

        return {
            "path": str(file_path),
            "name": _tag("title", file_path.stem),
            "artist": _tag("artist", "Unknown Artist"),
            "album": _tag("album", "Unknown Album"),
            "duration": int(audio.info.length) if audio.info else 0,
            "isrc": _tag("isrc"),
            "genre": _normalize_genre(_tag("genre")),
            "quality": quality,
            "format": file_path.suffix[1:].upper(),
            "is_local": True,
        }
    except Exception:
        return None


def _db_row_to_track(row: dict) -> dict:
    p = Path(row["path"])
    from urllib.parse import quote
    return {
        "path": row["path"],
        "name": row.get("title") or p.stem,
        "artist": row.get("artist") or "Unknown Artist",
        "album": row.get("album") or "Unknown Album",
        "duration": row.get("duration") or 0,
        "isrc": row.get("isrc") or "",
        "quality": row.get("quality") or p.suffix[1:].upper(),
        "format": row.get("format") or p.suffix[1:].upper(),
        "cover_url": "/api/library/art?path=" + quote(row["path"], safe=""),
        "is_local": True,
    }


def _background_scan(rescan: bool) -> None:
    """Walk the download dir, read tags for unknown files, prune deleted ones."""
    global _scan_running, _scan_progress
    try:
        download_path = Path(get_download_path()).expanduser()
        if not download_path.is_dir():
            return

        # Own connection for the background thread — SQLite doesn't share across threads
        db = LibraryDB(Path(path_config_base()) / "library.db")
        db.open()
        known = set() if rescan else db.complete_paths()

        _scan_progress = {"scanned": 0, "total": 0, "done": False}
        disk_paths: set[str] = set()
        batch = 0

        for f in download_path.rglob("*"):
            if f.suffix.lower() not in _AUDIO_EXTENSIONS:
                continue
            path_str = str(f)
            disk_paths.add(path_str)

            if path_str not in known:
                meta = _read_metadata(f)
                if meta:
                    db.record(
                        path_str,
                        status="tagged" if meta["isrc"] else "needs_isrc",
                        isrc=meta["isrc"] or None,
                        artist=meta["artist"],
                        title=meta["name"],
                        album=meta["album"],
                        duration=meta["duration"],
                        genre=meta.get("genre"),
                        quality=meta["quality"],
                        fmt=meta["format"],
                    )
                else:
                    db.record(path_str, status="unreadable")
                batch += 1
                if batch >= 50:
                    db.commit()
                    batch = 0

            _scan_progress["scanned"] = len(disk_paths)

        # Prune deleted files
        stale = known - disk_paths
        for p in stale:
            db.remove(p)

        if batch > 0 or stale:
            db.commit()

        _scan_progress["total"] = len(disk_paths)
        _scan_progress["done"] = True
        db.close()

        # Flag invalidation — main thread reopens on next request
        global _db
        _db = None
    finally:
        with _scan_lock:
            _scan_running = False


@router.get("/library/art")
def library_art(path: str = Query(..., description="Absolute path to audio file")):
    """Extract and serve embedded album art from a local audio file."""
    from fastapi import HTTPException
    from fastapi.responses import Response

    from tidal_dl.gui.security import validate_audio_path

    settings = Settings()
    allowed = [settings.data.download_base_path]
    if settings.data.scan_paths:
        allowed.extend(p.strip() for p in settings.data.scan_paths.split(",") if p.strip())

    validated = validate_audio_path(path, allowed)
    if validated is None:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        audio = MutagenFile(str(validated))
        if audio is None:
            raise HTTPException(status_code=404, detail="Not a recognized audio file")

        # FLAC
        if hasattr(audio, "pictures") and audio.pictures:
            pic = audio.pictures[0]
            return Response(content=pic.data, media_type=pic.mime or "image/jpeg")

        # MP3 / ID3
        tags = audio.tags or {}
        for key in tags:
            if key.startswith("APIC"):
                apic = tags[key]
                return Response(content=apic.data, media_type=apic.mime or "image/jpeg")

        # M4A / MP4
        if "covr" in tags:
            covr = tags["covr"]
            if covr:
                return Response(content=bytes(covr[0]), media_type="image/jpeg")

    except HTTPException:
        raise
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="No embedded art found")


@router.get("/library")
def library(
    sort: str = Query("recent", description="Sort: recent, artist, album, title"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query("", description="Search query (matches title, artist, album)"),
) -> dict:
    """Return a page of cached library from DB. Instant, no disk I/O."""
    db = _get_db()
    rows, total = db.tracks_page(sort=sort, limit=limit, offset=offset, query=q.strip())
    tracks = [_db_row_to_track(row) for row in rows]
    return {"tracks": tracks, "total": total, "scanning": _scan_running}


@router.post("/library/scan")
def scan_library(
    rescan: bool = Query(False, description="Re-read all files, ignoring cache"),
) -> dict:
    """Kick off a background scan. Returns immediately."""
    global _scan_running, _scan_progress
    with _scan_lock:
        if _scan_running:
            return {"status": "already_running", **_scan_progress}
        _scan_running = True
        _scan_progress = {"scanned": 0, "total": 0, "done": False}

    thread = threading.Thread(target=_background_scan, args=(rescan,), daemon=True)
    thread.start()
    return {"status": "started"}


@router.get("/library/scan/status")
def scan_status() -> dict:
    """Check background scan progress."""
    return {"scanning": _scan_running, **_scan_progress}
