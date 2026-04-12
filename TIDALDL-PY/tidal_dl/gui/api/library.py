"""GET /api/library — local file metadata backed by LibraryDB cache.

The library lives on a NAS (/Volumes/Music), so scanning is slow. Strategy:
- GET /api/library returns whatever is in the DB instantly.
- POST /api/library/scan kicks off a background thread that walks the disk,
  reads tags for new files, prunes deleted ones, and updates the DB.
- The frontend calls scan on first visit (if DB is empty) or on Sync click,
  then polls /api/library to pick up results as they stream in.
"""

from __future__ import annotations

import os
import threading
import time
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


_db: LibraryDB | None = None  # Compatibility alias for tests/debugging.
_db_opened_at: float = 0  # Compatibility alias for tests/debugging.
_DB_MAX_AGE = 300  # Force reconnect every 5 min to catch stale NAS handles
_scan_lock = threading.Lock()
_scan_running = False
_scan_progress = {"scanned": 0, "total": 0, "done": True}
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
    _db_local.opened_at = 0.0
    _db_local.generation = -1


def _invalidate_db_cache() -> None:
    global _db, _db_opened_at, _db_generation
    _close_thread_db()
    _db = None
    _db_opened_at = 0
    with _db_generation_lock:
        _db_generation += 1


def _get_db() -> LibraryDB:
    global _db, _db_opened_at
    now = time.time()
    db_path = Path(path_config_base()) / "library.db"
    db = getattr(_db_local, "db", None)
    opened_at = getattr(_db_local, "opened_at", 0.0)
    generation = getattr(_db_local, "generation", -1)

    if db is not None:
        expired = (now - opened_at) > _DB_MAX_AGE
        stale_generation = generation != _db_generation
        stale_path = db._path != db_path
        if expired or stale_generation or stale_path:
            _close_thread_db()
            db = None

    if db is None:
        db = LibraryDB(db_path)
        db.open()
        _db_local.db = db
        _db_local.opened_at = now
        _db_local.generation = _db_generation
    else:
        # Validate the connection is still alive (NAS mounts can drop)
        try:
            db._conn.execute("SELECT 1")
        except Exception:
            _close_thread_db()
            db = LibraryDB(db_path)
            db.open()
            _db_local.db = db
            _db_local.opened_at = now
            _db_local.generation = _db_generation

    _db = db
    _db_opened_at = getattr(_db_local, "opened_at", now)
    return db


def get_download_path() -> str:
    settings = Settings()
    return settings.data.download_base_path


def _path_in_library(path: str) -> bool:
    """Thread-safe check: is this path in our library DB? Opens its own connection."""
    import sqlite3

    db_path = Path(path_config_base()) / "library.db"
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT 1 FROM scanned WHERE path = ? LIMIT 1", (path,)).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


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

        # ISRC: easy mode doesn't map it for MP4/M4A — fall back to raw tags
        isrc = _tag("isrc")
        if not isrc:
            raw = MutagenFile(file_path)
            if raw and raw.tags:
                # MP4: stored as freeform atom or direct key
                for key in ("isrc", "----:com.apple.iTunes:isrc", "TSRC"):
                    val = raw.tags.get(key)
                    if val:
                        if isinstance(val, list):
                            isrc = str(val[0])
                        else:
                            isrc = str(val)
                        break

        return {
            "path": str(file_path),
            "name": _tag("title", file_path.stem),
            "artist": _tag("artist", "Unknown Artist"),
            "album": _tag("album", "Unknown Album"),
            "duration": round(audio.info.length) if audio.info else 0,
            "isrc": isrc,
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
        "genre": row.get("genre") or "",
        "quality": row.get("quality") or p.suffix[1:].upper(),
        "format": row.get("format") or p.suffix[1:].upper(),
        "cover_url": "/api/library/art?path=" + quote(row["path"], safe=""),
        "play_count": row.get("play_count") or 0,
        "is_local": True,
    }


