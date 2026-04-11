"""Regression tests for thread-safe GUI DB access."""

from __future__ import annotations

import threading
from pathlib import Path

import tidal_dl.gui.api.home as home_api
import tidal_dl.gui.api.library as library_api
from tidal_dl.helper.library_db import LibraryDB


def _seed_library_db(base_dir: Path) -> None:
    db = LibraryDB(base_dir / "library.db")
    db.open()
    db.record(
        "/music/artist/album/track.flac",
        status="tagged",
        artist="Artist",
        album="Album",
        title="Track",
    )
    db.record_download(
        track_id=1,
        name="Track",
        artist="Artist",
        album="Album",
        status="done",
        finished_at=100.0,
    )
    db.commit()
    db.close()


def _reset_db_cache(module) -> None:
    invalidate = getattr(module, "_invalidate_db_cache", None)
    if callable(invalidate):
        invalidate()
        return

    if hasattr(module, "_db"):
        db = getattr(module, "_db")
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        module._db = None
    if hasattr(module, "_db_opened_at"):
        module._db_opened_at = 0


def _concurrent_get_db_error(module, query, attempts: int = 12):
    for _ in range(attempts):
        _reset_db_cache(module)
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                barrier.wait(timeout=5)
                db = module._get_db()
                query(db)
            except BaseException as exc:  # pragma: no cover - failure path only
                errors.append(exc)

        left = threading.Thread(target=worker)
        right = threading.Thread(target=worker)
        left.start()
        right.start()
        left.join()
        right.join()

        if errors:
            return errors[0]

    return None


def test_library_api_get_db_is_thread_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
    _seed_library_db(tmp_path)

    error = _concurrent_get_db_error(
        library_api,
        lambda db: db.recent_albums_page(limit=1, offset=0),
    )

    assert error is None, repr(error)


def test_home_api_get_db_is_thread_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(home_api, "path_config_base", lambda: str(tmp_path))
    _seed_library_db(tmp_path)

    error = _concurrent_get_db_error(home_api, lambda db: db.all_tracks())

    assert error is None, repr(error)


def test_library_api_invalidation_reopens_other_threads_on_next_access(tmp_path, monkeypatch):
    monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
    _seed_library_db(tmp_path)
    _reset_db_cache(library_api)

    first = library_api._get_db()

    invalidated = threading.Event()

    def invalidate_from_other_thread() -> None:
        library_api._invalidate_db_cache()
        invalidated.set()

    worker = threading.Thread(target=invalidate_from_other_thread)
    worker.start()
    worker.join()

    assert invalidated.is_set()

    second = library_api._get_db()

    assert second is not first
    assert first._conn is None
    assert second._conn is not None
    rows, total = second.recent_albums_page(limit=1, offset=0)
    assert total == 1
    assert rows[0]["album"] == "Album"
