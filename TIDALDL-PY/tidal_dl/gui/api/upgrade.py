"""Track quality upgrade — probe Tidal, compare tiers, re-download upgrades."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from tidal_dl.constants import QUALITY_STRING_TO_ENUM, TIER_RANK
from tidal_dl.gui.api.downloads import DownloadEntry, _active, _broadcast, _lock
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

router = APIRouter()
logger = logging.getLogger("music-dl.upgrade")

# ---------------------------------------------------------------------------
# Module-level state for bulk scan SSE
# ---------------------------------------------------------------------------
_scan_state: dict[str, Any] = {
    "running": False,
    "cancel": None,
    "status": "idle",        # idle | running | complete | error | cancelled
    "checked": 0,
    "total": 0,
    "upgradeable": 0,
    "skipped_no_isrc": 0,
    "results": [],           # final scan_complete results (survives navigation)
    "error": None,
}
_scan_clients: list[asyncio.Queue] = []
_MAX_SSE_CLIENTS = 5


def _json(obj: Any) -> str:
    return json.dumps(obj)


def _scan_broadcast(event: dict) -> None:
    """Send event to all connected scan SSE clients."""
    for q in _scan_clients[:]:
        try:
            q.put_nowait(event)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db() -> LibraryDB:
    """Open and return a LibraryDB connection."""
    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    return db


def _tier_rank_for_quality(q: str | None, fmt: str | None = None) -> int:
    """Map a quality string + format to a numeric tier rank.

    Handles TIER_RANK direct keys (LOSSLESS, HIGH, MP3, FLAC, etc.)
    and local file quality strings like "44100Hz/16bit" or "96000Hz/24bit".

    The *fmt* parameter (file format: FLAC, M4A, MP3, etc.) is used to cap
    lossy formats at Uncommon (rank 1) regardless of the quality string.
    Without this, an M4A reporting "44100Hz/16bit" would be ranked Rare.
    """
    if not q:
        return 0

    # Lossy formats cap at Uncommon regardless of quality string
    _LOSSY_FORMATS = {"MP3", "AAC", "OGG", "M4A"}
    if fmt and fmt.upper() in _LOSSY_FORMATS:
        return 1  # Uncommon

    # Direct lookup first
    rank = TIER_RANK.get(q.upper())
    if rank is not None:
        return rank

    # Parse local file quality strings: e.g. "96000Hz/24bit", "44100Hz/16bit"
    m = re.match(r"(\d+)Hz/(\d+)bit", q, re.IGNORECASE)
    if m:
        sample_rate = int(m.group(1))
        bit_depth = int(m.group(2))
        if bit_depth >= 24 and sample_rate > 48000:
            return 4  # Legendary
        if bit_depth >= 24:
            return 3  # Epic
        if bit_depth >= 16:
            return 2  # Rare

    return 0


def _probe_tidal_isrc(
    session: Any, isrc: str, title: str = "", artist: str = ""
) -> dict | None:
    """Search Tidal for a track and return the best quality match.

    Searches by title+artist (Tidal's search API doesn't support raw ISRC queries),
    then matches by ISRC in the results.

    Returns {"tidal_track_id": int, "max_quality": str} or None.
    """
    from tidalapi.media import Track

    try:
        # Build search query from title + artist
        query = f"{title} {artist}".strip()
        if not query:
            query = isrc  # fallback, unlikely to work but worth trying

        results = session.search(query, models=[Track], limit=20)
        tracks = results.get("tracks", []) if isinstance(results, dict) else []
        if not tracks:
            tracks = getattr(results, "tracks", []) or []

        for t in tracks:
            t_isrc = getattr(t, "isrc", None)
            if not t_isrc or t_isrc.upper() != isrc.upper():
                continue
            return {"tidal_track_id": t.id, "max_quality": _extract_quality(t)}

        return None
    except Exception:
        logger.exception("Probe failed for ISRC %s", isrc)
        return None


def _extract_quality(t: Any) -> str:
    """Extract max quality string from a Tidal track object."""
    tags = getattr(t, "media_metadata_tags", None) or []
    audio_quality = getattr(t, "audio_quality", None) or ""
    max_q = str(audio_quality).upper() if audio_quality else "LOSSLESS"
    tag_upper = [str(tag).upper() for tag in tags]
    if "HIRES_LOSSLESS" in tag_upper or "HI_RES_LOSSLESS" in tag_upper:
        max_q = "HI_RES_LOSSLESS"
    elif "HIRES" in tag_upper or "HI_RES" in tag_upper:
        max_q = "HI_RES"
    elif "MQA" in tag_upper:
        max_q = "HI_RES"
    return max_q


def _probe_tidal_meta(
    session: Any, title: str, artist: str, duration: int = 0
) -> dict | None:
    """Search Tidal by title+artist and return best match.

    Matches by name similarity and optional duration check (±5s).
    Used as fallback for tracks without ISRC.

    Returns {"tidal_track_id": int, "max_quality": str, "isrc": str} or None.
    """
    from tidalapi.media import Track

    try:
        query = f"{title} {artist}".strip()
        if not query:
            return None

        results = session.search(query, models=[Track], limit=10)
        tracks = results.get("tracks", []) if isinstance(results, dict) else []
        if not tracks:
            tracks = getattr(results, "tracks", []) or []

        # Normalize for comparison
        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]", "", s.lower())

        target_title = _norm(title)
        target_artist = _norm(artist)

        for t in tracks:
            t_name = _norm(getattr(t, "name", "") or getattr(t, "full_name", "") or "")
            t_artist = _norm(", ".join(a.name for a in (t.artists or []) if a.name) if hasattr(t, "artists") else "")

            # Title must match closely
            if target_title not in t_name and t_name not in target_title:
                continue
            # Artist must match closely
            if target_artist not in t_artist and t_artist not in target_artist:
                continue
            # Duration check if available (±5 seconds)
            if duration > 0:
                t_dur = getattr(t, "duration", 0) or 0
                if t_dur > 0 and abs(t_dur - duration) > 5:
                    continue

            return {
                "tidal_track_id": t.id,
                "max_quality": _extract_quality(t),
                "isrc": getattr(t, "isrc", "") or "",
            }

        return None
    except Exception:
        logger.exception("Meta probe failed for %s - %s", artist, title)
        return None


def _trash_file(path: str) -> None:
    """Move file to trash (macOS Finder) or delete."""
    if not os.path.exists(path):
        return

    if platform.system() == "Darwin":
        posix = path.replace('"', '\\"')
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "Finder" to delete POSIX file "{posix}"'],
                capture_output=True,
                timeout=10,
            )
            return
        except Exception:
            pass

    # Fallback: direct delete
    try:
        os.remove(path)
    except OSError:
        logger.warning("Failed to delete old file: %s", path)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ProbeRequest(BaseModel):
    isrcs: list[str]


class ProbeByMetaItem(BaseModel):
    path: str
    title: str
    artist: str


class ProbeByMetaRequest(BaseModel):
    tracks: list[ProbeByMetaItem]


class UpgradeStartItem(BaseModel):
    path: str
    tidal_track_id: int | None = None  # If provided, skip ISRC/probe resolution


class UpgradeStartRequest(BaseModel):
    track_paths: list[str] = []  # Simple paths (resolved via ISRC → probe)
    tracks: list[UpgradeStartItem] = []  # Rich items with optional tidal_track_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/upgrade/probe")
def probe_isrcs(req: ProbeRequest) -> dict:
    """Batch probe ISRCs against Tidal for quality availability."""
    if len(req.isrcs) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 ISRCs per request")
    if not req.isrcs:
        raise HTTPException(status_code=400, detail="Provide at least one ISRC")

    from tidal_dl.config import Settings, Tidal

    settings = Settings()
    target_quality = getattr(settings.data, "upgrade_target_quality", "HI_RES_LOSSLESS")
    target_rank = TIER_RANK.get(target_quality, 4)

    tidal = Tidal()
    session = tidal.session

    db = _get_db()
    try:
        # Check cache for all ISRCs
        cached = db.get_probes_batch(req.isrcs)
        misses = [isrc for isrc in req.isrcs if isrc not in cached]

        # Look up title/artist for cache misses from scanned table
        isrc_meta: dict[str, tuple[str, str]] = {}
        if misses:
            assert db._conn
            ph = ",".join("?" for _ in misses)
            rows = db._conn.execute(
                f"SELECT isrc, title, artist FROM scanned WHERE isrc IN ({ph})", misses
            ).fetchall()
            for r in rows:
                isrc_meta[r["isrc"]] = (r["title"] or "", r["artist"] or "")

        # Probe Tidal for cache misses (0.5 req/sec)
        for i, isrc in enumerate(misses):
            if i > 0:
                time.sleep(2)
            title, artist = isrc_meta.get(isrc, ("", ""))
            result = _probe_tidal_isrc(session, isrc, title=title, artist=artist)
            if result:
                db.set_probe(isrc, result["tidal_track_id"], result["max_quality"])
                cached[isrc] = {
                    "isrc": isrc,
                    "tidal_track_id": result["tidal_track_id"],
                    "max_quality": result["max_quality"],
                }
            else:
                # Cache a "not found" sentinel so we don't re-probe
                db.set_probe(isrc, 0, "")
                cached[isrc] = {
                    "isrc": isrc,
                    "tidal_track_id": 0,
                    "max_quality": "",
                }

        db.commit()

        # Build results
        results = []
        for isrc in req.isrcs:
            probe = cached.get(isrc)
            if probe and probe.get("tidal_track_id") and probe.get("max_quality"):
                probed_rank = TIER_RANK.get(probe["max_quality"], 0)
                results.append({
                    "isrc": isrc,
                    "tidal_track_id": probe["tidal_track_id"],
                    "max_quality": probe["max_quality"],
                    "upgradeable": probed_rank > 0,
                })
            else:
                results.append({
                    "isrc": isrc,
                    "tidal_track_id": None,
                    "max_quality": None,
                    "upgradeable": False,
                })

        return {"results": results}
    finally:
        db.close()


@router.post("/upgrade/probe-by-meta")
def probe_by_meta(req: ProbeByMetaRequest) -> dict:
    """Probe tracks by title+artist when ISRC is missing. Max 20."""
    if len(req.tracks) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 tracks per request")
    if not req.tracks:
        raise HTTPException(status_code=400, detail="Provide at least one track")

    from tidal_dl.config import Settings, Tidal

    settings = Settings()
    target_quality = getattr(settings.data, "upgrade_target_quality", "HI_RES_LOSSLESS")
    target_rank = TIER_RANK.get(target_quality, 4)

    tidal = Tidal()
    session = tidal.session

    db = _get_db()
    try:
        results = []
        for i, item in enumerate(req.tracks):
            if i > 0:
                time.sleep(2)  # 0.5 req/sec

            # Look up duration from DB
            row = db.get(item.path)
            duration = row.get("duration", 0) if row else 0

            probe = _probe_tidal_meta(session, item.title, item.artist, duration)
            if probe and probe.get("tidal_track_id") and probe.get("max_quality"):
                # Cache for future use (now we have the ISRC from Tidal)
                if probe.get("isrc"):
                    db.set_probe(probe["isrc"], probe["tidal_track_id"], probe["max_quality"])
                probed_rank = TIER_RANK.get(probe["max_quality"], 0)
                results.append({
                    "path": item.path,
                    "tidal_track_id": probe["tidal_track_id"],
                    "max_quality": probe["max_quality"],
                    "isrc": probe.get("isrc", ""),
                    "upgradeable": probed_rank > 0,
                })
            else:
                results.append({
                    "path": item.path,
                    "tidal_track_id": None,
                    "max_quality": None,
                    "isrc": None,
                    "upgradeable": False,
                })

        db.commit()
    finally:
        db.close()

    return {"results": results}


@router.post("/upgrade/start")
def start_upgrade(req: UpgradeStartRequest) -> dict:
    """Trigger upgrade downloads for the given local track paths."""
    # Build unified list from both track_paths (simple) and tracks (rich)
    all_items: list[tuple[str, int | None]] = []
    for p in req.track_paths:
        all_items.append((p, None))
    for t in req.tracks:
        all_items.append((t.path, t.tidal_track_id))

    if not all_items:
        raise HTTPException(status_code=400, detail="Provide at least one track path")

    from tidal_dl.config import Settings

    settings = Settings()
    target_quality = getattr(settings.data, "upgrade_target_quality", "HI_RES_LOSSLESS")
    target_rank = TIER_RANK.get(target_quality, 4)

    db = _get_db()
    try:
        track_ids: list[int] = []
        upgrade_map: dict[int, str] = {}  # tidal_track_id -> old_path
        skipped = 0
        errors: list[str] = []

        for path, direct_tid in all_items:
            # If tidal_track_id provided directly (from meta probe), use it
            # No need to validate path — we already have the Tidal track ID
            if direct_tid:
                track_ids.append(direct_tid)
                upgrade_map[direct_tid] = path
                continue

            row = db.get(path)
            if not row:
                errors.append(f"Not in library: {path}")
                continue

            isrc = row.get("isrc")
            if not isrc:
                errors.append(f"No ISRC: {path}")
                skipped += 1
                continue

            probe = db.get_probe(isrc)
            if not probe or not probe.get("tidal_track_id") or not probe.get("max_quality"):
                errors.append(f"No probe data: {path}")
                skipped += 1
                continue

            probed_rank = TIER_RANK.get(probe["max_quality"], 0)
            local_rank = _tier_rank_for_quality(row.get("quality"), row.get("format"))

            if probed_rank <= local_rank:
                skipped += 1
                continue
            if probed_rank < target_rank:
                skipped += 1
                continue

            tid = probe["tidal_track_id"]
            if tid and tid not in upgrade_map:
                track_ids.append(tid)
                upgrade_map[tid] = path
    finally:
        db.close()

    if track_ids:
        thread = threading.Thread(
            target=_trigger_upgrade_downloads,
            args=(track_ids, upgrade_map, settings),
            daemon=True,
        )
        thread.start()

    return {
        "status": "queued",
        "count": len(track_ids),
        "skipped": skipped,
        "errors": errors,
    }


def _trigger_upgrade_downloads(
    track_ids: list[int],
    upgrade_map: dict[int, str],
    settings: Any,
) -> None:
    """Background thread: download upgrades and swap files."""
    from tidal_dl.config import Settings, Tidal
    from tidal_dl.download import Download, register_downloaded_track
    from tidal_dl.model.downloader import DownloadOutcome

    tidal = Tidal()
    settings = Settings()
    dl = Download(
        tidal_obj=tidal,
        path_base=settings.data.download_base_path,
        fn_logger=logger,
        skip_existing=False,
    )
    db = _get_db()

    try:
        for tid in track_ids:
            old_path = upgrade_map.get(tid, "")
            track_name = f"Track {tid}"

            # Register in shared download queue so Downloads tab shows it
            with _lock:
                entry = DownloadEntry(tid, track_name)
                entry.status = "queued"
                _active[tid] = entry
            _broadcast({"type": "progress", "track_id": tid, "name": track_name, "artist": "", "album": "", "cover_url": "", "quality": "", "status": "queued", "progress": 0})

            try:
                track = tidal.session.track(tid)
                track_name = track.full_name or track.name or track_name
                artist_name = ""
                album_name = ""
                cover_url = ""
                if track.artists:
                    artist_name = ", ".join(a.name for a in track.artists if a.name)
                if track.album:
                    album_name = track.album.name or ""
                    for size in (320, 160):
                        try:
                            url = track.album.image(size)
                            if url:
                                cover_url = url
                                break
                        except Exception:
                            continue

                with _lock:
                    entry = _active.get(tid)
                if entry:
                    entry.name = track_name
                    entry.artist = artist_name
                    entry.album = album_name
                    entry.cover_url = cover_url
                    entry.status = "downloading"
                _broadcast({"type": "progress", "track_id": tid, "name": track_name, "artist": artist_name, "album": album_name, "cover_url": cover_url, "quality": "", "status": "downloading", "progress": 0})

            except Exception as exc:
                with _lock:
                    _active.pop(tid, None)
                _broadcast({"type": "error", "track_id": tid, "name": track_name, "artist": "", "album": "", "cover_url": "", "error": str(exc)})
                _broadcast({"type": "upgrade_error", "track_id": tid, "name": track_name, "error": str(exc), "old_path": old_path})
                continue

            # Get probe to determine quality enum for download
            row = db.get(old_path) if old_path else None
            isrc = row.get("isrc") if row else None
            probe = db.get_probe(isrc) if isrc else None

            quality_str = probe.get("max_quality", "HI_RES_LOSSLESS") if probe else "HI_RES_LOSSLESS"
            quality_enum = QUALITY_STRING_TO_ENUM.get(quality_str)
            if quality_enum is None:
                quality_enum = QUALITY_STRING_TO_ENUM.get("HI_RES_LOSSLESS")

            if entry:
                entry.quality = quality_str
            _broadcast({"type": "upgrade_progress", "track_id": tid, "name": track_name, "artist": artist_name, "status": "upgrading", "old_path": old_path})

            try:
                outcome, new_path = dl.item(
                    file_template=settings.data.format_track,
                    media=track,
                    quality_audio=quality_enum,
                    duplicate_action_override="redownload",
                )

                if outcome in (DownloadOutcome.DOWNLOADED, DownloadOutcome.COPIED):
                    # Trash old file if it exists and differs from new
                    if old_path and str(new_path) != old_path and os.path.exists(old_path):
                        _trash_file(old_path)
                        db.remove(old_path)

                    # Register new file in library
                    register_downloaded_track(new_path)
                    db.commit()

                    with _lock:
                        _active.pop(tid, None)
                    _broadcast({"type": "complete", "track_id": tid, "name": track_name, "artist": artist_name, "album": album_name, "cover_url": cover_url, "quality": quality_str, "status": "done"})
                    _broadcast({"type": "upgrade_complete", "track_id": tid, "name": track_name, "artist": artist_name, "status": "done", "old_path": old_path, "new_path": str(new_path)})

                    # Record in download history
                    db.record_download(
                        track_id=tid, name=track_name, artist=artist_name,
                        album=album_name, status="done",
                        started_at=entry.started_at if entry else time.time(),
                        finished_at=time.time(),
                        cover_url=cover_url, quality=quality_str,
                    )
                    db.commit()
                else:
                    with _lock:
                        _active.pop(tid, None)
                    err_msg = f"Download outcome: {outcome}"
                    _broadcast({"type": "error", "track_id": tid, "name": track_name, "artist": artist_name, "album": album_name, "cover_url": cover_url, "error": err_msg})
                    _broadcast({"type": "upgrade_error", "track_id": tid, "name": track_name, "artist": artist_name, "error": err_msg, "old_path": old_path})

            except Exception as exc:
                with _lock:
                    _active.pop(tid, None)
                _broadcast({"type": "error", "track_id": tid, "name": track_name, "artist": artist_name, "album": album_name, "cover_url": cover_url, "error": str(exc)})
                _broadcast({"type": "upgrade_error", "track_id": tid, "name": track_name, "artist": artist_name, "error": str(exc), "old_path": old_path})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Bulk scan SSE
# ---------------------------------------------------------------------------


@router.get("/upgrade/scan")
async def scan_sse() -> StreamingResponse:
    """SSE stream for bulk upgrade scan progress."""
    if len(_scan_clients) >= _MAX_SSE_CLIENTS:
        raise HTTPException(status_code=429, detail="Too many SSE connections")

    # If scan already finished (complete/error/cancelled), return cached terminal event
    if not _scan_state["running"] and _scan_state["status"] in ("complete", "error", "cancelled"):
        terminal = _scan_state.copy()
        terminal.pop("cancel", None)
        terminal.pop("running", None)

        async def cached_stream():
            if terminal["status"] == "complete":
                yield f"data: {_json({'type': 'scan_complete', 'checked': terminal['checked'], 'total': terminal['total'], 'upgradeable': terminal['upgradeable'], 'skipped_no_isrc': terminal['skipped_no_isrc'], 'results': terminal['results']})}\n\n"
            elif terminal["status"] == "error":
                yield f"data: {_json({'type': 'scan_error', 'error': terminal.get('error', 'Unknown error')})}\n\n"
            else:
                yield f"data: {_json({'type': 'scan_cancelled', 'checked': terminal['checked'], 'total': terminal['total']})}\n\n"

        return StreamingResponse(cached_stream(), media_type="text/event-stream")

    # Start scan if not already running
    if not _scan_state["running"]:
        cancel_event = threading.Event()
        _scan_state.update(
            running=True, cancel=cancel_event, status="running",
            checked=0, total=0, upgradeable=0, skipped_no_isrc=0,
            results=[], error=None,
        )
        thread = threading.Thread(target=_start_bulk_scan, args=(cancel_event,), daemon=True)
        thread.start()

    queue: asyncio.Queue = asyncio.Queue()
    _scan_clients.append(queue)

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {_json(event)}\n\n"
                    # Stop streaming after scan completes or is cancelled
                    if event.get("type") in ("scan_complete", "scan_cancelled", "scan_error"):
                        break
                except asyncio.TimeoutError:
                    yield f"data: {_json({'type': 'ping'})}\n\n"
        except Exception:
            pass
        finally:
            if queue in _scan_clients:
                _scan_clients.remove(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _start_bulk_scan(cancel_event: threading.Event) -> None:
    """Background thread: scan all local tracks for upgrade candidates."""
    from tidal_dl.config import Settings, Tidal

    db = _get_db()
    try:
        settings = Settings()
        target_quality = getattr(settings.data, "upgrade_target_quality", "HI_RES_LOSSLESS")
        target_rank = TIER_RANK.get(target_quality, 4)

        # Verify Tidal login
        tidal = Tidal()
        session = tidal.session
        if not session.check_login():
            _scan_state.update(status="error", error="Not logged in to Tidal")
            _scan_broadcast({"type": "scan_error", "error": "Not logged in to Tidal"})
            return

        # Get all tracks with ISRCs
        all_tracks = db.upgradeable_tracks()

        # Filter: only tracks below target quality
        candidates = []
        skipped_no_isrc = 0
        for t in all_tracks:
            isrc = t.get("isrc")
            if not isrc:
                skipped_no_isrc += 1
                continue
            local_rank = _tier_rank_for_quality(t.get("quality"), t.get("format"))
            if local_rank < target_rank:
                candidates.append(t)

        total = len(candidates)
        checked = 0
        upgradeable_results: list[dict] = []

        # Batch check probe cache
        all_isrcs = [t["isrc"] for t in candidates]
        cached_probes = db.get_probes_batch(all_isrcs)

        for t in candidates:
            if cancel_event.is_set():
                _scan_state.update(status="cancelled", checked=checked, total=total)
                _scan_broadcast({"type": "scan_cancelled", "checked": checked, "total": total})
                return

            isrc = t["isrc"]
            probe = cached_probes.get(isrc)

            # Probe Tidal for cache misses
            if probe is None:
                probe_result = _probe_tidal_isrc(
                    session, isrc, title=t.get("title", ""), artist=t.get("artist", "")
                )
                if probe_result:
                    db.set_probe(isrc, probe_result["tidal_track_id"], probe_result["max_quality"])
                    probe = {
                        "isrc": isrc,
                        "tidal_track_id": probe_result["tidal_track_id"],
                        "max_quality": probe_result["max_quality"],
                    }
                else:
                    db.set_probe(isrc, 0, "")
                    probe = {"isrc": isrc, "tidal_track_id": 0, "max_quality": ""}
                db.commit()
                time.sleep(2)  # 0.5 req/sec rate limit

            # Check if upgradeable
            if probe.get("tidal_track_id") and probe.get("max_quality"):
                probed_rank = TIER_RANK.get(probe["max_quality"], 0)
                local_rank = _tier_rank_for_quality(t.get("quality"), t.get("format"))
                if probed_rank > local_rank and probed_rank >= target_rank:
                    upgradeable_results.append({
                        "path": t["path"],
                        "title": t.get("title", ""),
                        "artist": t.get("artist", ""),
                        "album": t.get("album", ""),
                        "current_quality": t.get("quality", ""),
                        "available_quality": probe["max_quality"],
                        "isrc": isrc,
                        "tidal_track_id": probe["tidal_track_id"],
                    })

            checked += 1

            # Cache + broadcast progress every 5 tracks
            if checked % 5 == 0 or checked == total:
                _scan_state.update(
                    checked=checked, total=total,
                    upgradeable=len(upgradeable_results),
                    skipped_no_isrc=skipped_no_isrc,
                )
                _scan_broadcast({
                    "type": "scan_progress",
                    "checked": checked,
                    "total": total,
                    "upgradeable": len(upgradeable_results),
                    "skipped_no_isrc": skipped_no_isrc,
                })

        _scan_state.update(
            status="complete", checked=checked, total=total,
            upgradeable=len(upgradeable_results),
            skipped_no_isrc=skipped_no_isrc,
            results=upgradeable_results,
        )
        _scan_broadcast({
            "type": "scan_complete",
            "checked": checked,
            "total": total,
            "upgradeable": len(upgradeable_results),
            "skipped_no_isrc": skipped_no_isrc,
            "results": upgradeable_results,
        })

    except Exception as exc:
        logger.exception("Bulk scan failed")
        _scan_state.update(status="error", error=str(exc))
        _scan_broadcast({"type": "scan_error", "error": str(exc)})
    finally:
        _scan_state["running"] = False
        _scan_state["cancel"] = None
        db.close()


@router.get("/upgrade/scan/status")
def scan_status() -> dict:
    """Return cached scan state without triggering a new scan."""
    return {
        "status": _scan_state["status"],
        "checked": _scan_state["checked"],
        "total": _scan_state["total"],
        "upgradeable": _scan_state["upgradeable"],
        "skipped_no_isrc": _scan_state["skipped_no_isrc"],
        "results": _scan_state["results"] if _scan_state["status"] == "complete" else [],
        "error": _scan_state.get("error"),
    }


@router.post("/upgrade/scan/cancel")
def cancel_scan() -> dict:
    """Cancel a running bulk scan."""
    cancel = _scan_state.get("cancel")
    if cancel and isinstance(cancel, threading.Event):
        cancel.set()
        return {"status": "cancelling"}
    return {"status": "not_running"}


@router.get("/upgrade/status")
def upgrade_status(isrcs: str = Query("", description="Comma-separated ISRCs, max 100")) -> dict:
    """Cache-only probe lookup — no Tidal API calls."""
    if not isrcs:
        return {"results": []}

    isrc_list = [s.strip() for s in isrcs.split(",") if s.strip()]
    if len(isrc_list) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 ISRCs")

    db = _get_db()
    try:
        cached = db.get_probes_batch(isrc_list)
        results = []
        for isrc in isrc_list:
            probe = cached.get(isrc)
            if probe and probe.get("tidal_track_id") and probe.get("max_quality"):
                results.append({
                    "isrc": isrc,
                    "tidal_track_id": probe["tidal_track_id"],
                    "max_quality": probe["max_quality"],
                })
            else:
                results.append({
                    "isrc": isrc,
                    "tidal_track_id": None,
                    "max_quality": None,
                })
        return {"results": results}
    finally:
        db.close()
