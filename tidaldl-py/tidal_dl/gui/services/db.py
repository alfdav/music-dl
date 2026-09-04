"""Shared LibraryDB accessor for GUI API routes."""
from __future__ import annotations

import threading
from pathlib import Path

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

_db: LibraryDB | None = None  # Compatibility alias for tests/debugging.
_local = threading.local()
_generation = 0
_lock = threading.Lock()


def _close_thread_db() -> None:
    db = getattr(_local, "db", None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
    _local.db = None
    _local.generation = -1


def _invalidate_db_cache() -> None:
    global _db, _generation
    _close_thread_db()
    _db = None
    with _lock:
        _generation += 1


def get_library_db() -> LibraryDB:
    global _db
    db_path = Path(path_config_base()) / "library.db"
    db = getattr(_local, "db", None)
    generation = getattr(_local, "generation", -1)

    if db is not None and (generation != _generation or db._path != db_path):
        _close_thread_db()
        db = None

    if db is None:
        db = LibraryDB(db_path)
        db.open()
        db.import_legacy_isrc_index(Path(path_config_base()) / "isrc_index.json")
        _local.db = db
        _local.generation = _generation
        _db = db

    from tidal_dl.helper.library_scanner import purge_skipped_library_rows

    purge_skipped_library_rows(db)
    return db
