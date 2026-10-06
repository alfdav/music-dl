"""Signed int64 file identity for scans and reconciles.

macOS SMB shares can report st_ino >= 2**63. Those values must round-trip
through SQLite's signed INTEGER and still match after a move.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.library_scan_support import StatOverride, open_db, write_wav

_SIGNED_MIN = -1 << 63
_SIGNED_MAX = (1 << 63) - 1
HUGE_INODE = (1 << 63) + 5
MAX_U64 = (1 << 64) - 1
HUGE_DEVICE = (1 << 63) + 9


def test_sqlite_int64_folds_unsigned_64_bit_values():
    from tidal_dl.helper.library_db.utils import sqlite_int64

    assert sqlite_int64(0) == 0
    assert sqlite_int64((1 << 63) - 1) == (1 << 63) - 1
    assert sqlite_int64(1 << 63) == _SIGNED_MIN
    assert sqlite_int64(HUGE_INODE) == HUGE_INODE - (1 << 64)
    assert sqlite_int64(MAX_U64) == -1
    assert sqlite_int64(-1) == -1
    assert sqlite_int64(_SIGNED_MIN) == _SIGNED_MIN
    assert sqlite_int64(None) is None
    # Outside one 64-bit window: keep the low 64 bits, never raise.
    assert sqlite_int64(1 << 64) == 0
    assert sqlite_int64((1 << 64) + 5) == 5
    assert sqlite_int64(_SIGNED_MIN - 1) == (1 << 63) - 1
    assert sqlite_int64("nope") is None  # type: ignore[arg-type]
    folded = sqlite_int64(HUGE_INODE)
    assert sqlite_int64(folded) == folded
    assert _SIGNED_MIN <= folded <= _SIGNED_MAX


def _patch_audio_stat(monkeypatch, mapping: dict[str, tuple[int, int] | BaseException]):
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        name = Path(os.fspath(path)).name
        spec = mapping.get(name)
        if isinstance(spec, BaseException):
            raise spec
        result = real_stat(path, *args, **kwargs)
        if spec is None:
            return result
        inode, device = spec
        return StatOverride(result, inode=inode, device=device)

    monkeypatch.setattr(os, "stat", fake_stat)


def _assert_signed_inode(stored: int, raw: int) -> None:
    from tidal_dl.helper.library_db.utils import sqlite_int64

    assert stored == sqlite_int64(raw)
    assert isinstance(stored, int)
    assert _SIGNED_MIN <= stored <= _SIGNED_MAX


def test_scan_and_reconcile_store_huge_inodes(library_scan_env, monkeypatch):
    lib, root, tmp_path = library_scan_env
    first = root / "Artist" / "Album" / "01 Song.wav"
    second = root / "Artist" / "Album" / "02 Song.wav"
    write_wav(first, 8)
    write_wav(second, 8)
    _patch_audio_stat(monkeypatch, {
        "01 Song.wav": (HUGE_INODE, HUGE_DEVICE),
        "02 Song.wav": (MAX_U64, MAX_U64),
    })

    lib._scan_running = True
    lib._background_scan(False)
    assert lib._scan_progress["phase"] == "done", lib._scan_progress
    assert lib._scan_progress["error"] is None

    db = open_db(tmp_path)
    first_row = db.get(str(first))
    second_row = db.get(str(second))
    db.close()
    assert first_row is not None and second_row is not None
    _assert_signed_inode(first_row["file_inode"], HUGE_INODE)
    _assert_signed_inode(second_row["file_inode"], MAX_U64)
    _assert_signed_inode(first_row["file_device"], HUGE_DEVICE)
    _assert_signed_inode(second_row["file_device"], MAX_U64)

    # A fresh library, reconciled rather than scanned, stores the same values.
    db = open_db(tmp_path)
    db._conn.execute("DELETE FROM scanned")
    db._conn.execute("DELETE FROM scanned_dirs")
    db.commit()
    db.close()
    lib._reconcile_running = True
    lib._background_path_reconcile()
    assert lib._reconcile_progress["phase"] == "done", lib._reconcile_progress
    assert lib._reconcile_progress["error"] is None
    db = open_db(tmp_path)
    reconciled = db.get(str(first))
    db.close()
    assert reconciled is not None
    _assert_signed_inode(reconciled["file_inode"], HUGE_INODE)
    _assert_signed_inode(reconciled["file_device"], HUGE_DEVICE)


def test_huge_inode_move_heals_by_identity(library_scan_env, monkeypatch):
    lib, root, tmp_path = library_scan_env
    original = root / "Artist" / "Old Album" / "01 Old Name.wav"
    moved = root / "Artist" / "New Album" / "09 New Name.wav"
    write_wav(original, 12)
    _patch_audio_stat(monkeypatch, {
        "01 Old Name.wav": (HUGE_INODE, HUGE_DEVICE),
        "09 New Name.wav": (HUGE_INODE, HUGE_DEVICE),
    })

    lib._scan_running = True
    lib._background_scan(False)
    assert lib._scan_progress["phase"] == "done", lib._scan_progress

    db = open_db(tmp_path)
    stored = db.get(str(original))
    assert stored is not None
    _assert_signed_inode(stored["file_inode"], HUGE_INODE)
    db._conn.execute(
        "UPDATE scanned SET play_count = 4 WHERE path = ?",
        (stored["path"],),
    )
    db.commit()
    db.close()

    moved.parent.mkdir(parents=True)
    original.rename(moved)
    lib._reconcile_running = True
    lib._background_path_reconcile()
    assert lib._reconcile_progress["phase"] == "done", lib._reconcile_progress
    assert lib._reconcile_progress["error"] is None

    db = open_db(tmp_path)
    old = db.get(str(original))
    new = db.get(str(moved))
    all_rows = db.identity_rows()
    db.close()
    assert old is None
    assert new is not None
    assert new["missing_since"] is None
    assert new["play_count"] == 4
    _assert_signed_inode(new["file_inode"], HUGE_INODE)
    assert len(all_rows) == 1


def test_scan_backfills_null_inode_with_converted_value(library_scan_env, monkeypatch):
    lib, root, tmp_path = library_scan_env
    path = root / "Artist" / "Album" / "01 Song.flac"
    write_wav(path, 8)
    _patch_audio_stat(monkeypatch, {"01 Song.flac": (HUGE_INODE, HUGE_DEVICE)})
    db = open_db(tmp_path)
    db.record(
        str(path),
        status="tagged",
        artist="Artist",
        title="01 Song",
        album="Album",
        duration=8,
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
        metadata_complete=True,
    )
    db.commit()
    assert db.get(str(path))["file_inode"] is None
    db.close()

    lib._scan_running = True
    lib._background_scan(False)
    assert lib._scan_progress["phase"] == "done", lib._scan_progress

    db = open_db(tmp_path)
    row = db.get(str(path))
    db.close()
    assert row is not None
    assert row["file_size"] is not None
    _assert_signed_inode(row["file_inode"], HUGE_INODE)
    _assert_signed_inode(row["file_device"], HUGE_DEVICE)


def test_per_file_stat_and_identity_errors_do_not_abort_scan(library_scan_env, monkeypatch):
    lib, root, tmp_path = library_scan_env
    good = root / "Artist" / "Album" / "01 Song.wav"
    stat_fail = root / "Artist" / "Album" / "02 Broken.wav"
    overflow = root / "Artist" / "Album" / "03 Overflow.wav"
    write_wav(good, 8)
    write_wav(stat_fail, 8)
    write_wav(overflow, 8)

    real_lstat = os.lstat

    def fake_lstat(path, *args, **kwargs):
        if Path(os.fspath(path)).name == "02 Broken.wav":
            raise OSError("stat failed")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", fake_lstat)

    real_fields = lib._file_identity_fields

    def flaky_fields(file_path, *, allowed_dirs):
        if Path(file_path).name == "03 Overflow.wav":
            raise OverflowError("identity overflow")
        return real_fields(file_path, allowed_dirs=allowed_dirs)

    monkeypatch.setattr(lib, "_file_identity_fields", flaky_fields)

    lib._scan_running = True
    lib._background_scan(False)
    assert lib._scan_progress["phase"] == "done", lib._scan_progress
    assert lib._scan_progress["error"] is None

    db = open_db(tmp_path)
    good_row = db.get(str(good))
    db.close()
    assert good_row is not None
    assert good_row["missing_since"] is None


def test_scan_level_exception_sets_phase_error(library_scan_env, monkeypatch):
    lib, root, _tmp_path = library_scan_env
    write_wav(root / "Artist" / "Album" / "01 Song.wav", 8)

    def boom(*args, **kwargs):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(os, "walk", boom)
    lib._scan_running = True
    lib._background_scan(False)
    assert lib._scan_progress["phase"] == "error"
    assert lib._scan_progress["error"]


@pytest.mark.parametrize("raw", [HUGE_INODE, MAX_U64])
def test_record_and_migrate_accept_unsigned_64_bit_ids(tmp_path, raw):
    from tidal_dl.helper.library_db.utils import sqlite_int64

    db = open_db(tmp_path)
    old = "/music/Artist/Album/01 Song.flac"
    new = "/music/Artist/Album/02 Song.flac"
    db.record(
        old,
        status="tagged",
        artist="Artist",
        title="Song",
        album="Album",
        file_inode=raw,
        file_device=raw,
        file_size=10,
    )
    db.commit()
    row = db.get(old)
    assert row is not None
    assert row["file_inode"] == sqlite_int64(raw)
    assert row["file_device"] == sqlite_int64(raw)
    assert db.migrate_path(old, new, file_inode=raw, file_device=raw, file_size=10)
    db.commit()
    moved = db.get(new)
    db.close()
    assert moved is not None
    assert moved["file_inode"] == sqlite_int64(raw)
    assert moved["file_device"] == sqlite_int64(raw)
