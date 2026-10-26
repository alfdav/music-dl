"""Library scan and reconcile behaviour on a legacy-shaped database.

Legacy shape = rows with NULL file_size/file_inode, missing_since NULL,
empty scanned_dirs (a pre-identity database after the identity migration).
Paths are generic fakes under a temp music root.
"""

from __future__ import annotations

import inspect
import os
import shutil
import unicodedata
from pathlib import Path
from types import SimpleNamespace

from tests.library_scan_support import (
    DURATIONS,
    build_legacy_library,
    dir_count,
    fake_metadata,
    legacy_row,
    open_db,
    rows_by_path,
    skip_unless_chmod_blocks,
    write_wav,
)
from tidal_dl.helper.library_db import LibraryDB


def test_empty_scanned_dirs_never_reports_unchanged(library_scan_env):
    lib, root, tmp_path = library_scan_env
    build_legacy_library(root, tmp_path)
    db = open_db(tmp_path)
    assert db.dir_signatures() == {}
    assert lib._dir_signatures_unchanged(db, [root]) is False
    db.close()


def test_normal_scan_heals_marks_missing_and_indexes(library_scan_env):
    lib, root, tmp_path = library_scan_env
    lay = build_legacy_library(root, tmp_path)
    lib._scan_running = True
    lib._background_scan(False)
    assert lib._scan_progress["phase"] == "done", lib._scan_progress
    rows = rows_by_path(tmp_path)

    for old, new in zip(lay["layout_old"], lay["layout_new"]):
        assert str(old) not in rows and str(new) in rows
    for old, new in zip(lay["renamed_old"], lay["renamed_new"]):
        assert str(old) not in rows and str(new) in rows
    for old in lay["recycled_old"]:
        assert rows[str(old)]["missing_since"] is not None
    for path in lay["new"]:
        assert rows[str(path)]["file_size"] is not None
    assert dir_count(tmp_path) > 0


def test_path_reconcile_heals_and_backfills_live_rows(library_scan_env):
    lib, root, tmp_path = library_scan_env
    lay = build_legacy_library(root, tmp_path)
    lib._reconcile_running = True
    lib._background_path_reconcile()
    prog = lib._reconcile_progress
    assert prog["phase"] == "done" and prog["error"] is None, prog
    rows = rows_by_path(tmp_path)
    for old, new in zip(lay["layout_old"], lay["layout_new"]):
        assert str(old) not in rows and str(new) in rows
    for old, new in zip(lay["renamed_old"], lay["renamed_new"]):
        assert str(old) not in rows and str(new) in rows
    for old in lay["recycled_old"]:
        assert rows[str(old)]["missing_since"] is not None
        assert rows[str(old)]["file_size"] is None
    for path in lay["new"]:
        assert str(path) in rows
    unchanged = [rows[str(path)] for path in lay["unchanged"]]
    assert all(row["file_size"] is not None and row["file_inode"] is not None for row in unchanged)
    assert prog["total"] > 0 and prog["missing"] == 10
    assert dir_count(tmp_path) > 0


def test_reconcile_reports_total_0_when_share_not_mounted(library_scan_env, monkeypatch):
    lib, root, tmp_path = library_scan_env
    build_legacy_library(root, tmp_path)
    monkeypatch.setattr(lib, "_scan_directories", list)
    lib._reconcile_running = True
    lib._background_path_reconcile()
    prog = lib._reconcile_progress
    assert (prog["phase"], prog["total"], prog["missing"], prog["error"]) == ("done", 0, 0, None)
    assert dir_count(tmp_path) == 0
    assert all(row["missing_since"] is None for row in rows_by_path(tmp_path).values())


