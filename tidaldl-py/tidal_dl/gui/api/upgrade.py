"""Track quality upgrade — probe Tidal, compare tiers, re-download upgrades."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from tidal_dl.constants import TIER_RANK
from tidal_dl.gui.services.job_models import UpgradeJobInput
from tidal_dl.gui.services.upgrade_jobs import tier_rank_for_quality as _tier_rank_for_quality
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base


def _norm(s: str) -> str:
    """Normalize string for comparison: lowercase, alphanumeric only."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|\+|/|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b|\bwith\b|\bx\b)\s*",
    re.IGNORECASE,
)


def _artist_parts(raw: str) -> set[str]:
    """Return normalized artist/collaborator parts from a metadata artist string."""
    parts = {_norm(raw)} if raw else set()
    for piece in _ARTIST_SPLIT_RE.split(raw or ""):
        normed = _norm(piece)
        if normed:
            parts.add(normed)
    return parts


def _track_artist_parts(track: Any) -> set[str]:
    """Return normalized artist parts from a Tidal track object."""
    raw_artists: list[str] = []
    if hasattr(track, "artists"):
        raw_artists.extend(a.name for a in (track.artists or []) if getattr(a, "name", None))
    artist = getattr(track, "artist", None)
    if getattr(artist, "name", None):
        raw_artists.append(artist.name)

    joined = ", ".join(raw_artists)
    parts = _artist_parts(joined)
    for raw in raw_artists:
        parts.update(_artist_parts(raw))
    return parts


def _artist_matches(local_artist: str, track: Any) -> bool:
    """Match local artist metadata to Tidal primary/collaborator artists.

    A local primary artist may match one Tidal artist even when Tidal has
    collaborators, but normalized prefixes must not match ("Drake" !=
    "Drake Bell").
    """
    local_parts = _artist_parts(local_artist)
    tidal_parts = _track_artist_parts(track)
    return bool(local_parts and tidal_parts and local_parts.intersection(tidal_parts))


def _titles_compatible(left: str, right: str) -> bool:
    """True when titles are the same song, allowing short parenthetical variants."""
    a, b = _norm(left), _norm(right)
    return bool(a and b and (a == b or a in b or b in a))


def _incompatible_titles(titles: list[str]) -> bool:
    norms = [_norm(title) for title in titles if _norm(title)]
    return any(
        a != b and a not in b and b not in a
        for i, a in enumerate(norms)
        for b in norms[i + 1 :]
    )


def _colliding_isrcs(tracks: list[dict]) -> set[str]:
    """ISRCs stamped on local files whose titles are clearly different songs."""
    groups: dict[str, list[str]] = {}
    for track in tracks:
        isrc = (track.get("isrc") or "").strip().upper()
        if not isrc:
            continue
        groups.setdefault(isrc, []).append(track.get("title") or "")
    return {isrc for isrc, titles in groups.items() if _incompatible_titles(titles)}


def _reject_colliding_isrc_matches(results: list[dict]) -> list[dict]:
    colliding = _colliding_isrcs(results)
    if not colliding:
        return results
    return [row for row in results if (row.get("isrc") or "").strip().upper() not in colliding]


def _shared_tidal_ids_with_title_collision(items: list[dict]) -> set[int]:
    groups: dict[int, list[str]] = {}
    for item in items:
        tid = item.get("tidal_track_id")
        if not tid:
            continue
        groups.setdefault(int(tid), []).append(item.get("title") or "")
    return {tid for tid, titles in groups.items() if _incompatible_titles(titles)}


def _tracks_for_isrc(db: Any, isrc: str) -> list[dict]:
    getter = getattr(db, "tracks_by_isrc", None)
    if not isrc or not callable(getter):
        return []
    return getter(isrc) or []


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
_scan_lock = threading.Lock()
_scan_event_loop: asyncio.AbstractEventLoop | None = None


def set_scan_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _scan_event_loop
    _scan_event_loop = loop


def _json(obj: Any) -> str:
    return json.dumps(obj)


def _scan_broadcast(event: dict) -> None:
    """Send event to all connected scan SSE clients (thread-safe)."""
    if _scan_event_loop is None or _scan_event_loop.is_closed():
        return
    for q in _scan_clients[:]:
        try:
            _scan_event_loop.call_soon_threadsafe(q.put_nowait, event)
        except Exception:  # noqa: BLE001, S110
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db() -> LibraryDB:
    """Open and return a LibraryDB connection."""
    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    return db