def _scan_directories() -> list[Path]:
    """Return all directories to scan: download_base_path + scan_paths."""
    settings = Settings()
    dirs: list[Path] = []
    dl = Path(settings.data.download_base_path).expanduser()
    if dl.is_dir():
        dirs.append(dl)
    if settings.data.scan_paths:
        for p in settings.data.scan_paths.split(","):
            p = p.strip()
            if p:
                expanded = Path(p).expanduser()
                if expanded.is_dir() and expanded not in dirs:
                    dirs.append(expanded)
    return dirs


def _migrate_volume_prefixes(db: LibraryDB, scan_dirs: list[Path]) -> None:
    """Rewrite stored path prefixes when a volume remounts under a different name.

    macOS can remount e.g. /Volumes/Music as /Volumes/Music 1.  All paths in
    the DB become stale.  We detect this by sampling stored paths and comparing
    their prefix against the current scan directories.  If they diverge, we
    batch-UPDATE every table that stores file paths.
    """
    assert db._conn
    conn = db._conn

    # Sample a few stored paths to discover what prefix the DB currently holds
    sample_rows = conn.execute(
        "SELECT path FROM scanned LIMIT 10"
    ).fetchall()
    if not sample_rows:
        return  # empty DB, nothing to migrate

    stored_paths = [r["path"] for r in sample_rows]

    for scan_dir in scan_dirs:
        current_prefix = str(scan_dir)
        # Check if any stored path already starts with this scan dir — no migration needed
        if any(p.startswith(current_prefix + os.sep) or p.startswith(current_prefix + "/") for p in stored_paths):
            continue

        # Try to find a stored prefix that looks like a variant of this scan dir.
        # e.g. current = /Volumes/Music, stored = /Volumes/Music 1/Artist/...
        # Strategy: walk up from the scan dir to find the mount point, then look
        # for stored paths sharing the same parent but with a different leaf name.
        scan_parent = str(Path(current_prefix).parent)  # e.g. /Volumes
        scan_leaf = Path(current_prefix).name            # e.g. Music

        # Find stored prefixes that share the same parent directory
        old_prefix = None
        for sp in stored_paths:
            if not sp.startswith(scan_parent + "/"):
                continue
            # Extract the leaf directory name from the stored path
            remainder = sp[len(scan_parent) + 1:]  # e.g. "Music 1/Artist/track.flac"
            stored_leaf = remainder.split("/")[0]    # e.g. "Music 1"
            if stored_leaf != scan_leaf:
                candidate = scan_parent + "/" + stored_leaf
                old_prefix = candidate
                break

        if not old_prefix:
            continue

        # Verify this old prefix is actually prevalent (not just one rogue row)
        count = conn.execute(
            "SELECT COUNT(*) FROM scanned WHERE path LIKE ? || '/%'",
            (old_prefix,),
        ).fetchone()[0]
        if count == 0:
            continue

        new_prefix = current_prefix
        print(f"[library] Volume remount detected: rewriting {count} paths")
        print(f"[library]   old prefix: {old_prefix}")
        print(f"[library]   new prefix: {new_prefix}")

        # Batch rewrite all tables that store file paths
        conn.execute(
            "UPDATE scanned SET path = replace(path, ?, ?) WHERE path LIKE ? || '/%'",
            (old_prefix, new_prefix, old_prefix),
        )
        conn.execute(
            "UPDATE play_events SET path = replace(path, ?, ?) WHERE path LIKE ? || '/%'",
            (old_prefix, new_prefix, old_prefix),
        )
        conn.execute(
            "UPDATE favorites SET path = replace(path, ?, ?) WHERE path IS NOT NULL AND path LIKE ? || '/%'",
            (old_prefix, new_prefix, old_prefix),
        )
        conn.commit()
        print(f"[library] Volume prefix migration complete — {count} paths updated")