def test_nfd_disk_names_match_nfc_rows_in_normal_scan(library_scan_env):
    """An NFD file matches its NFC row, then the row keeps the on-disk spelling."""
    lib, root, tmp_path = library_scan_env
    nfc_album = unicodedata.normalize("NFC", "Café Album")
    nfd_album = unicodedata.normalize("NFD", nfc_album)
    on_disk_paths: list[str] = []
    db = open_db(tmp_path)
    for index in range(1, 4):
        name = f"0{index} Canción {index}.wav"
        nfd_name = unicodedata.normalize("NFD", name)
        DURATIONS[nfd_name] = 10 + index
        on_disk = root / "Artista" / nfd_album / nfd_name
        write_wav(on_disk, 10 + index)
        on_disk_paths.append(str(on_disk))
        nfc_path = str(root / "Artista" / nfc_album / unicodedata.normalize("NFC", name))
        db.record(
            nfc_path,
            status="tagged",
            artist=on_disk.parts[-3],
            title=Path(nfd_name).stem,
            album=nfc_album,
            duration=10 + index,
            quality="WAV",
            fmt="WAV",
            codec="pcm",
            metadata_complete=True,
        )
    db.commit()
    db.close()
    lib._scan_running = True
    lib._background_scan(False)
    rows = rows_by_path(tmp_path)
    assert set(rows) == set(on_disk_paths)
    assert all(row["missing_since"] is None for row in rows.values())
    assert all(Path(path).exists() for path in rows)


def test_normal_scan_indexes_compatibility_character_folder(library_scan_env):
    lib, root, tmp_path = library_scan_env
    odd = root / "Artist F" / "Album\u2026"
    write_wav(odd / "01 Odd.wav", 5)
    lib._scan_running = True
    lib._background_scan(False)
    assert str(odd / "01 Odd.wav") in rows_by_path(tmp_path)


def test_migration_adds_identity_columns_without_backfill(tmp_path):
    import sqlite3

    db_path = tmp_path / "library.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE scanned (path TEXT PRIMARY KEY, status TEXT NOT NULL, scanned_at INTEGER NOT NULL)"
    )
    conn.execute("INSERT INTO scanned VALUES ('/music/Artist/Album/01 Song.flac', 'tagged', 1)")
    conn.execute("PRAGMA user_version = 9")
    conn.commit()
    conn.close()
    db = LibraryDB(db_path)
    db.open()
    row = db.get("/music/Artist/Album/01 Song.flac")
    assert row["file_size"] is None and row["missing_since"] is None
    assert db.dir_signatures() == {}
    db.close()


def test_startup_and_focus_only_request_path_reconcile():
    from tidal_dl import gui

    src = inspect.getsource(gui)
    assert "request_path_reconcile" in src
    assert "_background_scan" not in src and "scan_library" not in src
    views = (Path(gui.__file__).parent / "static" / "views.js").read_text()
    assert views.count("triggerScan(navSyncBtn") == 1


def test_unmounted_share_never_prunes(library_scan_env, monkeypatch):
    lib, root, tmp_path = library_scan_env
    build_legacy_library(root, tmp_path)
    monkeypatch.setattr(lib, "_scan_directories", list)
    lib._scan_running = True
    lib._background_scan(False)
    rows = rows_by_path(tmp_path)
    assert len(rows) == 150 and all(row["missing_since"] is None for row in rows.values())


def test_empty_mounted_share_never_prunes(library_scan_env):
    lib, root, tmp_path = library_scan_env
    build_legacy_library(root, tmp_path)
    for child in root.iterdir():
        shutil.rmtree(child)
    lib._scan_running = True
    lib._background_scan(False)
    lib._reconcile_running = True
    lib._background_path_reconcile()
    rows = rows_by_path(tmp_path)
    assert len(rows) == 150 and all(row["missing_since"] is None for row in rows.values())


def test_reconcile_indexes_folder_with_compatibility_character(library_scan_env):
    lib, root, tmp_path = library_scan_env
    build_legacy_library(root, tmp_path)
    odd = root / "Artist F" / "Album\u2026"
    for index in range(1, 4):
        DURATIONS[f"0{index} Odd {index}.wav"] = 900 + index
        write_wav(odd / f"0{index} Odd {index}.wav", 900 + index)
    lib._reconcile_running = True
    lib._background_path_reconcile()
    rows = rows_by_path(tmp_path)
    assert all(str(odd / f"0{index} Odd {index}.wav") in rows for index in range(1, 4))
    db = open_db(tmp_path)
    assert lib._dir_signatures_unchanged(db, [root]) is True
    db.close()


