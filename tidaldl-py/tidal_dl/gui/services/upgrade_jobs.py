from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import time
from typing import Any

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.library_db.utils import _local_quality_rank

logger = logging.getLogger("music-dl.upgrade")


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def tier_rank_for_quality(
    q: str | None,
    fmt: str | None = None,
    codec: str | None = None,
) -> int:
    return _local_quality_rank(q, fmt, codec)


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
                check=False,
            )
            return
        except Exception:  # noqa: BLE001, S110
            pass

    try:
        os.remove(path)
    except OSError:
        logger.warning("Failed to delete old file: %s", path)


def cleanup_replaced_track_files(
    db: LibraryDB, *, old_path: str, new_path: str, isrc: str | None = None
) -> list[str]:
    from tidal_dl.helper.recording_identity import collapse_folder_identity

    old_row = db.get(old_path) if old_path else None
    resolved_isrc = isrc or (old_row.get("isrc") if old_row else None)
    extra = [old_path] if old_path else []
    return collapse_folder_identity(
        db,
        isrc=resolved_isrc,
        keep_path=new_path,
        extra_paths=extra,
        trash=trash_file,
    )


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

        except Exception:  # noqa: BLE001
            logger.debug("Failed to fetch tracks for album %s", getattr(candidate, "id", "?"))
            continue

        time.sleep(2)

    return None, []
