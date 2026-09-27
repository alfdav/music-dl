"""Playlist endpoints — list, tracks, sync."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from tidal_dl.config import Tidal
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.local_identity import (
    candidate_rows_for_track,
    finish_stamp,
    indexed_path_for_row,
    match_local_row,
    stamp_track,
)
from tidal_dl.helper.path import path_config_base

router = APIRouter()
log = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes
_CACHE_MAX_PLAYLISTS = 50
_PLAYLIST_PAGE_SIZE = 50
_PLAYLIST_FETCH_CONCURRENCY = 2
_PLAYLIST_PAGE_CAP = 50
_PLAYLIST_TOTAL_CAP = 10_000
_PLAYLIST_429_RETRIES = 3

_playlist_list_cache: dict = {"data": None, "ts": 0.0}
# playlist_id → {"ts", "last_updated", "etag", "total", "pages": {offset: [catalog]}, "source"}
_playlist_tracks_cache: dict[str, dict] = {}
_playlist_meta_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_last_playlist_timings: dict[str, Any] = {}


def get_tidal():
    return Tidal()


def get_tidal_session():
    from tidal_dl.gui.api.settings import ensure_tidal_logged_in

    tidal = get_tidal()
    ensure_tidal_logged_in(tidal)
    return tidal.session


def _get_playlist_db() -> LibraryDB:
    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    return db


def _normalize(value: str | None) -> str:
    return (value or "").strip().casefold()


def _normalize_updated(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def _title_artist_key(title: str | None, artist: str | None) -> tuple[str, str] | None:
    left = _normalize(title)
    right = _normalize(artist)
    if not left or not right:
        return None
    return left, right


def _best_local_row(
    track_data: dict,
    db: LibraryDB,
    all_tracks: list[dict] | None = None,
    fallback_index: dict[tuple[str, str], list[dict]] | None = None,
) -> dict | None:
    candidates = candidate_rows_for_track(db, track_data)
    if not candidates and all_tracks:
        candidates = list(all_tracks)
    if not candidates and fallback_index:
        key = _title_artist_key(track_data.get("name"), track_data.get("artist"))
        if key is not None:
            candidates = list(fallback_index.get(key, []))
    return match_local_row(track_data, candidates)


def _catalog_quality(track: Any) -> str:
    tags = getattr(track, "media_metadata_tags", None) or []
    if "HIRES_LOSSLESS" in tags:
        return "HI_RES_LOSSLESS"
    if "HIRES" in tags:
        return "HI_RES"
    if "DOLBY_ATMOS" in tags:
        return "DOLBY_ATMOS"
    return getattr(track, "audio_quality", "") or ""


def _serialize_catalog_track(track: Any) -> dict:
    """Catalog fields only — no library DB, no filesystem, no extra Tidal calls."""
    artists = getattr(track, "artists", None) or []
    artist_name = ", ".join(a.name for a in artists if getattr(a, "name", None))
    album = getattr(track, "album", None)
    album_name = getattr(album, "name", "") if album else ""
    album_id = getattr(album, "id", None) if album else None
    cover_url = ""
    if album is not None:
        image = getattr(album, "image", None)
        if callable(image):
            try:
                cover_url = image(320) or ""
            except Exception:  # noqa: BLE001
                cover_url = ""
    artist_id = getattr(artists[0], "id", None) if artists else None
    return {
        "id": getattr(track, "id", None),
        "name": getattr(track, "full_name", None) or getattr(track, "name", "") or "",
        "artist": artist_name,
        "album": album_name,
        "album_id": album_id,
        "artist_id": artist_id,
        "cover_url": cover_url,
        "duration": getattr(track, "duration", 0) or 0,
        "quality": _catalog_quality(track),
        "isrc": getattr(track, "isrc", "") or "",
        "is_local": False,
    }


def _too_many_requests(exc: BaseException) -> bool:
    if type(exc).__name__ == "TooManyRequests":
        return True
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 429


def _retry_after_sec(exc: BaseException) -> float | None:
    retry = getattr(exc, "retry_after", None)
    if retry is None:
        headers = getattr(getattr(exc, "response", None), "headers", None) or {}
        retry = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        value = float(retry)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _call_tracks(playlist: Any, *, limit: int, offset: int) -> list:
    getter = getattr(playlist, "tracks", None)
    if not callable(getter):
        return []
    try:
        return list(getter(limit=limit, offset=offset) or [])
    except TypeError:
        raw = list(getter() or [])
        return raw[offset : offset + limit]


def _indexed_display_row(track_data: dict, db: Any) -> dict | None:
    """ISRC → indexed library path. No artist walk and no filesystem stat."""
    from tidal_dl.helper.library_scanner import path_has_skipped_scan_dir

    isrc = str(track_data.get("isrc") or "").strip()
    if not isrc or not hasattr(db, "tracks_by_isrc"):
        return None
    rows = [dict(row) for row in (db.tracks_by_isrc(isrc) or []) if row]
    usable = [
        row for row in rows
        if row.get("path") and not path_has_skipped_scan_dir(str(row.get("path") or ""))
    ]
    if not usable:
        return None
    wanted = _normalize(str(track_data.get("name") or track_data.get("title") or ""))

    def _rank(row: dict) -> tuple:
        title = _normalize(str(row.get("title") or row.get("name") or ""))
        path = str(row.get("path") or "")
        return (0 if wanted and title == wanted else 1, len(path), path)

    usable.sort(key=_rank)
    return usable[0]


def _stamp_sql_only(tracks: list[dict], db: Any) -> list[dict]:
    """Identity match from SQLite only. No NAS/stat. First-page safe."""
    stamped: list[dict] = []
    for data in tracks:
        row = dict(data)
        local_row = _indexed_display_row(row, db)
        stamped.append(finish_stamp(stamp_track(row, local_row)))
    return stamped


def _stamp_honest(tracks: list[dict], db: Any) -> list[dict]:
    """Playability-honest stamp for sync / unpaginated reads."""
    from tidal_dl.helper.library_reconcile import present_playable_path

    stamped: list[dict] = []
    for data in tracks:
        row = dict(data)
        row["is_local"] = False
        row.pop("playable", None)
        row.pop("local_path", None)
        row.pop("path", None)
        local_row = _best_local_row(row, db)
        if local_row:
            served, ok = present_playable_path(indexed_path_for_row(local_row), db)
            if ok and served:
                local_row = {**local_row, "path": served}
            else:
                local_row = None
        stamped.append(finish_stamp(stamp_track(row, local_row)))
    return stamped


def _flatten_pages(pages: dict[int, list[dict]], total: int) -> list[dict]:
    ordered: list[dict] = []
    for offset in sorted(pages):
        ordered.extend(pages[offset])
    if total and len(ordered) > total:
        return ordered[:total]
    return ordered


def _cache_valid(entry: dict | None, last_updated: str | None, etag: str | None) -> bool:
    if not entry:
        return False
    if time.time() - float(entry.get("ts") or 0) > _CACHE_TTL:
        return False
    wanted = _normalize_updated(last_updated)
    stored = _normalize_updated(entry.get("last_updated"))
    if wanted and stored and wanted != stored:
        return False
    stored_etag = entry.get("etag")
    return not (etag and stored_etag and etag != stored_etag)


def _evict_cache() -> None:
    if len(_playlist_tracks_cache) <= _CACHE_MAX_PLAYLISTS:
        return
    try:
        oldest_id = min(_playlist_tracks_cache, key=lambda k: _playlist_tracks_cache[k]["ts"])
        del _playlist_tracks_cache[oldest_id]
        _playlist_meta_cache.pop(oldest_id, None)
    except KeyError:
        pass


def _store_cache(playlist_id: str, entry: dict) -> None:
    with _cache_lock:
        _playlist_tracks_cache[playlist_id] = entry
        _evict_cache()


def _mark(name: str, started: float) -> float:
    ms = (time.perf_counter() - started) * 1000
    _last_playlist_timings[name] = round(ms, 1)
    return ms


def _load_playlist_object(session, playlist_id: str, entry: dict | None):
    if entry and entry.get("source") is not None:
        return entry["source"]
    from tidal_dl.gui.api.settings import _is_tidal_unauthorized

    t0 = time.perf_counter()
    try:
        playlist = session.playlist(playlist_id)
    except HTTPException:
        raise
    except Exception as exc:
        if _is_tidal_unauthorized(exc):
            raise
        raise HTTPException(status_code=404, detail=f"Playlist not found: {exc}") from exc
    _mark("tidal_meta_ms", t0)
    return playlist


def _bounded_playlist_total(value: int | None) -> int:
    return max(0, min(int(value or 0), _PLAYLIST_TOTAL_CAP))


def _resolve_playlist_total(
    entry: dict,
    total_hint: int | None,
    playlist: Any | None,
) -> int:
    """Tidal num_tracks wins. Client total may fill a gap, never inflate it."""
    tidal_num = int(getattr(playlist, "num_tracks", 0) or 0) if playlist is not None else 0
    if tidal_num:
        return _bounded_playlist_total(tidal_num)
    current = _bounded_playlist_total(entry.get("total"))
    if current:
        return current
    return _bounded_playlist_total(total_hint)


def _missing_offsets(entry: dict, total: int, page_size: int) -> list[int]:
    pages = entry.get("pages") or {}
    bounded = _bounded_playlist_total(total)
    return [offset for offset in range(0, bounded, page_size) if offset not in pages]


def _fetch_pages(playlist: Any, offsets: list[int], page_size: int) -> dict[int, list[dict]]:
    fetched: dict[int, list[dict]] = {}
    if not offsets:
        return fetched

    from tidal_dl.download.api_pacing import shared_pacer

    pacer = shared_pacer()

    def _one(offset: int) -> tuple[int, list[dict]]:
        retries = 0
        while True:
            pacer.wait_before_api(enabled=pacer.rate_limit_hits > 0)
            try:
                t0 = time.perf_counter()
                raw = _call_tracks(playlist, limit=page_size, offset=offset)
                log.info(
                    "playlist_load stage=tidal_page offset=%s count=%s ms=%.1f",
                    offset,
                    len(raw),
                    (time.perf_counter() - t0) * 1000,
                )
                return offset, [_serialize_catalog_track(track) for track in raw]
            except Exception as exc:
                if not _too_many_requests(exc):
                    raise
                retries += 1
                wait = pacer.note_429(_retry_after_sec(exc))
                log.warning(
                    "playlist_load stage=tidal_429 offset=%s wait=%.1f retry=%s",
                    offset,
                    wait,
                    retries,
                )
                if retries > _PLAYLIST_429_RETRIES:
                    raise HTTPException(
                        status_code=429,
                        detail="Tidal rate limit; playlist tracks paused",
                    ) from exc
                time.sleep(wait)

    if len(offsets) == 1:
        offset, rows = _one(offsets[0])
        fetched[offset] = rows
        return fetched

    workers = min(_PLAYLIST_FETCH_CONCURRENCY, len(offsets))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset, rows in pool.map(_one, offsets):
            fetched[offset] = rows
    return fetched


def _ensure_pages(
    session,
    playlist_id: str,
    *,
    needed: list[int],
    last_updated: str | None,
    total_hint: int | None,
    page_size: int,
) -> dict:
    t_all = time.perf_counter()
    _last_playlist_timings.clear()
    _last_playlist_timings["playlist_id"] = playlist_id

    with _cache_lock:
        entry = _playlist_tracks_cache.get(playlist_id)

    if entry and not _cache_valid(entry, last_updated, None):
        entry = None
        with _cache_lock:
            _playlist_tracks_cache.pop(playlist_id, None)

    if entry is None:
        entry = {
            "ts": time.time(),
            "last_updated": _normalize_updated(last_updated),
            "etag": None,
            "total": _bounded_playlist_total(total_hint),
            "pages": {},
            "source": None,
        }

    pages = entry.setdefault("pages", {})
    missing = [offset for offset in needed if offset not in pages]
    playlist = entry.get("source")
    if missing or not entry.get("total"):
        if playlist is None:
            playlist = _load_playlist_object(session, playlist_id, entry)
            entry["source"] = playlist
            meta_updated = _normalize_updated(getattr(playlist, "last_updated", None))
            if meta_updated:
                if entry.get("last_updated") and meta_updated != entry["last_updated"]:
                    pages.clear()
                    missing = list(needed)
                entry["last_updated"] = meta_updated
            entry["etag"] = getattr(playlist, "_etag", None) or entry.get("etag")
            num = getattr(playlist, "num_tracks", 0) or 0
            if num:
                entry["total"] = _bounded_playlist_total(num)
            elif total_hint:
                entry["total"] = _bounded_playlist_total(total_hint)
        if missing:
            t_fetch = time.perf_counter()
            fetched = _fetch_pages(playlist, missing, page_size)
            _mark("tidal_pages_ms", t_fetch)
            pages.update(fetched)
            if not entry.get("total"):
                got = len(fetched.get(missing[0], [])) if missing else 0
                entry["total"] = missing[0] + got
                if got >= page_size:
                    entry["total"] = missing[0] + got + 1
    entry["total"] = _resolve_playlist_total(entry, total_hint, playlist)

    entry["ts"] = time.time()
    _store_cache(playlist_id, entry)
    _mark("ensure_pages_ms", t_all)
    _last_playlist_timings["tidal_page_count"] = len(needed)
    return entry


def _playlist_page_payload(
    session,
    playlist_id: str,
    *,
    limit: int,
    offset: int,
    last_updated: str | None,
    total_hint: int | None,
    honest: bool,
) -> dict:
    page_size = min(max(limit, 1), _PLAYLIST_PAGE_CAP)
    aligned = offset - (offset % page_size)
    t0 = time.perf_counter()
    entry = _ensure_pages(
        session,
        playlist_id,
        needed=[aligned],
        last_updated=last_updated,
        total_hint=total_hint,
        page_size=page_size,
    )
    catalog = list((entry.get("pages") or {}).get(aligned) or [])
    # Requested offset may sit inside a cached page.
    slice_start = max(0, offset - aligned)
    page = catalog[slice_start : slice_start + limit]
    total = int(entry.get("total") or (offset + len(page)))
    t_stamp = time.perf_counter()
    db = _get_playlist_db()
    try:
        tracks = _stamp_honest(page, db) if honest else _stamp_sql_only(page, db)
    finally:
        db.close()
    _mark("stamp_ms", t_stamp)
    _mark("total_ms", t0)
    log.info(
        "playlist_load id=%s limit=%s offset=%s returned=%s total=%s timings=%s",
        playlist_id,
        limit,
        offset,
        len(tracks),
        total,
        _last_playlist_timings,
    )
    return {
        "tracks": tracks,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(tracks) < total,
        "last_updated": entry.get("last_updated") or None,
        "etag": entry.get("etag"),
    }


def _playlist_full_payload(
    session,
    playlist_id: str,
    *,
    last_updated: str | None,
    total_hint: int | None,
    honest: bool,
) -> dict:
    t0 = time.perf_counter()
    entry = _ensure_pages(
        session,
        playlist_id,
        needed=[0],
        last_updated=last_updated,
        total_hint=total_hint,
        page_size=_PLAYLIST_PAGE_SIZE,
    )
    total = int(entry.get("total") or 0)
    if total <= 0:
        first = (entry.get("pages") or {}).get(0) or []
        total = len(first)
        if len(first) >= _PLAYLIST_PAGE_SIZE:
            playlist = _load_playlist_object(session, playlist_id, entry)
            entry["source"] = playlist
            num = getattr(playlist, "num_tracks", 0) or 0
            if num:
                total = int(num)
                entry["total"] = total
    missing = _missing_offsets(entry, total or 0, _PLAYLIST_PAGE_SIZE)
    if missing:
        playlist = _load_playlist_object(session, playlist_id, entry)
        entry["source"] = playlist
        if not total:
            total = int(getattr(playlist, "num_tracks", 0) or 0)
            entry["total"] = total
            missing = _missing_offsets(entry, total, _PLAYLIST_PAGE_SIZE)
        t_rest = time.perf_counter()
        fetched = _fetch_pages(playlist, missing, _PLAYLIST_PAGE_SIZE)
        _mark("tidal_remaining_ms", t_rest)
        entry.setdefault("pages", {}).update(fetched)
        # If Tidal reported a low num_tracks, keep walking while pages stay full.
        while True:
            pages = entry["pages"]
            ordered = _flatten_pages(pages, 0)
            last_off = max(pages) if pages else 0
            last_len = len(pages.get(last_off) or [])
            if last_len < _PLAYLIST_PAGE_SIZE:
                total = len(ordered)
                break
            next_off = last_off + _PLAYLIST_PAGE_SIZE
            if total and next_off >= total:
                break
            if next_off in pages:
                continue
            more = _fetch_pages(playlist, [next_off], _PLAYLIST_PAGE_SIZE)
            if not more.get(next_off):
                total = len(ordered)
                break
            pages.update(more)
            if total and next_off + _PLAYLIST_PAGE_SIZE >= total:
                break
        entry["total"] = total or len(_flatten_pages(entry["pages"], 0))
        entry["ts"] = time.time()
        _store_cache(playlist_id, entry)

    catalog = _flatten_pages(entry.get("pages") or {}, int(entry.get("total") or 0))
    t_stamp = time.perf_counter()
    db = _get_playlist_db()
    try:
        tracks = _stamp_honest(catalog, db) if honest else _stamp_sql_only(catalog, db)
    finally:
        db.close()
    _mark("stamp_ms", t_stamp)
    _mark("total_ms", t0)
    log.info(
        "playlist_load id=%s full returned=%s timings=%s",
        playlist_id,
        len(tracks),
        _last_playlist_timings,
    )
    return {
        "tracks": tracks,
        "total": len(tracks),
        "last_updated": entry.get("last_updated") or None,
        "etag": entry.get("etag"),
    }


def _serialize_playlist_tracks(session, playlist_id: str) -> list[dict]:
    return _playlist_full_payload(
        session, playlist_id, last_updated=None, total_hint=None, honest=True,
    )["tracks"]


def _playlist_tracks_data(session, playlist_id: str) -> dict:
    return _playlist_full_payload(
        session, playlist_id, last_updated=None, total_hint=None, honest=True,
    )


@router.get("/playlists")
def list_playlists() -> dict:
    """List user's Tidal playlists."""
    now = time.time()
    if _playlist_list_cache["data"] is not None and (now - _playlist_list_cache["ts"]) < _CACHE_TTL:
        return _playlist_list_cache["data"]

    from tidal_dl.gui.api.settings import call_tidal

    def _user_playlists():
        user = getattr(tidal.session, "user", None)
        if user is None:
            return []
        getter = getattr(user, "playlists", None)
        if not callable(getter):
            return []
        return getter() or []

    tidal = get_tidal()
    playlists = call_tidal(tidal, _user_playlists)

    # Use DB-cached playlist covers to survive server restarts
    db = _get_playlist_db()
    try:
        items = []
        for pl in playlists:
            pl_id = str(pl.id)
            cover = db.get_playlist_cover(pl_id)
            if cover is None:
                cover = _safe_image(pl)
                db.set_playlist_cover(pl_id, cover)
            items.append({
                "id": pl_id,
                "name": getattr(pl, "name", ""),
                "num_tracks": getattr(pl, "num_tracks", 0),
                "cover_url": cover,
                "last_updated": getattr(pl, "last_updated", None),
            })
        db.commit()
    finally:
        db.close()

    result = {"playlists": items}
    _playlist_list_cache["data"] = result
    _playlist_list_cache["ts"] = now
    return result