def _background_scan(rescan: bool) -> None:
    """Walk all configured dirs, read tags for unknown files, prune deleted ones."""
    global _scan_running, _scan_progress
    try:
        scan_dirs = _scan_directories()

        # Backup DB before scan — single rolling .bak for disaster recovery
        import shutil
        db_path = Path(path_config_base()) / "library.db"
        if db_path.is_file():
            shutil.copy2(str(db_path), str(db_path) + ".bak")

        # Own connection for the background thread — SQLite doesn't share across threads
        db = LibraryDB(Path(path_config_base()) / "library.db")
        db.open()

        # --- Volume remount prefix migration ---
        # macOS sometimes remounts /Volumes/Music as /Volumes/Music 1 (or back).
        # Stored absolute paths become stale, causing full rescans and data loss.
        # Detect and batch-rewrite prefixes before anything else touches the DB.
        if scan_dirs:
            _migrate_volume_prefixes(db, scan_dirs)

        # If no scan directories are reachable, skip scan entirely to preserve
        # the cached library data.  Without this guard the prune logic would
        # delete every row because disk_paths would be empty.
        if not scan_dirs:
            print("[library] No scan directories reachable — skipping scan to preserve cache")
            with _scan_lock:
                _scan_progress = {"scanned": 0, "total": 0, "done": True}
            db.close()
            return

        known = set() if rescan else db.complete_paths()

        # --- Fast-path: skip walk if nothing changed on disk ---
        import json as _json

        try:
            finger = _json.dumps({
                "dirs": sorted(str(d) for d in scan_dirs),
                "mtimes": [os.stat(str(d)).st_mtime for d in sorted(scan_dirs)],
                "known_count": len(known),
            }, sort_keys=True)
        except OSError:
            finger = None

        if not rescan and finger:
            stored = db.get_meta("scan_fingerprint")
            if stored == finger:
                print("[library] Scan directories unchanged — skipping")
                with _scan_lock:
                    _scan_progress = {"scanned": 0, "total": 0, "done": True}
                db.close()
                return

        with _scan_lock:
            _scan_progress = {"scanned": 0, "total": 0, "done": False}
        disk_paths: set[str] = set()
        batch = 0

        if scan_dirs:
            # Phase 1: Walk filesystem — fast, just collect paths
            for scan_dir in scan_dirs:
                for f in scan_dir.rglob("*"):
                    if f.suffix.lower() not in _AUDIO_EXTENSIONS:
                        continue
                    disk_paths.add(str(f))
                    _scan_progress["total"] = len(disk_paths)

            # Phase 2: Read metadata + waveform only for NEW files (the diff)
            from tidal_dl.helper.waveform import extract_both, peaks_to_json

            new_paths = disk_paths - known
            _scan_progress["scanned"] = 0
            for path_str in new_paths:
                meta = _read_metadata(Path(path_str))
                if meta:
                    # Extract waveform peaks (single ffmpeg decode, ~30ms per file)
                    waveform_json = None
                    hires_json = None
                    both = extract_both(path_str)
                    if both:
                        waveform_json = peaks_to_json(both[0])
                        hires_json = peaks_to_json(both[1])

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
                        waveform=waveform_json,
                        waveform_hires=hires_json,
                    )
                else:
                    db.record(path_str, status="unreadable")
                batch += 1
                if batch >= 50:
                    db.commit()
                    batch = 0
                _scan_progress["scanned"] += 1

            # Prune deleted files — with safety threshold for volume remounts
            stale = known - disk_paths
            if len(stale) > 0.5 * len(known) and len(known) > 100:
                print(
                    f"[library] Skipping prune: {len(stale)}/{len(known)} paths would be removed"
                    " — possible volume remount"
                )
            else:
                for p in stale:
                    db.remove(p)

            if batch > 0 or stale:
                db.commit()

        with _scan_lock:
            _scan_progress["done"] = True

        # Save scan fingerprint so next scan can skip if nothing changed
        if finger:
            # Recompute with final known_count (scan may have added/removed rows)
            try:
                final_known = len(db.complete_paths()) if not rescan else len(disk_paths)
                finger = _json.dumps({
                    "dirs": sorted(str(d) for d in scan_dirs),
                    "mtimes": [os.stat(str(d)).st_mtime for d in sorted(scan_dirs)],
                    "known_count": final_known,
                }, sort_keys=True)
                db.set_meta("scan_fingerprint", finger)
                db.commit()
            except OSError:
                pass

        # Backfill genres for tracks scanned before genre support was added.
        # Runs AFTER scan is marked done so the UI doesn't show a stuck spinner.
        # Limit to 200 files per scan to avoid long NAS hangs.
        missing = db._conn.execute(
            "SELECT path FROM scanned WHERE (genre IS NULL OR genre = '') AND status != 'unreadable' LIMIT 200"
        ).fetchall()
        if missing:
            gfilled = 0
            for row in missing:
                p = Path(row[0])
                try:
                    if not p.exists():
                        continue
                    audio = MutagenFile(str(p), easy=True)
                    if audio and audio.tags:
                        raw = audio.tags.get("genre")
                        if raw and isinstance(raw, list):
                            genre = _normalize_genre(str(raw[0]))
                        elif raw:
                            genre = _normalize_genre(str(raw))
                        else:
                            genre = None
                        if genre:
                            db._conn.execute(
                                "UPDATE scanned SET genre = ? WHERE path = ?",
                                (genre, row[0]),
                            )
                            gfilled += 1
                except Exception:
                    pass
            if gfilled:
                db.commit()
        db.close()

        # Flag invalidation — request threads reopen on next access
        _invalidate_db_cache()
    finally:
        with _scan_lock:
            _scan_running = False