def _probe_tidal_isrc(
    session: Any, isrc: str, title: str = "", artist: str = "", duration: int = 0
) -> dict | None:
    """Search Tidal and return a quality match that is the same song.

    ISRC alone is not identity: playlist dumps clone one ISRC onto many titles.
    Prefer title+artist+duration; an ISRC hit is kept only when titles agree.
    """
    from tidalapi.media import Track

    try:
        query = f"{title} {artist}".strip() or isrc
        results = session.search(query, models=[Track], limit=20)
        tracks = results.get("tracks", []) if isinstance(results, dict) else []
        if not tracks:
            tracks = getattr(results, "tracks", []) or []

        isrc_hit = None
        meta_hit = None
        for t in tracks:
            t_title = getattr(t, "name", "") or getattr(t, "full_name", "") or ""
            title_ok = _titles_compatible(title, t_title)
            t_isrc = getattr(t, "isrc", None)
            isrc_ok = bool(t_isrc and isrc and t_isrc.upper() == isrc.upper())
            duration_ok = True
            if duration > 0:
                t_dur = getattr(t, "duration", 0) or 0
                if t_dur > 0 and abs(t_dur - duration) > 5:
                    duration_ok = False
            if isrc_ok and title_ok and duration_ok:
                isrc_hit = t
                break
            if title_ok and duration_ok and _artist_matches(artist, t) and meta_hit is None:
                meta_hit = t

        chosen = isrc_hit or meta_hit
        if chosen is None:
            return None
        return {"tidal_track_id": chosen.id, "max_quality": _extract_quality(chosen)}
    except Exception:
        logger.exception("Probe failed for ISRC %s", isrc)
        return None


def _is_quality_upgrade(local_rank: int, probed_rank: int) -> bool:
    """True when Tidal has a higher tier than the local file."""
    return probed_rank > local_rank


def _request_upgrade_quality(probed_quality: str, target_quality: str) -> str:
    """Request Tidal's available tier, capped at the configured upgrade target."""
    probed_rank = TIER_RANK.get(probed_quality, 0)
    target_rank = TIER_RANK.get(target_quality, 0)
    if probed_rank <= 0:
        return target_quality
    if target_rank <= 0 or probed_rank <= target_rank:
        return probed_quality
    return target_quality


def _extract_quality(t: Any) -> str:
    """Extract max quality string from a Tidal track object."""
    tags = getattr(t, "media_metadata_tags", None) or []
    audio_quality = getattr(t, "audio_quality", None) or ""
    max_q = str(audio_quality).upper() if audio_quality else "LOSSLESS"
    tag_upper = [str(tag).upper() for tag in tags]
    if "HIRES_LOSSLESS" in tag_upper or "HI_RES_LOSSLESS" in tag_upper:
        max_q = "HI_RES_LOSSLESS"
    elif "HIRES" in tag_upper or "HI_RES" in tag_upper or "MQA" in tag_upper:
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

        target_title = _norm(title)
        for t in tracks:
            t_name = _norm(getattr(t, "name", "") or getattr(t, "full_name", "") or "")
            # Title must match closely (substring ok — titles are usually unique)
            if target_title not in t_name and t_name not in target_title:
                continue
            # Artist must match a full normalized artist/collaborator part to prevent
            # wrong-artist downloads (e.g. "Drake" != "Drake Bell") while allowing
            # multi-artist tracks (e.g. local "Drake" vs Tidal "Drake, Future").
            if not _artist_matches(artist, t):
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


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ProbeRequest(BaseModel):
    isrcs: list[str]
    force: bool = False


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

    from tidal_dl.config import Tidal

    tidal = Tidal()
    session = tidal.session

    db = _get_db()
    try:
        # Check cache for all ISRCs unless caller explicitly forces a refresh
        cached = {} if req.force else db.get_probes_batch(req.isrcs)
        misses = list(req.isrcs) if req.force else [isrc for isrc in req.isrcs if isrc not in cached]

        local_rows: list[dict] = []
        for isrc in req.isrcs:
            local_rows.extend(_tracks_for_isrc(db, isrc))
        colliding = _colliding_isrcs(local_rows)

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
        # NOTE: This blocks the worker thread for up to 2s × len(misses).
        # Acceptable because sync handlers run in uvicorn's threadpool, not event loop.
        for i, isrc in enumerate(misses):
            if isrc.strip().upper() in colliding:
                continue
            if i > 0:
                time.sleep(1)
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
            if isrc.strip().upper() in colliding:
                results.append({
                    "isrc": isrc,
                    "tidal_track_id": None,
                    "max_quality": None,
                    "upgradeable": False,
                })
                continue
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

    from tidal_dl.config import Tidal

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


