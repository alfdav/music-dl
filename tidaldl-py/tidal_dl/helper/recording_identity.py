"""Same-folder recording identity for upgrade and re-download.

A recording is identified by ISRC and/or a live path. Filename templates and
numbered CD-rip prefixes are not identity. When those spellings differ, skip
or replace the live file — never write a second copy in the same album folder.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from tidal_dl.helper.library_scanner import (
    SCAN_EXTENSIONS,
    path_has_skipped_scan_dir,
)

if TYPE_CHECKING:
    from tidal_dl.helper.library_db import LibraryDB

logger = logging.getLogger("music-dl.identity")

ExtractIsrc = Callable[[Path], str | None]


def extract_audio_isrc(path: Path) -> str | None:
    from tidal_dl.helper.library_scanner import _extract_isrc

    try:
        return _extract_isrc(path)
    except Exception:  # noqa: BLE001
        return None


def _norm_isrc(isrc: str | None) -> str:
    return (isrc or "").strip().upper()


def _resolved_file(path: Path | str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    try:
        if candidate.is_file():
            return candidate.resolve()
    except OSError:
        return None
    return None


def _isrc_rows(db: LibraryDB, isrc: str) -> list[dict]:
    try:
        return db.tracks_by_isrc(isrc, include_missing=True)
    except TypeError:
        return db.tracks_by_isrc(isrc)


def playable_library_row_for_isrc(db: LibraryDB | None, isrc: str | None) -> dict | None:
    """Return the row library lookup can play for *isrc*, or None.

    Search and playlist local resolution only accept an indexed live
    ``tracks_by_isrc`` row whose path is a real file and not under a
    skipped scan directory. Download skip / ``has_live_isrc`` / bot
    ``is_local`` must use this same gate so a tag-scan sibling cannot
    block a download the app cannot play.
    """
    if db is None or not isrc:
        return None
    try:
        rows = db.tracks_by_isrc(isrc)
    except TypeError:
        rows = db.tracks_by_isrc(isrc)
    for row in rows:
        path = (row or {}).get("path") or ""
        if path_has_skipped_scan_dir(path):
            continue
        if Path(path).is_file():
            return row
    return None


def live_identity_paths(
    *,
    isrc: str | None,
    directory: Path | str,
    db: LibraryDB | None = None,
    dest_path: Path | str | None = None,
    extract_isrc: ExtractIsrc | None = None,
) -> list[Path]:
    """Live files in *directory* that are the same recording as *isrc*."""
    directory = Path(directory)
    wanted = _norm_isrc(isrc)
    extract = extract_isrc or extract_audio_isrc
    found: dict[str, Path] = {}

    def add(path: Path | str | None) -> None:
        resolved = _resolved_file(path)
        if resolved is None:
            return
        try:
            if resolved.parent != directory.resolve():
                return
        except OSError:
            return
        if path_has_skipped_scan_dir(resolved):
            return
        found[str(resolved)] = resolved

    if dest_path:
        dest_file = _resolved_file(dest_path)
        dest_is_wanted = False
        if dest_file is not None and not wanted:
            dest_is_wanted = True
        elif dest_file is not None and db:
            dest_is_wanted = any(
                _resolved_file(row.get("path")) == dest_file for row in _isrc_rows(db, wanted)
            )
        if dest_file is not None and not dest_is_wanted and wanted:
            dest_is_wanted = _norm_isrc(extract(dest_file)) == wanted
        if dest_file is not None and dest_is_wanted:
            add(dest_file)

    if db and wanted:
        for row in _isrc_rows(db, wanted):
            add(row.get("path"))

    if wanted and directory.is_dir() and not path_has_skipped_scan_dir(directory / "_"):
        try:
            children = list(directory.iterdir())
        except OSError:
            children = []
        for child in children:
            try:
                if not child.is_file() or child.suffix.lower() not in SCAN_EXTENSIONS:
                    continue
            except OSError:
                continue
            if str(child.resolve()) in found:
                continue
            tagged = extract(child)
            if _norm_isrc(tagged) == wanted:
                add(child)

    return sorted(found.values(), key=lambda path: path.name.lower())


def collapse_folder_identity(
    db: LibraryDB,
    *,
    isrc: str | None,
    keep_path: Path | str,
    extra_paths: Iterable[Path | str] | None = None,
    extract_isrc: ExtractIsrc | None = None,
    trash: Callable[[str], None] | None = None,
) -> list[str]:
    """Remove same-folder identity copies, keeping *keep_path*."""
    keep = Path(keep_path)
    wanted = _norm_isrc(isrc)
    extra = [Path(path) for path in (extra_paths or []) if path]
    directories = {keep.parent}
    for path in extra:
        directories.add(path.parent)

    removed: list[str] = []
    seen: set[str] = set()

    def queue(path: Path | str | None) -> None:
        if not path:
            return
        raw = str(path)
        candidate = Path(raw)
        try:
            resolved = candidate.resolve()
            keep_key = str(keep.resolve()) if keep.exists() else str(keep)
            if str(resolved) == keep_key or raw == str(keep):
                return
        except OSError:
            resolved = candidate
            if raw == str(keep):
                return
        if raw in seen or str(resolved) in seen:
            return
        seen.add(raw)
        seen.add(str(resolved))
        removed.append(raw)

    for path in extra:
        queue(path)

    for directory in directories:
        if path_has_skipped_scan_dir(directory / "_"):
            continue
        for identity in live_identity_paths(
            isrc=wanted,
            directory=directory,
            db=db,
            dest_path=keep if directory == keep.parent else None,
            extract_isrc=extract_isrc,
        ):
            queue(identity)

    trash_fn = trash or _trash_file
    stale_rows = [path for path in removed if db.get(path)]
    for path in removed:
        trash_fn(path)
    if stale_rows:
        with db.write_transaction():
            for path in stale_rows:
                db.remove(path)
    return removed


def adopt_original_name(
    keep_path: Path | str,
    removed_paths: Iterable[str],
    db: LibraryDB | None = None,
    *,
    preferred: str | None = None,
    isrc: str | None = None,
) -> Path:
    """Rename *keep_path* onto a removed same-folder original when free.

    After a successful rename the ISRC/index row must follow the file.
    Collapse already deleted the original's row; dropping the keep row
    without migrating or re-registering leaves ``has_live_isrc`` false
    even though the recording is on disk.
    """
    keep = Path(keep_path)
    candidates: list[Path] = []
    if preferred:
        candidates.append(Path(preferred))
    for raw in removed_paths:
        original = Path(raw)
        if preferred and original == Path(preferred):
            continue
        candidates.append(original)

    for original in candidates:
        if not original.name or original == keep:
            continue
        if original.parent != keep.parent:
            continue
        if original.exists() or not keep.exists():
            continue
        try:
            keep.rename(original)
        except OSError:
            continue
        if db is not None:
            _index_adopted_path(db, keep, original, isrc)
        return original
    return keep


def _index_adopted_path(
    db: LibraryDB,
    old_path: Path,
    new_path: Path,
    isrc: str | None,
) -> None:
    """Keep a live ISRC/index row on the post-rename on-disk path."""
    old_str = str(old_path)
    new_str = str(new_path)
    old_row = None
    try:
        old_row = db.get(old_str)
    except Exception:  # noqa: BLE001
        old_row = None
    wanted = _norm_isrc(isrc) or _norm_isrc((old_row or {}).get("isrc"))

    if old_row is not None:
        try:
            if db.migrate_path(old_str, new_str):
                return
        except Exception:  # noqa: BLE001
            logger.debug("adopt migrate failed %s -> %s", old_str, new_str, exc_info=True)
        try:
            if db.get(old_str):
                db.remove(old_str)
        except Exception:  # noqa: BLE001
            logger.debug("adopt could not drop stale keep row %s", old_str)

    if not wanted:
        return
    try:
        db.register_isrc_path(wanted, new_path)
    except Exception:  # noqa: BLE001
        logger.debug("adopt could not re-register ISRC at %s", new_str)


def _trash_file(path: str) -> None:
    try:
        from tidal_dl.gui.services.upgrade_jobs import trash_file

        trash_file(path)
        return
    except Exception:  # noqa: BLE001
        logger.debug("upgrade trash_file unavailable for %s", path)
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to delete identity twin: %s", path)