def test_reconcile_works_when_root_name_has_compatibility_character(library_scan_env, monkeypatch, tmp_path):
    lib, _root, _ = library_scan_env
    root = tmp_path / "Music\u2026"
    root.mkdir()

    class FakeSettings:
        data = SimpleNamespace(download_base_path=str(root), scan_paths="")

    monkeypatch.setattr(lib, "Settings", FakeSettings)
    lay = build_legacy_library(root, tmp_path)
    lib._reconcile_running = True
    lib._background_path_reconcile()
    rows = rows_by_path(tmp_path)
    assert all(rows[str(path)]["missing_since"] is not None for path in lay["recycled_old"])
    assert all(str(path) in rows for path in lay["layout_new"] + lay["new"])
    assert dir_count(tmp_path) > 0


@skip_unless_chmod_blocks
def test_unreadable_root_reports_error_and_keeps_db(library_scan_env, chmod_restore):
    lib, root, tmp_path = library_scan_env
    build_legacy_library(root, tmp_path)
    os.chmod(root, 0)
    chmod_restore.append(root)
    lib._scan_running = True
    lib._background_scan(False)
    assert lib._scan_progress["phase"] == "error"
    assert "not readable" in (lib._scan_progress["error"] or "")
    lib._reconcile_running = True
    lib._background_path_reconcile()
    assert lib._reconcile_progress["phase"] == "error"
    assert "not readable" in (lib._reconcile_progress["error"] or "")
    os.chmod(root, 0o755)
    rows = rows_by_path(tmp_path)
    assert len(rows) == 150 and all(row["missing_since"] is None for row in rows.values())
    assert dir_count(tmp_path) == 0


@skip_unless_chmod_blocks
def test_unreadable_subfolder_is_not_marked_missing(library_scan_env, chmod_restore):
    lib, root, tmp_path = library_scan_env
    lay = build_legacy_library(root, tmp_path)
    locked = root / "Artist 0" / "Album 0"
    os.chmod(locked, 0)
    chmod_restore.append(locked)
    lib._scan_running = True
    lib._background_scan(False)
    os.chmod(locked, 0o755)
    rows = rows_by_path(tmp_path)
    assert all(rows[str(path)]["missing_since"] is None for path in lay["unchanged"])
    assert all(rows[str(path)]["missing_since"] is not None for path in lay["recycled_old"])


def test_rescan_marks_vanished_rows_missing(library_scan_env):
    lib, root, tmp_path = library_scan_env
    lay = build_legacy_library(root, tmp_path)
    lib._scan_running = True
    lib._background_scan(True)
    rows = rows_by_path(tmp_path)
    assert all(rows[str(path)]["missing_since"] is not None for path in lay["recycled_old"])
    assert all(rows[str(path)]["file_size"] is not None for path in lay["unchanged"])


def test_rescan_on_empty_share_never_prunes(library_scan_env):
    lib, root, tmp_path = library_scan_env
    build_legacy_library(root, tmp_path)
    for child in root.iterdir():
        shutil.rmtree(child)
    lib._scan_running = True
    lib._background_scan(True)
    rows = rows_by_path(tmp_path)
    assert len(rows) == 150 and all(row["missing_since"] is None for row in rows.values())


def test_normal_scan_backfills_identity_for_live_legacy_rows(library_scan_env):
    lib, root, tmp_path = library_scan_env
    lay = build_legacy_library(root, tmp_path)
    lib._scan_running = True
    lib._background_scan(False)
    rows = rows_by_path(tmp_path)
    assert all(rows[str(path)]["file_size"] is not None for path in lay["unchanged"])
    assert all(rows[str(path)]["file_inode"] is not None for path in lay["unchanged"])
    assert all(rows[str(path)]["file_size"] is None for path in lay["recycled_old"])