@router.get("/library/artists")
def library_artists(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query("", description="Search filter"),
) -> dict:
    """Return paginated artists with track/album counts."""
    from urllib.parse import quote

    db = _get_db()
    rows, total = db.artists_page(limit=limit, offset=offset, query=q.strip())
    artists = [
        {
            "name": r["artist"],
            "track_count": r["track_count"],
            "album_count": r["album_count"],
            "cover_url": "/api/library/art?path=" + quote(r["cover_path"], safe="") if r.get("cover_path") else "",
        }
        for r in rows
    ]
    return {"artists": artists, "total": total}


@router.get("/library/albums")
def all_albums(q: str = Query("", description="Search filter")):
    """Return all albums in the local library as a gallery."""
    from urllib.parse import quote

    db = _get_db()
    albums = db.all_albums(query=q)
    return {
        "albums": [
            {
                "name": a["album"],
                "artist": a["artist"],
                "track_count": a["track_count"],
                "cover_url": "/api/library/art?path=" + quote(a["cover_path"], safe=""),
                "best_quality": a.get("best_quality") or "",
            }
            for a in albums
        ],
        "total": len(albums),
    }


@router.get("/library/recent-albums")
def library_recent_albums(
    limit: int = Query(12, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> dict:
    from urllib.parse import quote

    db = _get_db()
    rows, total = db.recent_albums_page(limit=limit, offset=offset)
    albums = [
        {
            "name": row["album"],
            "artist": row["artist"],
            "track_count": row["track_count"],
            "cover_url": "/api/library/art?path=" + quote(row["cover_path"], safe="") if row.get("cover_path") else "",
            "recent_at": row["recent_at"],
            "recent_source": row["recent_source"],
        }
        for row in rows
    ]
    return {"albums": albums, "total": total, "limit": limit, "offset": offset}


@router.get("/library/artist/{artist_name}/albums")
def artist_albums(artist_name: str):
    """Return all albums by an artist from the local library."""
    from urllib.parse import quote

    db = _get_db()
    albums = db.albums_by_artist(artist_name)
    return {
        "artist": artist_name,
        "albums": [
            {
                "name": a["album"],
                "track_count": a["track_count"],
                "cover_url": "/api/library/art?path=" + quote(a["cover_path"], safe=""),
                "genres": a.get("genres") or "",
                "best_quality": a.get("best_quality") or "",
            }
            for a in albums
        ],
        "total": len(albums),
    }


@router.get("/library/artist/{artist_name}/album/{album_name}/tracks")
def artist_album_tracks(artist_name: str, album_name: str):
    """Return all tracks for a specific album by an artist."""
    db = _get_db()
    tracks = db.album_tracks(artist_name, album_name)
    return {
        "artist": artist_name,
        "album": album_name,
        "tracks": [_db_row_to_track(t) for t in tracks],
        "total": len(tracks),
    }


def _art_cache_dir() -> Path:
    """Return (and create) the art cache directory."""
    d = Path(path_config_base()) / "art_cache"
    d.mkdir(exist_ok=True)
    return d


def _art_cache_key(path: str) -> str:
    """Stable cache filename from audio path."""
    import hashlib
    return hashlib.md5(path.encode()).hexdigest() + ".jpg"


@router.get("/library/art")
def library_art(path: str = Query(..., description="Absolute path to audio file")):
    """Extract and serve embedded album art from a local audio file. Disk-cached."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, Response

    from tidal_dl.gui.security import validate_audio_path

    # Check disk cache first — instant response
    cache_dir = _art_cache_dir()
    cache_file = cache_dir / _art_cache_key(path)
    if cache_file.is_file():
        return FileResponse(
            cache_file, media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    settings = Settings()
    allowed = [str(Path(settings.data.download_base_path).expanduser())]
    if settings.data.scan_paths:
        allowed.extend(str(Path(p.strip()).expanduser()) for p in settings.data.scan_paths.split(",") if p.strip())

    validated = validate_audio_path(path, allowed)
    # Fallback: if path is in our library DB, we already trusted it during scan
    if validated is None and _path_in_library(path):
        try:
            validated = Path(path).resolve(strict=True)
        except (OSError, ValueError):
            validated = None
    if validated is None:
        raise HTTPException(status_code=403, detail="Access denied")

    art_data = None
    art_mime = "image/jpeg"

    try:
        audio = MutagenFile(str(validated))
        if audio is None:
            raise HTTPException(status_code=404, detail="Not a recognized audio file")

        # FLAC
        if hasattr(audio, "pictures") and audio.pictures:
            pic = audio.pictures[0]
            art_data = pic.data
            art_mime = pic.mime or "image/jpeg"

        # MP3 / ID3
        if not art_data:
            tags = audio.tags or {}
            for key in tags:
                if key.startswith("APIC"):
                    apic = tags[key]
                    art_data = apic.data
                    art_mime = apic.mime or "image/jpeg"
                    break

        # M4A / MP4
        if not art_data:
            tags = audio.tags or {}
            if "covr" in tags and tags["covr"]:
                art_data = bytes(tags["covr"][0])

    except HTTPException:
        raise
    except Exception:
        pass

    # Write to disk cache and return
    if art_data:
        cache_file.write_bytes(art_data)
        return Response(
            content=art_data, media_type=art_mime,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Fallback: look for cover image in the same directory as the audio file
    cover_names = ["cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "front.png", "album.jpg", "album.png"]
    parent = validated.parent
    for name in cover_names:
        img_path = parent / name
        if img_path.is_file():
            # Cache the folder art too
            import shutil
            shutil.copy2(str(img_path), str(cache_file))
            mime = "image/png" if name.endswith(".png") else "image/jpeg"
            return FileResponse(
                img_path, media_type=mime,
                headers={"Cache-Control": "public, max-age=86400"},
            )

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


@router.get("/library/search")
def library_search(
    q: str = Query(..., min_length=1, description="Search query"),
    type: str = Query("tracks", description="Search type: tracks, albums, artists"),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """Search the local library by title, artist, or album."""
    db = _get_db()

    if type == "tracks":
        rows, total = db.tracks_page(sort="artist", limit=limit, offset=0, query=q.strip())
        return {"tracks": [_db_row_to_track(r) for r in rows], "total": total}

    if type == "albums":
        albums = db.all_albums(query=q.strip())
        from urllib.parse import quote
        return {
            "albums": [
                {
                    "name": a["album"],
                    "artist": a["artist"],
                    "track_count": a["track_count"],
                    "cover_url": "/api/library/art?path=" + quote(a["cover_path"], safe=""),
                    "is_local": True,
                }
                for a in albums[:limit]
            ],
            "total": len(albums),
        }

    if type == "artists":
        assert db._conn
        like = f"%{q.strip()}%"
        rows = db._conn.execute(
            """SELECT artist, COUNT(*) as track_count, COUNT(DISTINCT album) as album_count,
                      MIN(path) as cover_path
               FROM scanned
               WHERE artist LIKE ? AND status != 'unreadable'
               GROUP BY artist ORDER BY track_count DESC LIMIT ?""",
            (like, limit),
        ).fetchall()
        from urllib.parse import quote
        return {
            "artists": [
                {
                    "name": r["artist"],
                    "track_count": r["track_count"],
                    "album_count": r["album_count"],
                    "cover_url": "/api/library/art?path=" + quote(r["cover_path"], safe=""),
                    "is_local": True,
                }
                for r in rows
            ],
            "total": len(rows),
        }

    return {"error": "Unknown type", "total": 0}


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
    with _scan_lock:
        return {"scanning": _scan_running, **_scan_progress}


from pydantic import BaseModel


class FavoriteToggleRequest(BaseModel):
    path: str | None = None
    tidal_id: int | None = None
    artist: str | None = None
    title: str | None = None
    album: str | None = None
    isrc: str | None = None
    cover_url: str | None = None


@router.get("/library/favorites")
def get_favorites():
    """Return all favorited tracks."""
    from urllib.parse import quote

    db = _get_db()
    favs = db.all_favorites()
    total_duration = 0
    result = []
    for f in favs:
        quality = f.get("scanned_quality") or ""
        duration = f.get("scanned_duration") or 0
        if duration:
            total_duration += duration
        entry = {
            "id": f["id"],
            "path": f.get("path"),
            "tidal_id": f.get("tidal_id"),
            "artist": f.get("artist") or "Unknown Artist",
            "name": f.get("title") or "Unknown",
            "album": f.get("album") or "",
            "isrc": f.get("isrc") or "",
            "cover_url": f.get("cover_url") or "",
            "quality": quality,
            "duration": duration,
            "favorited_at": f["favorited_at"],
            "is_local": f.get("path") is not None,
        }
        if entry["path"]:
            entry["cover_url"] = "/api/library/art?path=" + quote(entry["path"], safe="")
        result.append(entry)
    return {"favorites": result, "total": len(result), "total_duration": total_duration}


@router.get("/library/favorites/check")
def check_favorites(
    paths: str = Query("", description="Comma-separated paths"),
    tidal_ids: str = Query("", description="Comma-separated tidal IDs"),
):
    """Bulk check which items are favorited."""
    db = _get_db()
    fav_paths = db.favorite_paths()
    fav_tids = db.favorite_tidal_ids()

    result = {}
    if paths:
        for p in paths.split(","):
            p = p.strip()
            if p:
                result[p] = p in fav_paths
    if tidal_ids:
        for tid in tidal_ids.split(","):
            tid = tid.strip()
            if tid:
                result["tidal:" + tid] = int(tid) in fav_tids
    return {"favorites": result}


@router.post("/library/favorites/toggle")
def toggle_favorite(req: FavoriteToggleRequest):
    """Toggle favorite status. Returns new state."""
    db = _get_db()
    is_fav = db.is_favorite(path=req.path, tidal_id=req.tidal_id)

    if is_fav:
        db.remove_favorite(path=req.path, tidal_id=req.tidal_id)
    else:
        db.add_favorite(
            path=req.path,
            tidal_id=req.tidal_id,
            artist=req.artist,
            title=req.title,
            album=req.album,
            isrc=req.isrc,
            cover_url=req.cover_url,
        )
    db.commit()

    return {"favorited": not is_fav}
