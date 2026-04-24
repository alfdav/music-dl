from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from tidal_dl.constants import QUALITY_STRING_TO_ENUM, TIER_RANK
from tidal_dl.helper.library_db import LibraryDB

logger = logging.getLogger("music-dl.upgrade")


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def tier_rank_for_quality(q: str | None, fmt: str | None = None) -> int:
    if not q:
        return 0

    lossy_formats = {"MP3", "AAC", "OGG", "M4A"}
    if fmt and fmt.upper() in lossy_formats:
        return 1

    rank = TIER_RANK.get(q.upper())
    if rank is not None:
        return rank

    match = re.match(r"(\d+)Hz/(\d+)bit", q, re.IGNORECASE)
    if match:
        sample_rate = int(match.group(1))
        bit_depth = int(match.group(2))
        if bit_depth >= 24 and sample_rate > 48000:
            return 4
        if bit_depth >= 24:
            return 3
        if bit_depth >= 16:
            return 2

    return 0


def trash_file(path: str) -> None:
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

    try:
        os.remove(path)
    except OSError:
        logger.warning("Failed to delete old file: %s", path)


def cleanup_replaced_track_files(
    db: LibraryDB, *, old_path: str, new_path: str
) -> list[str]:
    removed: list[str] = []
    seen: set[str] = set()
    new_path = str(new_path)

    def queue(path: str | None) -> None:
        if not path or path == new_path or path in seen:
            return
        seen.add(path)
        removed.append(path)

    old_row = db.get(old_path) if old_path else None
    queue(old_path)

    isrc = old_row.get("isrc") if old_row else None
    old_album = old_row.get("album") if old_row else None
    old_dir = str(Path(old_path).parent) if old_path else None
    if isrc:
        for row in db.tracks_by_isrc(isrc):
            candidate = row.get("path")
            if not candidate:
                continue
            same_album = old_album and row.get("album") == old_album
            same_dir = old_dir and str(Path(candidate).parent) == old_dir
            if same_album and same_dir:
                queue(candidate)

    for stale_path in removed:
        trash_file(stale_path)
        if db.get(stale_path):
            db.remove(stale_path)

    return removed


def resolve_tidal_album(
    session: Any, album_name: str, artist_hint: str, isrcs: list[str]
) -> tuple[Any, list] | tuple[None, list]:
    from tidalapi.album import Album

    norm_album = norm(album_name)
    isrc_set = {isrc.upper() for isrc in isrcs if isrc}
    if not norm_album or not isrc_set:
        return None, []

    try:
        query = f"{album_name} {artist_hint}".strip()
        results = session.search(query, models=[Album], limit=10)
        albums = results.get("albums", []) if isinstance(results, dict) else []
        if not albums:
            albums = getattr(results, "albums", []) or []
    except Exception:
        logger.exception("Album search failed for %r", album_name)
        return None, []

    for candidate in albums:
        candidate_name = norm(getattr(candidate, "name", "") or "")
        if candidate_name != norm_album:
            continue

        try:
            album_tracks = []
            if hasattr(candidate, "tracks"):
                album_tracks = candidate.tracks() or []
            if not album_tracks and hasattr(candidate, "items"):
                album_tracks = candidate.items() or []
            if not album_tracks:
                continue

            for track in album_tracks:
                track_isrc = getattr(track, "isrc", None)
                if track_isrc and track_isrc.upper() in isrc_set:
                    return candidate, album_tracks

        except Exception:
            logger.debug("Failed to fetch tracks for album %s", getattr(candidate, "id", "?"))
            continue

        time.sleep(2)

    return None, []