def test_download_registration_records_identity(library_scan_env, monkeypatch):
    _lib, root, tmp_path = library_scan_env
    from tidal_dl.download import registry

    monkeypatch.setattr(registry, "path_config_base", lambda: str(tmp_path))
    path = root / "Artist" / "Album" / "01 Song.wav"
    write_wav(path, 10)
    registry.register_downloaded_track(path)
    row = rows_by_path(tmp_path)[str(path)]
    assert row["file_size"] == path.stat().st_size and row["file_inode"] is not None


def test_under_any_dir_is_separator_agnostic_and_path_aware():
    """Unreadable-dir prune must keep the album and spare the sibling name."""
    from tidal_dl.gui.api.library import _under_any_dir

    slash_album = {"/music/Album 1"}
    assert _under_any_dir("/music/Album 1/01 Song.flac", slash_album) is True
    assert _under_any_dir("/music/Album 1", slash_album) is True
    assert _under_any_dir("/music/Album 10/01 Song.flac", slash_album) is False
    assert _under_any_dir("/music/Album 10", slash_album) is False

    windows_album = {r"C:\music\Album 1"}
    assert _under_any_dir(r"C:\music\Album 1\01 Song.flac", windows_album) is True
    assert _under_any_dir(r"C:\music\Album 1", windows_album) is True
    assert _under_any_dir(r"C:\music\Album 10\01 Song.flac", windows_album) is False
    assert _under_any_dir("/music/Album 1/01 Song.flac", {r"\music\Album 1"}) is True
    assert _under_any_dir(r"\music\Album 10\01 Song.flac", {"/music/Album 1"}) is False
    assert _under_any_dir("/music/Album 1/01 Song.flac", set()) is False


def test_discovery_oserror_does_not_mark_existing_row_missing(library_scan_env, monkeypatch):
    """A file whose lstat fails stays put, and is not indexed as a new row."""
    import pathlib

    lib, root, tmp_path = library_scan_env
    existing = root / "Artist" / "Album" / "01 Kept.wav"
    healthy = root / "Artist" / "Album" / "02 Healthy.wav"
    unseen = root / "Artist" / "Album" / "03 Unseen.wav"
    write_wav(existing, 8)
    write_wav(healthy, 8)
    write_wav(unseen, 8)
    DURATIONS[existing.name] = 8
    DURATIONS[healthy.name] = 8
    DURATIONS[unseen.name] = 8
    db = open_db(tmp_path)
    legacy_row(db, existing, 8)
    db.commit()
    db.close()

    real_lstat = pathlib.Path.lstat

    def flaky_lstat(self, *args, **kwargs):
        if self.name in {"01 Kept.wav", "03 Unseen.wav"}:
            raise OSError("lstat failed")
        return real_lstat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "lstat", flaky_lstat)

    def run(rescan: bool) -> None:
        lib._scan_running = True
        lib._background_scan(rescan)
        assert lib._scan_progress["phase"] == "done", lib._scan_progress
        assert lib._scan_progress["error"] is None
        db = open_db(tmp_path)
        kept = db.get(str(existing))
        fresh = db.get(str(unseen))
        good = db.get(str(healthy))
        db.close()
        assert kept is not None and kept["missing_since"] is None
        assert fresh is None
        assert good is not None and good["missing_since"] is None

    run(False)
    run(True)