@router.delete("/upgrade/probes")
def purge_probes() -> dict:
    """Clear all cached Tidal quality probes so the next scan re-probes fresh."""
    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    try:
        assert db._conn
        cur = db._conn.execute("DELETE FROM quality_probes")
        deleted = cur.rowcount
        db.commit()
    finally:
        db.close()
    return {"deleted": deleted}


@router.post("/upgrade/start")
def start_upgrade(req: UpgradeStartRequest, request: Request) -> dict:
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

    db = _get_db()
    try:
        track_ids: list[int] = []
        upgrade_map: dict[int, str] = {}  # tidal_track_id -> old_path
        request_quality: dict[int, str] = {}
        skipped = 0
        errors: list[str] = []
        resolved: list[tuple[str, int | None, dict]] = []

        for path, direct_tid in all_items:
            row = db.get(path)
            if not row:
                errors.append(f"Not in library: {path}")
                continue
            resolved.append((path, direct_tid, row))

        colliding_isrcs = _colliding_isrcs([row for _, _, row in resolved])
        for _, _, row in resolved:
            isrc = row.get("isrc")
            if isrc:
                colliding_isrcs |= _colliding_isrcs(_tracks_for_isrc(db, isrc))
        colliding_tids = _shared_tidal_ids_with_title_collision([
            {"title": row.get("title") or "", "tidal_track_id": direct_tid}
            for _, direct_tid, row in resolved
        ])

        for path, direct_tid, row in resolved:
            # If tidal_track_id provided directly (from meta probe), use it
            if direct_tid:
                if int(direct_tid) in colliding_tids:
                    errors.append(f"Uncertain identity: {path}")
                    skipped += 1
                    continue
                track_ids.append(direct_tid)
                upgrade_map[direct_tid] = path
                isrc = row.get("isrc")
                probe = db.get_probe(isrc) if isrc else None
                probed_quality = (probe or {}).get("max_quality") or target_quality
                request_quality[direct_tid] = _request_upgrade_quality(probed_quality, target_quality)
                continue
            isrc = row.get("isrc")
            if not isrc:
                errors.append(f"No ISRC: {path}")
                skipped += 1
                continue
            if isrc.upper() in colliding_isrcs:
                errors.append(f"Uncertain identity: {path}")
                skipped += 1
                continue

            probe = db.get_probe(isrc)
            if not probe or not probe.get("tidal_track_id") or not probe.get("max_quality"):
                errors.append(f"No probe data: {path}")
                skipped += 1
                continue

            probed_rank = TIER_RANK.get(probe["max_quality"], 0)
            local_rank = _tier_rank_for_quality(
                row.get("quality"), row.get("format"), row.get("codec")
            )

            if not _is_quality_upgrade(local_rank, probed_rank):
                skipped += 1
                continue

            tid = probe["tidal_track_id"]
            if tid and tid not in upgrade_map:
                track_ids.append(tid)
                upgrade_map[tid] = path
                request_quality[tid] = _request_upgrade_quality(probe["max_quality"], target_quality)
    finally:
        db.close()

    if track_ids:
        items = [
            UpgradeJobInput(
                track_id=tid,
                old_path=upgrade_map[tid],
                quality=request_quality.get(tid, target_quality),
            )
            for tid in track_ids
        ]
        queued = request.app.state.download_jobs.enqueue_upgrade(items)
    else:
        queued = {"count": 0, "skipped": 0}

    return {
        "status": "queued",
        "count": queued["count"],
        "skipped": skipped + queued.get("skipped", 0),
        "errors": errors,
    }

# ---------------------------------------------------------------------------
# Bulk scan SSE
# ---------------------------------------------------------------------------


