"""Download management — trigger downloads, SSE progress, history."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class DownloadRequest(BaseModel):
    track_ids: list[int] = []


class DownloadEntry:
    def __init__(self, track_id: int, name: str) -> None:
        self.track_id = track_id
        self.name = name
        self.artist: str = ""
        self.album: str = ""
        self.cover_url: str = ""
        self.quality: str = ""
        self.progress: float = 0.0
        self.status: str = "queued"
        self.started_at: float = time.time()
        self.finished_at: float | None = None


# In-memory state (guarded by _lock for thread-safety between bg download thread and request handlers)
_lock = threading.Lock()
_active: dict[int, DownloadEntry] = {}
_sse_clients: list[asyncio.Queue] = []
_MAX_SSE_CLIENTS = 5


def _broadcast(event: dict) -> None:
    """Send event to all connected SSE clients."""
    for q in _sse_clients[:]:
        try:
            q.put_nowait(event)
        except Exception:
            pass


def _scan_new_downloads(db, settings) -> None:
    """Quick scan of download dir for files not yet in library DB."""
    from pathlib import Path

    from tidal_dl.gui.api.library import _AUDIO_EXTENSIONS, _read_metadata

    dl_path = Path(settings.data.download_base_path).expanduser()
    if not dl_path.is_dir():
        return

    known = db.known_paths()
    batch = 0
    for f in dl_path.rglob("*"):
        if f.suffix.lower() not in _AUDIO_EXTENSIONS:
            continue
        path_str = str(f)
        if path_str in known:
            continue
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

    if batch > 0:
        db.commit()

    # Invalidate main thread's DB connection so it picks up new data
    import tidal_dl.gui.api.library as lib_mod
    lib_mod._db = None


def trigger_download(track_ids: list[int]) -> dict:
    """Trigger downloads using the existing Download pipeline in a background thread."""

    with _lock:
        for tid in track_ids:
            _active[tid] = DownloadEntry(tid, f"Track {tid}")

    # Broadcast queued state for all tracks so the UI shows the full queue
    for tid in track_ids:
        _broadcast({"type": "progress", "track_id": tid, "name": f"Track {tid}", "artist": "", "album": "", "cover_url": "", "quality": "", "status": "queued", "progress": 0})

    def _run() -> None:
        import logging
        from pathlib import Path

        from tidal_dl.config import Settings, Tidal
        from tidal_dl.download import Download
        from tidal_dl.helper.library_db import LibraryDB
        from tidal_dl.helper.path import path_config_base

        tidal = Tidal()
        settings = Settings()
        logger = logging.getLogger("music-dl.gui")
        dl = Download(
            tidal_obj=tidal,
            path_base=settings.data.download_base_path,
            fn_logger=logger,
            skip_existing=settings.data.skip_existing,
        )

        # Own DB connection for this thread
        db = LibraryDB(Path(path_config_base()) / "library.db")
        db.open()

        for tid in track_ids:
            track = None
            try:
                track = tidal.session.track(tid)
            except Exception:
                pass

            with _lock:
                entry = _active.get(tid)
            if entry:
                if track:
                    entry.name = track.full_name or track.name or entry.name
                    if track.artists:
                        entry.artist = ", ".join(a.name for a in track.artists if a.name)
                    if track.album:
                        entry.album = track.album.name or ""
                        # Try 320px, fall back to 160px
                        for size in (320, 160):
                            try:
                                url = track.album.image(size)
                                if url:
                                    entry.cover_url = url
                                    break
                            except Exception:
                                continue
                # Set quality early so it's available in SSE and history
                _q = settings.data.quality_audio
                entry.quality = _q.value if hasattr(_q, "value") else str(_q or "LOSSLESS")
                entry.status = "downloading"
                _broadcast({"type": "progress", "track_id": tid, "name": entry.name, "artist": entry.artist, "album": entry.album, "cover_url": entry.cover_url, "quality": entry.quality, "status": "downloading", "progress": 0})

            try:
                if not track:
                    raise ValueError(f"Could not resolve track {tid}")

                # Retry with exponential backoff for transient errors
                import requests

                _RETRYABLE = (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                    ConnectionError,
                    OSError,
                )
                _MAX_RETRIES = 3
                _last_exc: Exception | None = None

                for _attempt in range(_MAX_RETRIES + 1):
                    try:
                        dl.item(
                            file_template=settings.data.format_track,
                            media=track,
                            quality_audio=settings.data.quality_audio,
                        )
                        _last_exc = None
                        break  # success
                    except _RETRYABLE as retry_exc:
                        _last_exc = retry_exc
                        if _attempt < _MAX_RETRIES:
                            backoff = 2 ** (_attempt + 1)  # 2s, 4s, 8s
                            with _lock:
                                entry = _active.get(tid)
                            if entry:
                                entry.status = "retrying"
                                _broadcast({"type": "progress", "track_id": tid, "name": entry.name, "artist": entry.artist, "album": entry.album, "cover_url": entry.cover_url, "quality": entry.quality, "status": "retrying", "progress": 0, "retry": _attempt + 1, "max_retries": _MAX_RETRIES})
                            time.sleep(backoff)
                    except requests.exceptions.HTTPError as http_exc:
                        # Retry on 429 Too Many Requests
                        if hasattr(http_exc, "response") and http_exc.response is not None and http_exc.response.status_code == 429:
                            _last_exc = http_exc
                            if _attempt < _MAX_RETRIES:
                                backoff = 2 ** (_attempt + 1)
                                with _lock:
                                    entry = _active.get(tid)
                                if entry:
                                    entry.status = "retrying"
                                    _broadcast({"type": "progress", "track_id": tid, "name": entry.name, "artist": entry.artist, "album": entry.album, "cover_url": entry.cover_url, "quality": entry.quality, "status": "retrying", "progress": 0, "retry": _attempt + 1, "max_retries": _MAX_RETRIES})
                                time.sleep(backoff)
                        else:
                            raise  # permanent HTTP error

                if _last_exc is not None:
                    raise _last_exc

                with _lock:
                    entry = _active.pop(tid, None)
                if entry:
                    entry.status = "done"
                    entry.progress = 100
                    entry.finished_at = time.time()
                    # quality already set before dl.item(); keep as fallback
                    if not entry.quality:
                        _q = settings.data.quality_audio
                        entry.quality = _q.value if hasattr(_q, "value") else str(_q or "LOSSLESS")

                    # Persist to DB
                    artist_name = entry.artist
                    album_name = entry.album
                    if not artist_name and track.artists:
                        artist_name = ", ".join(a.name for a in track.artists if a.name)
                    if not album_name and track.album:
                        album_name = track.album.name or ""

                    db.record_download(
                        track_id=tid,
                        name=entry.name,
                        artist=artist_name,
                        album=album_name,
                        status="done",
                        started_at=entry.started_at,
                        finished_at=entry.finished_at,
                        cover_url=entry.cover_url,
                        quality=entry.quality,
                    )
                    db.commit()

                    _broadcast({"type": "complete", "track_id": tid, "name": entry.name, "artist": entry.artist, "album": album_name, "cover_url": entry.cover_url, "quality": entry.quality, "status": "done"})

            except Exception as exc:
                with _lock:
                    entry = _active.pop(tid, None)
                if entry:
                    entry.status = "error"
                    entry.finished_at = time.time()

                    # Persist error to DB — wrapped so broadcast always fires
                    try:
                        db.record_download(
                            track_id=tid,
                            name=entry.name,
                            artist=entry.artist,
                            album=entry.album,
                            status="error",
                            error=str(exc),
                            started_at=entry.started_at,
                            finished_at=entry.finished_at,
                            cover_url=entry.cover_url,
                            quality=entry.quality,
                        )
                        db.commit()
                    except Exception:
                        logger.exception("Failed to persist download error for track %s", tid)

                    _broadcast({"type": "error", "track_id": tid, "name": entry.name, "artist": entry.artist, "album": entry.album, "cover_url": entry.cover_url, "error": str(exc)})

        # After all downloads complete, scan download dir for new files
        _scan_new_downloads(db, settings)
        db.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"status": "queued", "count": len(track_ids)}


@router.post("/download")
def download(req: DownloadRequest) -> dict:
    """Trigger download of one or more tracks."""
    if not req.track_ids:
        raise HTTPException(status_code=400, detail="Provide track_ids")

    return trigger_download(req.track_ids)


@router.get("/downloads/active/snapshot")
def downloads_snapshot() -> dict:
    """Return current in-progress downloads (non-SSE)."""
    with _lock:
        entries = [
            {"track_id": e.track_id, "name": e.name, "artist": e.artist,
             "album": e.album, "cover_url": e.cover_url, "quality": e.quality,
             "status": e.status, "progress": e.progress}
            for e in _active.values()
        ]
    return {"active": entries}


@router.get("/downloads/active")
async def downloads_sse() -> StreamingResponse:
    """Server-Sent Events stream for download progress."""
    if len(_sse_clients) >= _MAX_SSE_CLIENTS:
        raise HTTPException(status_code=429, detail="Too many SSE connections")

    queue: asyncio.Queue = asyncio.Queue()
    _sse_clients.append(queue)

    async def event_stream():
        try:
            for entry in _active.values():
                yield f"data: {_json({'type': 'progress', 'track_id': entry.track_id, 'name': entry.name, 'artist': entry.artist, 'album': entry.album, 'cover_url': entry.cover_url, 'quality': entry.quality, 'status': entry.status, 'progress': entry.progress})}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {_json(event)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {_json({'type': 'ping'})}\n\n"
        except Exception:
            pass
        finally:
            if queue in _sse_clients:
                _sse_clients.remove(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/downloads/history")
def downloads_history(limit: int = 50) -> dict:
    """Recent download history from DB, enriched with local file paths."""
    from pathlib import Path

    from tidal_dl.helper.library_db import LibraryDB
    from tidal_dl.helper.path import path_config_base

    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    history = db.download_history(limit)

    # Enrich with local file path from scanned table for reveal-in-finder
    for entry in history:
        name = entry.get("name")
        artist = entry.get("artist")
        album = entry.get("album")
        if name and artist:
            assert db._conn
            # Include album in match to avoid wrong-album hits for same-name tracks
            if album:
                row = db._conn.execute(
                    "SELECT path FROM scanned WHERE title = ? AND artist = ? AND album = ? LIMIT 1",
                    (name, artist, album),
                ).fetchone()
            else:
                row = None
            # Fallback without album if no match (e.g. album metadata differs)
            if not row:
                row = db._conn.execute(
                    "SELECT path FROM scanned WHERE title = ? AND artist = ? LIMIT 1",
                    (name, artist),
                ).fetchone()
            entry["file_path"] = row["path"] if row else None
        else:
            entry["file_path"] = None

    db.close()
    return {"downloads": history}


class DeleteTrackRequest(BaseModel):
    path: str


@router.delete("/library/track")
def delete_track(req: DeleteTrackRequest) -> dict:
    """Delete a track file from disk and remove from library DB."""
    import os
    import platform
    import subprocess
    from pathlib import Path

    from tidal_dl.helper.library_db import LibraryDB
    from tidal_dl.helper.path import path_config_base

    file_path = Path(req.path)

    # Delete from disk
    if file_path.exists():
        try:
            os.remove(str(file_path))
        except OSError:
            if platform.system() == "Darwin":
                posix = str(file_path).replace('"', '\\"')
                subprocess.run(
                    ["osascript", "-e", f'tell application "Finder" to delete POSIX file "{posix}"'],
                    capture_output=True,
                )
            else:
                raise HTTPException(status_code=500, detail="Failed to delete file")

    # Remove from library DB
    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    db.remove(str(file_path))
    db.commit()
    db.close()

    return {"status": "deleted", "path": str(file_path)}


class RevealRequest(BaseModel):
    path: str


@router.post("/downloads/reveal")
def reveal_in_finder(req: RevealRequest) -> dict:
    """Reveal a file in Finder (macOS) or file manager."""
    import platform
    import subprocess
    from pathlib import Path

    file_path = Path(req.path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", "-R", str(file_path)])
    elif system == "Windows":
        subprocess.Popen(["explorer", "/select,", str(file_path)])
    else:
        # Linux: open containing folder
        subprocess.Popen(["xdg-open", str(file_path.parent)])

    return {"status": "ok"}


@router.delete("/downloads/history")
def clear_history(status: str | None = None) -> dict:
    """Clear download history. Optional ?status=done or ?status=error filter."""
    from pathlib import Path

    from tidal_dl.helper.library_db import LibraryDB
    from tidal_dl.helper.path import path_config_base

    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    deleted = db.clear_download_history(status)
    db.close()
    return {"deleted": deleted}


def _json(obj: Any) -> str:
    return json.dumps(obj)
