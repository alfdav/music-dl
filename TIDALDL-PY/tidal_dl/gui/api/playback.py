"""Audio playback endpoints — Tidal streaming and local file serving."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from tidal_dl.config import Settings, Tidal

router = APIRouter()


def get_download_paths() -> list[str]:
    """Return all configured directories that may contain audio files."""
    settings = Settings()
    paths = [str(Path(settings.data.download_base_path).expanduser())]
    if settings.data.scan_paths:
        paths.extend(str(Path(p.strip()).expanduser()) for p in settings.data.scan_paths.split(",") if p.strip())
    return paths


@router.get("/local")
def serve_local_file(path: str = Query(..., description="Absolute path to audio file")):
    """Serve a local audio file. Path must be within a configured download directory."""
    from tidal_dl.gui.security import validate_audio_path

    allowed = get_download_paths()
    validated_path = validate_audio_path(path, allowed)
    # Fallback: if path is in our library DB, we already trusted it during scan
    if validated_path is None:
        from tidal_dl.gui.api.library import _path_in_library

        if _path_in_library(path):
            try:
                validated_path = Path(path).resolve(strict=True)
            except (OSError, ValueError):
                validated_path = None
    if validated_path is None:
        raise HTTPException(status_code=403, detail="Access denied")

    media_types = {
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".aac": "audio/aac",
    }
    media_type = media_types.get(validated_path.suffix.lower(), "audio/flac")
    return FileResponse(validated_path, media_type=media_type)


@router.get("/stream/{track_id}")
def stream_tidal_track(track_id: int):
    """Proxy a Tidal stream to the browser. Full if OAuth, preview fallback."""
    import requests as http_requests

    from tidal_dl.gui.security import validate_stream_url

    tidal = Tidal()
    session = tidal.session

    if session.check_login():
        try:
            track = session.track(track_id)
            stream = track.get_stream()
            manifest = stream.get_stream_manifest()
            urls = manifest.get_urls()
            if urls:
                stream_url = urls[0]
                if not validate_stream_url(stream_url):
                    raise HTTPException(status_code=502, detail="Untrusted stream source")
                resp = http_requests.get(
                    stream_url, stream=True, timeout=30, allow_redirects=True
                )
                content_type = resp.headers.get("Content-Type", "audio/flac")
                headers = {}
                if resp.headers.get("Content-Length"):
                    headers["Content-Length"] = resp.headers["Content-Length"]
                return StreamingResponse(
                    resp.iter_content(chunk_size=8192),
                    media_type=content_type,
                    headers=headers,
                )
        except HTTPException:
            raise
        except Exception:
            pass

    # Fallback: 30-second preview (host is hardcoded + track_id is int, but validate anyway)
    try:
        preview_url = f"https://listening-test.tidal.com/v1/tracks/{track_id}/preview"
        if not validate_stream_url(preview_url):
            raise HTTPException(status_code=502, detail="Untrusted preview source")
        resp = http_requests.get(preview_url, stream=True, timeout=15)
        if resp.status_code == 200:
            return StreamingResponse(
                resp.iter_content(chunk_size=8192),
                media_type=resp.headers.get("Content-Type", "audio/mp4"),
            )
    except Exception:
        pass

    raise HTTPException(status_code=503, detail="Unable to stream track")


@router.get("/waveform")
def get_waveform(path: str = Query(..., description="Absolute path to audio file")):
    """Return pre-computed waveform peaks (display + hires) for a local track.

    Display peaks (~100) define the static bar shape.
    Hires peaks (~10/sec) drive per-frame animation during playback.
    Both are extracted at scan time and cached in the library DB.
    """
    from tidal_dl.gui.security import validate_audio_path
    from tidal_dl.helper.library_db import LibraryDB
    from tidal_dl.helper.path import path_config_base
    from tidal_dl.helper.waveform import extract_both, peaks_from_json, peaks_to_json

    s = Settings()
    allowed = [s.data.download_base_path] if hasattr(s.data, "download_base_path") else []
    if validate_audio_path(path, allowed) is None:
        raise HTTPException(status_code=400, detail="Invalid path")

    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    try:
        row = db._conn.execute(
            "SELECT waveform, waveform_hires FROM scanned WHERE path = ?", (path,)
        ).fetchone()

        if row and row["waveform"] and row["waveform_hires"]:
            display = peaks_from_json(row["waveform"])
            hires = peaks_from_json(row["waveform_hires"])
            if display and hires:
                return {"peaks": display, "hires": hires}

        # Not cached — extract on demand (single ffmpeg decode) and store
        both = extract_both(path)
        if both:
            db._conn.execute(
                "UPDATE scanned SET waveform = ?, waveform_hires = ? WHERE path = ?",
                (peaks_to_json(both[0]), peaks_to_json(both[1]), path),
            )
            db.commit()
    finally:
        db.close()

    if not both:
        raise HTTPException(status_code=404, detail="Could not extract waveform")
    return {"peaks": both[0], "hires": both[1]}