@router.get("/playlists/{playlist_id}/tracks")
def playlist_tracks(
    playlist_id: str,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    last_updated: Annotated[str | None, Query()] = None,
    total: Annotated[int | None, Query(ge=0, le=10_000)] = None,
) -> dict:
    """Get tracks for a specific playlist.

    Paginated reads (limit set) return the first rows quickly: one Tidal page,
    SQLite identity only, no NAS stats. Unpaginated reads (sync / compat)
    fetch remaining pages with a small concurrency limit and honesty-stamp.
    """
    from tidal_dl.gui.api.settings import call_tidal

    tidal = get_tidal()
    if limit is not None:
        return call_tidal(
            tidal,
            lambda: _playlist_page_payload(
                tidal.session,
                playlist_id,
                limit=limit,
                offset=offset,
                last_updated=last_updated,
                total_hint=total,
                honest=False,
            ),
        )
    return call_tidal(
        tidal,
        lambda: _playlist_full_payload(
            tidal.session,
            playlist_id,
            last_updated=last_updated,
            total_hint=total,
            honest=True,
        ),
    )


def _enqueue_playlist_downloads(track_ids: list[int], request: Request | None) -> dict:
    if request is None:
        return {"status": "queued", "count": len(track_ids)}
    return request.app.state.download_jobs.enqueue_download(track_ids)


@router.post("/playlists/{playlist_id}/sync")
def sync_playlist(playlist_id: str, request: Request = None) -> dict:
    """Trigger sync for a playlist — download tracks missing from the local library."""
    from tidal_dl.gui.api.settings import call_tidal

    tidal = get_tidal()
    tracks_data = call_tidal(
        tidal, lambda: _playlist_tracks_data(tidal.session, playlist_id)
    )["tracks"]
    missing_ids = [t["id"] for t in tracks_data if not t.get("is_local") and t.get("id")]
    total = len(tracks_data)

    # Invalidate tracks cache — after sync, local state changes so next load re-fetches.
    with _cache_lock:
        _playlist_tracks_cache.pop(playlist_id, None)
        _playlist_meta_cache.pop(playlist_id, None)

    if not missing_ids:
        return {"status": "up_to_date", "missing": 0, "total": total}

    _enqueue_playlist_downloads(missing_ids, request)

    return {"status": "syncing", "missing": len(missing_ids), "total": total}


def _safe_image(obj: Any) -> str:
    try:
        return obj.image(320)
    except Exception:  # noqa: BLE001
        return ""
