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
