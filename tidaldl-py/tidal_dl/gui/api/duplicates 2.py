"""Duplicate detection, cleanup, and undo for the local music library."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from tidal_dl.gui.api.upgrade import _tier_rank_for_quality
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

router = APIRouter()
logger = logging.getLogger("music-dl.duplicates")

_TIER_NAMES = {4: "Legendary", 3: "Epic", 2: "Rare", 1: "Uncommon", 0: "Common"}
_LOCK_FILENAME = "cleanup.lock"
_MANIFEST_FILENAME = "manifest.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db() -> LibraryDB:
    """Open and return a LibraryDB connection."""
    db = LibraryDB(Path(path_config_base()) / "library.db")
    db.open()
    return db


def _staging_base() -> Path:
    return Path(path_config_base()) / "undo-staging"


def _lock_path() -> Path:
    return Path(path_config_base()) / _LOCK_FILENAME


def _is_cleanup_running() -> bool:
    """Check file-based lock. Stale locks (>10 min) are auto-cleared."""
    lp = _lock_path()
    if not lp.exists():
        return False
    try:
        age = time.time() - lp.stat().st_mtime
        if age > 600:  # 10 min = definitely stale
            lp.unlink(missing_ok=True)
            logger.warning("Cleared stale cleanup lock (age %.0fs)", age)
            return False
        return True
    except OSError:
        return False


def _acquire_lock() -> None:
    _lock_path().write_text(str(os.getpid()))


def _release_lock() -> None:
    _lock_path().unlink(missing_ok=True)


def _write_manifest(staging_dir: Path, moved_files: list[dict], expires_at: float) -> None:
    """Persist undo manifest to disk alongside staged files."""
    manifest = {
        "staging_path": str(staging_dir),
        "moved_files": moved_files,
        "expires_at": expires_at,
    }
    (staging_dir / _MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2))


def _read_manifest(staging_dir: Path) -> dict | None:
    """Read manifest from a staging dir. Returns None if missing/corrupt."""
    mf = staging_dir / _MANIFEST_FILENAME
    if not mf.exists():
        return None
    try:
        return json.loads(mf.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _find_active_manifest() -> dict | None:
    """Find the most recent non-expired staging manifest (survives crash)."""
    base = _staging_base()
    if not base.exists():
        return None
    best: dict | None = None
    best_ts = 0
    for d in base.iterdir():
        if not d.is_dir():
            continue
        try:
            ts = int(d.name)
        except ValueError:
            continue
        manifest = _read_manifest(d)
        if manifest and manifest.get("expires_at", 0) > time.time() and ts > best_ts:
            best = manifest
            best_ts = ts
    return best


def _path_score(path: str) -> int:
    """Lower score = more canonical. Higher = more likely duplicate."""
    score = 0
    p = path.lower()
    if "#recycle" in p:
        score += 100
    if "- playlists" in p or "/playlists/" in p:
        score += 50
    if re.search(r'_\d{2}\.\w+$', p):
        score += 30
    score += p.count("/")
    return score


def _normalize(s: str) -> str:
    """Normalize a string for fuzzy matching."""
    return " ".join(s.lower().strip().split())


def _reachable_scan_dirs() -> list[Path]:
    from tidal_dl.gui.api.library import _scan_directories

    return [d for d in _scan_directories() if d.exists()]


def _prune_stale(db: LibraryDB, reachable_dirs: list[Path]) -> int:
    """Remove DB entries for files that no longer exist on disk."""
    if not reachable_dirs:
        return 0
    assert db._conn
    rows = db._conn.execute(
        "SELECT path FROM scanned WHERE status != 'unreadable'"
    ).fetchall()
    pruned = 0
    for row in rows:
        p = row["path"]
        under_reachable = any(
            p.startswith(str(d) + "/") or p.startswith(str(d) + os.sep)
            for d in reachable_dirs
        )
        if not under_reachable:
            continue
        if not os.path.exists(p):
            db.remove(p)
            pruned += 1
    if pruned:
        db.commit()
    return pruned


def _find_duplicate_groups(db: LibraryDB) -> list[dict]:
    """Two-phase duplicate grouping: ISRC+album, then title+artist fallback."""
    assert db._conn
    groups: list[dict] = []
    seen_paths: set[str] = set()

    # Phase 1: ISRC + album grouping
    isrc_groups = db._conn.execute(
        """SELECT isrc, COALESCE(album, '') as album_key, COUNT(*) as cnt
           FROM scanned
           WHERE isrc IS NOT NULL AND isrc != '' AND status != 'unreadable'
           GROUP BY isrc, album_key HAVING cnt > 1"""
    ).fetchall()

    for g in isrc_groups:
        rows = db._conn.execute(
            """SELECT * FROM scanned
               WHERE isrc = ? AND COALESCE(album, '') = ? AND status != 'unreadable'""",
            (g["isrc"], g["album_key"]),
        ).fetchall()
        tracks = [dict(r) for r in rows]
        if len(tracks) < 2:
            continue

        # Rank: best quality first, then most canonical path, then shortest path
        tracks.sort(
            key=lambda t: (
                -_tier_rank_for_quality(t.get("quality"), t.get("format")),
                _path_score(t["path"]),
                len(t["path"]),
            )
        )

        keeper = tracks[0]
        duplicates = tracks[1:]

        keeper_rank = _tier_rank_for_quality(keeper.get("quality"), keeper.get("format"))
        groups.append({
            "key": f"isrc:{g['isrc']}|{g['album_key']}",
            "keeper": {
                "path": keeper["path"],
                "quality": keeper.get("quality"),
                "format": keeper.get("format"),
                "tier": _TIER_NAMES.get(keeper_rank, "Common"),
            },
            "duplicates": [
                {
                    "path": d["path"],
                    "quality": d.get("quality"),
                    "format": d.get("format"),
                    "tier": _TIER_NAMES.get(
                        _tier_rank_for_quality(d.get("quality"), d.get("format")),
                        "Common",
                    ),
                }
                for d in duplicates
            ],
        })
        for t in tracks:
            seen_paths.add(t["path"])

    # Phase 2: title+artist fallback for ISRC-less tracks
    no_isrc_rows = db._conn.execute(
        """SELECT * FROM scanned
           WHERE (isrc IS NULL OR isrc = '') AND status != 'unreadable'"""
    ).fetchall()

    # Group by normalized (title, artist)
    meta_groups: dict[tuple[str, str], list[dict]] = {}
    for r in no_isrc_rows:
        d = dict(r)
        if d["path"] in seen_paths:
            continue
        title = _normalize(d.get("title") or "")
        artist = _normalize(d.get("artist") or "")
        if not title:
            continue
        key = (title, artist)
        meta_groups.setdefault(key, []).append(d)

    for (title, artist), tracks in meta_groups.items():
        if len(tracks) < 2:
            continue

        # Sub-group by duration with ±2s tolerance using sweep
        tracks.sort(key=lambda t: t.get("duration") or 0)
        duration_groups: list[list[dict]] = []
        current_group: list[dict] = [tracks[0]]

        for i in range(1, len(tracks)):
            cur_dur = tracks[i].get("duration") or 0
            group_dur = current_group[0].get("duration") or 0
            if cur_dur - group_dur <= 2:
                current_group.append(tracks[i])
            else:
                if len(current_group) >= 2:
                    duration_groups.append(current_group)
                current_group = [tracks[i]]
        if len(current_group) >= 2:
            duration_groups.append(current_group)

        for dg in duration_groups:
            dg.sort(
                key=lambda t: (
                    -_tier_rank_for_quality(t.get("quality"), t.get("format")),
                    _path_score(t["path"]),
                    len(t["path"]),
                )
            )
            keeper = dg[0]
            duplicates = dg[1:]
            keeper_rank = _tier_rank_for_quality(
                keeper.get("quality"), keeper.get("format")
            )
            groups.append({
                "key": f"meta:{title}|{artist}",
                "keeper": {
                    "path": keeper["path"],
                    "quality": keeper.get("quality"),
                    "format": keeper.get("format"),
                    "tier": _TIER_NAMES.get(keeper_rank, "Common"),
                },
                "duplicates": [
                    {
                        "path": d["path"],
                        "quality": d.get("quality"),
                        "format": d.get("format"),
                        "tier": _TIER_NAMES.get(
                            _tier_rank_for_quality(d.get("quality"), d.get("format")),
                            "Common",
                        ),
                    }
                    for d in duplicates
                ],
            })

    return groups


def _staging_dir(ts: int) -> Path:
    d = _staging_base() / str(ts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_old_staging() -> None:
    """Delete staging dirs whose manifest has expired (or has no manifest)."""
    base = _staging_base()
    if not base.exists():
        return
    now = time.time()
    for d in base.iterdir():
        if not d.is_dir():
            continue
        try:
            ts = int(d.name)
        except ValueError:
            continue
        manifest = _read_manifest(d)
        # No manifest = orphaned from a crash with no recovery possible, or very old
        if manifest is None and now - ts > 300:
            shutil.rmtree(d, ignore_errors=True)
        elif manifest and manifest.get("expires_at", 0) < now:
            shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _preview_sync() -> dict:
    """Scan library for duplicate tracks and return grouped results."""
    from tidal_dl.gui.api.library import _scan_running

    if _scan_running:
        raise HTTPException(status_code=409, detail="Library scan in progress")
    if _is_cleanup_running():
        raise HTTPException(status_code=409, detail="Cleanup already in progress")

    db = _get_db()
    try:
        reachable = _reachable_scan_dirs()
        stale_count = _prune_stale(db, reachable)
        groups = _find_duplicate_groups(db)
        total_duplicates = sum(len(g["duplicates"]) for g in groups)

        # Check if there's an active undo manifest (from this or a previous run)
        active_manifest = _find_active_manifest()

        return {
            "stale_count": stale_count,
            "groups": groups,
            "total_groups": len(groups),
            "total_duplicates": total_duplicates,
            "undo_available": active_manifest is not None,
        }
    finally:
        db.close()


@router.get("/duplicates/preview")
async def preview_duplicates() -> dict:
    return await asyncio.to_thread(_preview_sync)


def _clean_sync() -> dict:
    """Move duplicate files to staging and remove from DB."""
    from tidal_dl.gui.api.library import _scan_running

    if _scan_running:
        raise HTTPException(status_code=409, detail="Library scan in progress")
    if _is_cleanup_running():
        raise HTTPException(status_code=409, detail="Cleanup already in progress")

    _acquire_lock()
    db = _get_db()
    try:
        _cleanup_old_staging()

        reachable = _reachable_scan_dirs()
        stale_pruned = _prune_stale(db, reachable)
        groups = _find_duplicate_groups(db)

        ts = int(time.time())
        staging = _staging_dir(ts)
        moved_files: list[dict[str, Any]] = []

        for group in groups:
            for dup in group["duplicates"]:
                original_path = dup["path"]
                if not os.path.exists(original_path):
                    continue
                # Store full DB row before removal
                row = db.get(original_path)
                if not row:
                    continue
                staged_name = (
                    hashlib.md5(original_path.encode()).hexdigest()
                    + Path(original_path).suffix
                )
                staged_path = str(staging / staged_name)
                try:
                    shutil.move(original_path, staged_path)
                except OSError as exc:
                    logger.warning("Failed to stage %s: %s", original_path, exc)
                    continue
                moved_files.append({
                    "original": original_path,
                    "staged": staged_path,
                    "db_row": dict(row),
                })
                db.remove(original_path)

        db.commit()

        # Persist manifest to disk — survives crash
        expires_at = time.time() + 300
        _write_manifest(staging, moved_files, expires_at)

        return {
            "stale_pruned": stale_pruned,
            "groups_cleaned": len(groups),
            "duplicates_moved": len(moved_files),
            "undo_available": len(moved_files) > 0,
            "undo_expires_at": expires_at,
        }
    finally:
        _release_lock()
        db.close()


@router.post("/duplicates/clean")
async def clean_duplicates() -> dict:
    return await asyncio.to_thread(_clean_sync)


@router.post("/duplicates/undo")
def undo_cleanup() -> dict:
    """Restore files from the most recent cleanup (reads manifest from disk)."""
    manifest = _find_active_manifest()
    if not manifest:
        raise HTTPException(status_code=410, detail="No active undo — window expired or no cleanup found")
    if not manifest.get("moved_files"):
        raise HTTPException(status_code=404, detail="Nothing to undo")

    db = _get_db()
    try:
        restored = 0
        failed = 0
        errors: list[str] = []

        for entry in manifest["moved_files"]:
            original_path = entry["original"]
            staged_path = entry["staged"]
            row = entry["db_row"]

            try:
                os.makedirs(os.path.dirname(original_path), exist_ok=True)
                shutil.move(staged_path, original_path)
                db.record(
                    path=row["path"],
                    status=row["status"],
                    isrc=row.get("isrc"),
                    artist=row.get("artist"),
                    title=row.get("title"),
                    album=row.get("album"),
                    duration=row.get("duration"),
                    quality=row.get("quality"),
                    fmt=row.get("format"),
                    genre=row.get("genre"),
                )
                restored += 1
            except Exception as exc:
                failed += 1
                errors.append(f"{original_path}: {exc}")

        db.commit()

        # Remove the staging dir now that files are restored
        staging_path = manifest.get("staging_path")
        if staging_path:
            shutil.rmtree(staging_path, ignore_errors=True)

        return {"restored": restored, "failed": failed, "errors": errors}
    finally:
        db.close()
