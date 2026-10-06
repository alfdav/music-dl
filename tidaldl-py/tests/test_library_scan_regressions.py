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
    lib, root, tmp_path = library_scan_env
    nfc_album = unicodedata.normalize("NFC", "Café Album")
    nfd_album = unicodedata.normalize("NFD", nfc_album)
    db = open_db(tmp_path)
    for index in range(1, 4):
        name = f"0{index} Canción {index}.wav"
        DURATIONS[unicodedata.normalize("NFD", name)] = 10 + index
        on_disk = root / "Artista" / nfd_album / unicodedata.normalize("NFD", name)
        write_wav(on_disk, 10 + index)
        db.record(
            str(on_disk),
            status="tagged",
            artist=on_disk.parts[-3],
            title=on_disk.stem,
            album=on_disk.parts[-2],
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
    assert len(rows) == 3
    assert all(row["missing_since"] is None for row in rows.values())
    assert all(path == unicodedata.normalize("NFC", path) for path in rows)


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


def test_linux_nfd_named_new_file_is_stored_under_nfc_path(library_scan_env, monkeypatch):
    """Byte-exact filesystems keep the NFC spelling the walk folded to.

    macOS lookups are normalization-insensitive, so this only describes a
    Linux walk that opens the folded string.
    """
    import tidal_dl.gui.api.library as lib_mod

    lib, root, tmp_path = library_scan_env
    nfd = "Cafe\u0301"
    write_wav(root / "Artist" / nfd / "01 Song.wav", 5)
    monkeypatch.setattr(lib_mod, "_read_metadata", fake_metadata)
    lib._scan_running = True
    lib._background_scan(False)
    (path,) = rows_by_path(tmp_path)
    db = open_db(tmp_path)
    status = db.get(path)["status"]
    db.close()
    assert not Path(path).exists() and status == "unreadable"
