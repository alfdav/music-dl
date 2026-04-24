"""Download management — trigger downloads, SSE progress, history."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


def _job_service(request: Request):
    return request.app.state.download_jobs


class DownloadRequest(BaseModel):
    track_ids: list[int] = []


@router.post("/download")
def download(req: DownloadRequest, request: Request) -> dict:
    """Trigger download of one or more tracks."""
    if not req.track_ids:
        raise HTTPException(status_code=400, detail="Provide track_ids")

    from tidal_dl.config import Tidal

    try:
        logged_in = Tidal().session.check_login()
    except Exception:
        logged_in = False

    if not logged_in:
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    return _job_service(request).enqueue_download(req.track_ids)


@router.post("/downloads/pause")
def pause_downloads(request: Request) -> dict:
    """Pause the download queue. Current track finishes, then queue waits."""
    return _job_service(request).pause()


@router.post("/downloads/resume")
def resume_downloads(request: Request) -> dict:
    """Resume the download queue."""
    return _job_service(request).resume()


class CancelRequest(BaseModel):
    track_ids: list[int] | None = None


@router.post("/downloads/cancel")
def cancel_downloads(request: Request, req: CancelRequest | None = None) -> dict:
    """Cancel downloads. If track_ids given, cancel those; otherwise cancel all."""
    return _job_service(request).cancel(req.track_ids if req else None)


@router.get("/downloads/queue-state")
def queue_state(request: Request) -> dict:
    """Return the current queue control state."""
    return _job_service(request).queue_state()


@router.get("/downloads/active/snapshot")
def downloads_snapshot(request: Request) -> dict:
    """Return current in-progress downloads (non-SSE).

    Only returns actively-downloading items individually; queued items
    are summarised as a count to keep payloads small for large queues.
    """
    return _job_service(request).snapshot()


@router.get("/downloads/active")
async def downloads_sse(request: Request) -> StreamingResponse:
    """Server-Sent Events stream for download progress."""
    service = _job_service(request)
    try:
        queue = service.events.subscribe()
    except RuntimeError:
        raise HTTPException(status_code=429, detail="Too many SSE connections")

    async def event_stream():
        try:
            for event in service.initial_events():
                yield f"data: {_json(event)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {_json(event)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {_json({'type': 'ping'})}\n\n"
        finally:
            service.events.unsubscribe(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/downloads/history")
def downloads_history(limit: int = Query(50, ge=1, le=500)) -> dict:
    """Recent download history from DB, enriched with local file paths."""
    from pathlib import Path

    from tidal_dl.helper.library_db import LibraryDB
    from tidal_dl.helper.path import path_config_base

    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    try:
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
    finally:
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

    from tidal_dl.gui.security import validate_audio_path
    from tidal_dl.helper.library_db import LibraryDB
    from tidal_dl.helper.path import path_config_base

    # Validate path is within configured library directories
    from tidal_dl.config import Settings
    s = Settings()
    bp = s.data.download_base_path if hasattr(s.data, "download_base_path") else ""
    allowed = [str(Path(bp).expanduser())] if bp else []
    validated = validate_audio_path(req.path, allowed)
    if validated is None:
        raise HTTPException(status_code=400, detail="Invalid path")
    file_path = validated

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

    from tidal_dl.gui.security import validate_audio_path

    from pathlib import Path

    from tidal_dl.config import Settings
    s = Settings()
    bp = s.data.download_base_path if hasattr(s.data, "download_base_path") else ""
    allowed = [str(Path(bp).expanduser())] if bp else []
    validated = validate_audio_path(req.path, allowed)
    if validated is None:
        raise HTTPException(status_code=400, detail="Invalid path")
    file_path = validated
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
    if status is not None and status not in ("done", "error"):
        raise HTTPException(status_code=400, detail="status must be 'done' or 'error'")

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