def test_rescan_heals_renamed_folder(library_scan_env):
    """rescan=true migrates a renamed folder before it re-reads the file."""
    lib, root, tmp_path = library_scan_env
    old_dir = root / "Artist" / "Old Album"
    track = old_dir / "01 Song.wav"
    write_wav(track, 12)
    DURATIONS[track.name] = 12
    lib._scan_running = True
    lib._background_scan(False)
    assert lib._scan_progress["phase"] == "done", lib._scan_progress

    db = open_db(tmp_path)
    stored = db.get(str(track))
    assert stored is not None
    db._conn.execute(
        "UPDATE scanned SET play_count = 4 WHERE path = ?",
        (stored["path"],),
    )
    db.commit()
    db.close()

    new_dir = root / "Artist" / "New Album"
    old_dir.rename(new_dir)
    moved = new_dir / track.name
    lib._scan_running = True
    lib._background_scan(True)
    assert lib._scan_progress["phase"] == "done", lib._scan_progress
    assert lib._scan_progress["error"] is None

    db = open_db(tmp_path)
    old = db.get(str(track))
    new = db.get(str(moved))
    rows = db.identity_rows()
    db.close()
    assert old is None
    assert new is not None
    assert new["missing_since"] is None
    assert new["play_count"] == 4
    assert len(rows) == 1
    assert all(row["missing_since"] is None for row in rows)


def _scan_snapshot(tmp_path: Path) -> tuple:
    db = open_db(tmp_path)
    rows = tuple(sorted(
        (
            row["path"],
            row["missing_since"],
            row["file_size"],
            row["file_mtime"],
            row["file_inode"],
            row["file_device"],
        )
        for row in db.identity_rows()
    ))
    signatures = tuple(sorted(db.dir_signatures().items()))
    db.close()
    return rows, signatures


@skip_unless_chmod_blocks
def test_reconcile_unlistable_root_writes_nothing(library_scan_env, monkeypatch, chmod_restore):
    """One unlistable root aborts reconcile before any other root is written."""
    lib, _root, tmp_path = library_scan_env
    readable = tmp_path / "library-a"
    locked = tmp_path / "library-b"
    live = readable / "Artist" / "Album" / "01 Live.wav"
    gone = readable / "Artist" / "Album" / "02 Gone.wav"
    new = readable / "Artist" / "Album" / "03 New.wav"
    hidden = locked / "Artist" / "Album" / "01 Hidden.wav"
    write_wav(live, 8)
    write_wav(gone, 8)
    write_wav(new, 8)
    write_wav(hidden, 8)
    db = open_db(tmp_path)
    for path, duration in ((live, 8), (gone, 9), (hidden, 8)):
        legacy_row(db, path, duration)
    db.commit()
    db.close()
    gone.unlink()

    class FakeSettings:
        data = SimpleNamespace(download_base_path=str(readable), scan_paths=str(locked))

    monkeypatch.setattr(lib, "Settings", FakeSettings)
    os.chmod(locked, 0)
    chmod_restore.append(locked)
    before = _scan_snapshot(tmp_path)
    assert len(before[0]) == 3
    assert before[1] == ()
    assert all(row[1] is None and row[2] is None for row in before[0])

    lib._reconcile_running = True
    lib._background_path_reconcile()
    progress = lib._reconcile_progress
    assert progress["phase"] == "error", progress
    assert progress["error"] == "Library folder is not readable — library kept"
    assert _scan_snapshot(tmp_path) == before


def test_linux_nfd_named_new_file_is_stored_under_nfc_path(library_scan_env, monkeypatch):
    """The row stores the on-disk walk string and the metadata read from it.

    The canonical key stays NFC for matching. On a byte-exact filesystem that
    string is the NFD name ``os.walk`` returned, and that path is what opens.
    """
    import tidal_dl.gui.api.library as lib_mod

    lib, root, tmp_path = library_scan_env
    nfd = "Cafe\u0301"
    on_disk = root / "Artist" / nfd / "01 Song.wav"
    write_wav(on_disk, 5)
    monkeypatch.setattr(lib_mod, "_read_metadata", fake_metadata)
    lib._scan_running = True
    lib._background_scan(False)
    rows = rows_by_path(tmp_path)
    assert len(rows) == 1
    (path, row) = next(iter(rows.items()))
    assert path == str(on_disk)
    assert Path(path).exists()
    db = open_db(tmp_path)
    stored = db.get(path)
    db.close()
    assert stored["status"] != "unreadable"
    assert stored["artist"] == "Artist"
    assert stored["album"] == nfd
    assert stored["title"] == "01 Song"
    assert stored["file_inode"] is not None
    assert row["file_inode"] is not None