@router.get("/upgrade/scan")
async def scan_sse() -> StreamingResponse:
    """SSE stream for bulk upgrade scan progress."""
    if len(_scan_clients) >= _MAX_SSE_CLIENTS:
        raise HTTPException(status_code=429, detail="Too many SSE connections")

    # If scan already finished (complete/error/cancelled), return cached terminal event
    with _scan_lock:
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
                except TimeoutError:
                    yield f"data: {_json({'type': 'ping'})}\n\n"
        except Exception:  # noqa: BLE001, S110
            pass
        finally:
            if queue in _scan_clients:
                _scan_clients.remove(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _start_bulk_scan(cancel_event: threading.Event) -> None:
    """Background thread: scan all local tracks for upgrade candidates."""
    from tidal_dl.config import Settings, Tidal

    db = None
    try:
        db = _get_db()
        settings = Settings()
        target_quality = getattr(settings.data, "upgrade_target_quality", "HI_RES_LOSSLESS")
        target_rank = TIER_RANK.get(target_quality, 4)

        # Verify Tidal login
        from tidal_dl.gui.api.settings import ensure_tidal_logged_in

        tidal = Tidal()
        if not ensure_tidal_logged_in(tidal):
            _scan_state.update(status="error", error="Not logged in to Tidal")
            _scan_broadcast({"type": "scan_error", "error": "Not logged in to Tidal"})
            return
        session = tidal.session

        # Get all tracks with ISRCs
        all_tracks = db.upgradeable_tracks()
        all_count = len(all_tracks)

        _scan_state.update(status="running", total=all_count)
        _scan_broadcast({"type": "scan_progress", "checked": 0, "total": all_count,
                         "upgradeable": 0, "skipped_no_isrc": 0,
                         "phase": "Verifying library files..."})

        # Filter: only tracks below target quality that exist on disk
        candidates = []
        skipped_no_isrc = 0
        stale_paths: list[str] = []
        for i, t in enumerate(all_tracks):
            if cancel_event.is_set():
                _scan_state.update(status="cancelled")
                _scan_broadcast({"type": "scan_cancelled", "checked": 0, "total": all_count})
                return

            isrc = t.get("isrc")
            if not isrc:
                skipped_no_isrc += 1
                continue
            # Skip entries whose files no longer exist (orphaned DB rows)
            if not os.path.exists(t["path"]):
                stale_paths.append(t["path"])
                continue
            local_rank = _tier_rank_for_quality(
                t.get("quality"), t.get("format"), t.get("codec")
            )
            if local_rank < target_rank:
                candidates.append(t)

            # Broadcast file verification progress every 200 tracks
            if (i + 1) % 200 == 0 or (i + 1) == all_count:
                _scan_broadcast({"type": "scan_progress", "checked": 0, "total": all_count,
                                 "upgradeable": 0, "skipped_no_isrc": skipped_no_isrc,
                                 "phase": f"Verifying files... {i + 1:,} / {all_count:,}"})

        # Clean up stale DB entries — only if less than 5% are stale
        # (protects against NAS disconnection nuking the entire library)
        if stale_paths:
            stale_pct = len(stale_paths) / max(all_count, 1)
            if stale_pct < 0.05:
                for sp in stale_paths:
                    db.remove(sp)
                db.commit()
                logger.info("Cleaned %d stale scanned entries", len(stale_paths))
            else:
                logger.warning("Skipped stale cleanup: %d/%d (%.0f%%) entries missing — possible volume offline",
                               len(stale_paths), all_count, stale_pct * 100)

        total = len(candidates)
        checked = 0
        upgradeable_results: list[dict] = []

        # Batch check probe cache
        all_isrcs = [t["isrc"] for t in candidates]
        cached_probes = db.get_probes_batch(all_isrcs)
        colliding = _colliding_isrcs(candidates)

        for t in candidates:
            if cancel_event.is_set():
                _scan_state.update(status="cancelled", checked=checked, total=total)
                _scan_broadcast({"type": "scan_cancelled", "checked": checked, "total": total})
                return

            isrc = t["isrc"]
            isrc_collides = isrc.upper() in colliding
            probe = None if isrc_collides else cached_probes.get(isrc)

            # Probe Tidal for cache misses. Colliding ISRCs are per-title only.
            if probe is None:
                probe_result = _probe_tidal_isrc(
                    session,
                    isrc,
                    title=t.get("title", ""),
                    artist=t.get("artist", ""),
                    duration=t.get("duration", 0) or 0,
                )
                if probe_result:
                    if not isrc_collides:
                        db.set_probe(isrc, probe_result["tidal_track_id"], probe_result["max_quality"])
                    probe = {
                        "isrc": isrc,
                        "tidal_track_id": probe_result["tidal_track_id"],
                        "max_quality": probe_result["max_quality"],
                    }
                else:
                    if not isrc_collides:
                        db.set_probe(isrc, 0, "")
                    probe = {"isrc": isrc, "tidal_track_id": 0, "max_quality": ""}
                if not isrc_collides:
                    db.commit()
                time.sleep(2)  # 0.5 req/sec rate limit

            # Check if upgradeable
            if probe.get("tidal_track_id") and probe.get("max_quality"):
                probed_rank = TIER_RANK.get(probe["max_quality"], 0)
                local_rank = _tier_rank_for_quality(
                    t.get("quality"), t.get("format"), t.get("codec")
                )
                if _is_quality_upgrade(local_rank, probed_rank):
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
        with _scan_lock:
            _scan_state.update(status="error", error=str(exc))
        _scan_broadcast({"type": "scan_error", "error": str(exc)})
    finally:
        with _scan_lock:
            _scan_state["running"] = False
            _scan_state["cancel"] = None
        if db:
            db.close()


def _rebuild_results_from_db() -> list[dict]:
    """Reconstruct upgradeable results from scanned + quality_probes tables.

    Called when _scan_state is idle (e.g. after server restart) to avoid
    forcing the user to re-scan. Returns the same structure as a live scan.
    """
    from tidal_dl.config import Settings

    settings = Settings()
    target_quality = getattr(settings.data, "upgrade_target_quality", "HI_RES_LOSSLESS")
    target_rank = TIER_RANK.get(target_quality, 4)

    db = _get_db()
    try:
        all_tracks = db.upgradeable_tracks()
        all_isrcs = [t["isrc"] for t in all_tracks if t.get("isrc")]
        if not all_isrcs:
            return []
        cached_probes = db.get_probes_batch(all_isrcs)
        colliding = _colliding_isrcs(all_tracks)
        results = []
        for t in all_tracks:
            isrc = t.get("isrc")
            if not isrc or isrc.upper() in colliding:
                continue
            probe = cached_probes.get(isrc)
            if not probe or not probe.get("tidal_track_id") or not probe.get("max_quality"):
                continue
            probed_rank = TIER_RANK.get(probe["max_quality"], 0)
            local_rank = _tier_rank_for_quality(
                t.get("quality"), t.get("format"), t.get("codec")
            )
            if _is_quality_upgrade(local_rank, probed_rank):
                results.append({
                    "path": t["path"],
                    "title": t.get("title", ""),
                    "artist": t.get("artist", ""),
                    "album": t.get("album", ""),
                    "current_quality": t.get("quality", ""),
                    "available_quality": probe["max_quality"],
                    "isrc": isrc,
                    "tidal_track_id": probe["tidal_track_id"],
                })
        return results
    finally:
        db.close()


@router.get("/upgrade/scan/status")
def scan_status(include_results: bool = Query(False)) -> dict:
    """Return cached scan state without triggering a new scan.

    When idle (e.g. after server restart), reconstructs results from DB
    so the user never has to re-scan just because the server restarted.
    """
    status = _scan_state["status"]

    # If idle and probes exist in DB, rebuild from DB
    if status == "idle":
        try:
            results = _rebuild_results_from_db()
            if results:
                # Populate _scan_state so subsequent calls are instant
                _scan_state.update(
                    status="complete",
                    checked=len(results),
                    total=len(results),
                    upgradeable=len(results),
                    results=results,
                )
                status = "complete"
        except Exception:  # noqa: BLE001, S110
            pass  # fall through to idle

    resp: dict = {
        "status": status,
        "checked": _scan_state["checked"],
        "total": _scan_state["total"],
        "upgradeable": _scan_state["upgradeable"],
        "skipped_no_isrc": _scan_state["skipped_no_isrc"],
        "error": _scan_state.get("error"),
    }
    if status == "complete" and _scan_state.get("results"):
        filtered = _reject_colliding_isrc_matches(list(_scan_state["results"]))
        if len(filtered) != len(_scan_state["results"]):
            _scan_state["results"] = filtered
            _scan_state["upgradeable"] = len(filtered)
        resp["upgradeable"] = _scan_state["upgradeable"]
    if include_results and status == "complete":
        resp["results"] = _scan_state["results"]
    else:
        resp["results"] = []
    return resp


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
        local_rows: list[dict] = []
        for isrc in isrc_list:
            local_rows.extend(_tracks_for_isrc(db, isrc))
        colliding = _colliding_isrcs(local_rows)
        results = []
        for isrc in isrc_list:
            if isrc.strip().upper() in colliding:
                results.append({
                    "isrc": isrc,
                    "tidal_track_id": None,
                    "max_quality": None,
                })
                continue
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
