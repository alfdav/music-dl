"""Open and store the on-disk path. NFC is only the row-matching key.

Some macOS SMB shares open a file only under the exact directory-entry
spelling, often NFD. The NFC twin raises FileNotFoundError there. Scans
must index and heal rows with the walk's path, and must not mark that
row missing or insert a second one.

The strict opener below rejects the NFC spelling of each NFD fixture.
Linux tmp files already behave that way; the patch makes macOS and
Windows runs fail the same way.
"""

from __future__ import annotations

import errno
import os
import unicodedata
import wave
from pathlib import Path
from types import SimpleNamespace

from tidal_dl.helper.library_db import LibraryDB, canonical_library_path

ALBUM_NFD = "A\u0301lbum"
TRACK_NFD = "01 Cancio\u0301n.wav"
ALBUM_NFC = unicodedata.normalize("NFC", ALBUM_NFD)
TRACK_NFC_NAME = "01 Song.wav"


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\x00\x00" * 32)


def _walk_audio(root: Path) -> list[str]:
    found: list[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if Path(name).suffix.lower() == ".wav":
                found.append(str(Path(dirpath) / name))
    return found


def _blocked_nfc_forms(on_disk_paths: list[str]) -> set[str]:
    blocked: set[str] = set()
    for raw in on_disk_paths:
        current = os.path.abspath(os.fspath(raw))
        while True:
            nfc = unicodedata.normalize("NFC", current)
            if nfc != current:
                blocked.add(nfc)
                blocked.add(os.path.normpath(nfc))
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    return blocked


def _install_strict_opener(monkeypatch, on_disk_paths: list[str]) -> None:
    """NFC twins of *on_disk_paths* raise FileNotFoundError. Exact strings work."""
    blocked = _blocked_nfc_forms(on_disk_paths)
    real_stat = os.stat
    real_lstat = os.lstat
    real_open = os.open
    real_scandir = os.scandir
    real_builtin_open = open

    def reject(path) -> None:
        text = os.fspath(path)
        if text in blocked or os.path.abspath(text) in blocked or os.path.normpath(text) in blocked:
            raise FileNotFoundError(errno.ENOENT, "NFC form is not the on-disk name", text)

    def strict_stat(path, *args, **kwargs):
        reject(path)
        return real_stat(path, *args, **kwargs)

    def strict_lstat(path, *args, **kwargs):
        reject(path)
        return real_lstat(path, *args, **kwargs)

    def strict_os_open(path, flags, mode=0o777, *args, **kwargs):
        reject(path)
        return real_open(path, flags, mode, *args, **kwargs)

    def strict_scandir(path):
        reject(path)
        return real_scandir(path)

    def strict_open(path, *args, **kwargs):
        if not isinstance(path, int):
            reject(path)
        return real_builtin_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", strict_stat)
    monkeypatch.setattr(os, "lstat", strict_lstat)
    monkeypatch.setattr(os, "open", strict_os_open)
    monkeypatch.setattr(os, "scandir", strict_scandir)
    monkeypatch.setattr("builtins.open", strict_open)


def _bind_library(monkeypatch, tmp_path: Path, library_dir: Path):
    import tidal_dl.gui.api.library as library_api

    class FakeSettings:
        data = SimpleNamespace(download_base_path=str(library_dir), scan_paths="")

    monkeypatch.setattr(library_api, "Settings", FakeSettings)
    monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
    monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
    monkeypatch.setattr(library_api, "_album_cards", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda _path: None)
    return library_api


def _run_scan(library_api, *, rescan: bool = False) -> None:
    library_api._scan_running = True
    library_api._background_scan(rescan)
    progress = library_api._scan_progress
    assert progress["phase"] == "done", progress


def _open_db(tmp_path: Path) -> LibraryDB:
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    return db


def _nfd_track(root: Path) -> Path:
    path = root / "Artist" / ALBUM_NFD / TRACK_NFD
    _write_wav(path)
    return path


def _listed(root: Path, created: Path) -> str:
    wanted = canonical_library_path(str(created))
    matches = [item for item in _walk_audio(root) if canonical_library_path(item) == wanted]
    assert matches, _walk_audio(root)
    return matches[0]


def _assert_openable(path: str) -> None:
    st = os.stat(path)
    assert st.st_ino
    assert Path(path).is_file()


def test_new_nfd_file_is_indexed_from_the_on_disk_path(tmp_path, monkeypatch):
    """A new NFD name is tagged from the bytes the walk returned, and stored as that string."""
    root = tmp_path / "music"
    created = _nfd_track(root)
    on_disk = _listed(root, created)
    assert on_disk != canonical_library_path(on_disk)
    _install_strict_opener(monkeypatch, [on_disk])
    library_api = _bind_library(monkeypatch, tmp_path, root)

    _run_scan(library_api)

    db = _open_db(tmp_path)
    rows = db._conn.execute("SELECT * FROM scanned").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    db.close()
    assert row["path"] == on_disk
    assert row["status"] != "unreadable"
    assert row["artist"]
    assert row["title"]
    assert row["album"]
    assert row["file_inode"] is not None
    assert row["missing_since"] is None
    _assert_openable(row["path"])


def test_legacy_nfc_row_heals_in_place_and_second_scan_is_stable(tmp_path, monkeypatch):
    """An NFC row for an NFD file keeps its plays and favourite, then a later scan does not rewrite it."""
    root = tmp_path / "music"
    created = _nfd_track(root)
    on_disk = _listed(root, created)
    nfc = canonical_library_path(on_disk)
    assert nfc != on_disk
    library_api = _bind_library(monkeypatch, tmp_path, root)
    db = _open_db(tmp_path)
    db.record(
        nfc,
        status="tagged",
        artist="Artist",
        title="Example Song",
        album="Demo",
        duration=1,
        metadata_complete=True,
    )
    stored = db.get(nfc)["path"]
    db._conn.execute(
        """UPDATE scanned
           SET play_count = 7, file_size = NULL, file_mtime = NULL,
               file_inode = NULL, file_device = NULL
           WHERE path = ?""",
        (stored,),
    )
    db.add_favorite(path=stored, artist="Artist", title="Example Song", album="Demo")
    db.commit()
    rowid = db._conn.execute("SELECT rowid FROM scanned").fetchone()[0]
    db.close()
    _install_strict_opener(monkeypatch, [on_disk])

    _run_scan(library_api)

    db = _open_db(tmp_path)
    rows = db._conn.execute("SELECT rowid, * FROM scanned").fetchall()
    assert len(rows) == 1
    healed = dict(rows[0])
    assert healed["rowid"] == rowid
    assert healed["path"] == on_disk
    assert healed["play_count"] == 7
    assert healed["missing_since"] is None
    assert healed["status"] != "unreadable"
    assert healed["file_inode"] is not None
    assert db.is_favorite(path=on_disk)
    assert db.is_favorite(path=nfc)
    favs = [row["path"] for row in db._conn.execute("SELECT path FROM favorites")]
    assert favs == [on_disk]
    db.collapse_unicode_path_twins()
    db.commit()
    assert db.known_paths() == {on_disk}
    first = (
        healed["path"],
        healed["play_count"],
        healed["file_inode"],
        healed["missing_since"],
        healed["status"],
        healed["artist"],
        healed["title"],
    )
    db.close()

    _run_scan(library_api)

    db = _open_db(tmp_path)
    again = dict(db._conn.execute("SELECT * FROM scanned").fetchone())
    assert (
        again["path"],
        again["play_count"],
        again["file_inode"],
        again["missing_since"],
        again["status"],
        again["artist"],
        again["title"],
    ) == first
    assert len(db.known_paths()) == 1
    db.close()


def test_reconcile_indexes_nfd_file_and_heals_legacy_nfc_row(tmp_path, monkeypatch):
    """Path reconcile stats and stores the on-disk spelling, without a second row."""
    fresh_home = tmp_path / "fresh-home"
    fresh_home.mkdir()
    root = tmp_path / "music"
    created = _nfd_track(root)
    on_disk = _listed(root, created)
    library_api = _bind_library(monkeypatch, fresh_home, root)
    _install_strict_opener(monkeypatch, [on_disk])

    fresh = _open_db(fresh_home)
    library_api._run_path_reconcile(fresh, [root])
    indexed_row = fresh._conn.execute("SELECT * FROM scanned").fetchone()
    assert indexed_row is not None
    indexed = dict(indexed_row)
    assert indexed["path"] == on_disk
    assert indexed["status"] != "unreadable"
    assert indexed["file_inode"] is not None
    assert indexed["missing_since"] is None
    assert len(fresh.known_paths()) == 1
    fresh.close()

    legacy_home = tmp_path / "legacy-home"
    legacy_home.mkdir()
    legacy_root = tmp_path / "legacy-music"
    legacy_created = _nfd_track(legacy_root)
    legacy_disk = _listed(legacy_root, legacy_created)
    legacy_nfc = canonical_library_path(legacy_disk)
    assert legacy_disk != legacy_nfc
    _install_strict_opener(monkeypatch, [legacy_disk])
    library_api = _bind_library(monkeypatch, legacy_home, legacy_root)
    legacy = _open_db(legacy_home)
    legacy.record(
        legacy_nfc,
        status="tagged",
        artist="Artist",
        title="Example Song",
        album="Demo",
        duration=1,
        metadata_complete=True,
    )
    legacy._conn.execute(
        "UPDATE scanned SET play_count = 3, file_inode = NULL, file_size = NULL WHERE path = ?",
        (legacy.get(legacy_nfc)["path"],),
    )
    legacy.commit()
    rowid = legacy._conn.execute("SELECT rowid FROM scanned").fetchone()[0]
    library_api._run_path_reconcile(legacy, [legacy_root])
    rows = legacy._conn.execute("SELECT rowid, * FROM scanned").fetchall()
    assert len(rows) == 1
    healed = dict(rows[0])
    assert healed["rowid"] == rowid
    assert healed["path"] == legacy_disk
    assert healed["play_count"] == 3
    assert healed["missing_since"] is None
    assert healed["status"] != "unreadable"
    assert healed["file_inode"] is not None
    legacy.close()


def test_prune_keeps_nfd_file_and_marks_a_deleted_one_missing(tmp_path, monkeypatch):
    """A listed NFD file is not missing. After it is deleted, that same row is."""
    root = tmp_path / "music"
    created = _nfd_track(root)
    on_disk = _listed(root, created)
    nfc = canonical_library_path(on_disk)
    library_api = _bind_library(monkeypatch, tmp_path, root)
    db = _open_db(tmp_path)
    db.record(
        nfc,
        status="tagged",
        artist="Artist",
        title="Example Song",
        album="Demo",
        duration=1,
        metadata_complete=True,
    )
    db._conn.execute(
        "UPDATE scanned SET play_count = 4, file_inode = NULL, file_size = NULL WHERE path = ?",
        (db.get(nfc)["path"],),
    )
    db.commit()
    db.close()
    _install_strict_opener(monkeypatch, [on_disk])

    _run_scan(library_api)
    db = _open_db(tmp_path)
    present = dict(db._conn.execute("SELECT * FROM scanned").fetchone())
    assert present["path"] == on_disk
    assert present["missing_since"] is None
    assert present["play_count"] == 4
    assert len(db.known_paths()) == 1
    db.close()

    Path(on_disk).unlink()
    _run_scan(library_api)
    db = _open_db(tmp_path)
    gone = dict(db._conn.execute("SELECT * FROM scanned").fetchone())
    assert len(db.known_paths()) == 1
    assert gone["play_count"] == 4
    assert gone["missing_since"] is not None
    db.close()


def test_rescan_keeps_the_nfc_row_and_its_user_data(tmp_path, monkeypatch):
    """rescan=true rewrites the stored spelling in place and does not add a row."""
    root = tmp_path / "music"
    created = _nfd_track(root)
    on_disk = _listed(root, created)
    nfc = canonical_library_path(on_disk)
    library_api = _bind_library(monkeypatch, tmp_path, root)
    db = _open_db(tmp_path)
    db.record(
        nfc,
        status="tagged",
        artist="Artist",
        title="Example Song",
        album="Demo",
        duration=1,
        metadata_complete=True,
    )
    stored = db.get(nfc)["path"]
    db._conn.execute(
        "UPDATE scanned SET play_count = 5, file_inode = NULL, file_size = NULL WHERE path = ?",
        (stored,),
    )
    db.add_favorite(path=stored, artist="Artist", title="Example Song", album="Demo")
    db.commit()
    rowid = db._conn.execute("SELECT rowid FROM scanned").fetchone()[0]
    db.close()
    _install_strict_opener(monkeypatch, [on_disk])

    _run_scan(library_api, rescan=True)

    db = _open_db(tmp_path)
    rows = db._conn.execute("SELECT rowid, * FROM scanned").fetchall()
    assert len(rows) == 1
    healed = dict(rows[0])
    assert healed["rowid"] == rowid
    assert healed["path"] == on_disk
    assert healed["play_count"] == 5
    assert healed["missing_since"] is None
    assert healed["status"] != "unreadable"
    assert healed["file_inode"] is not None
    assert [row["path"] for row in db._conn.execute("SELECT path FROM favorites")] == [on_disk]
    db.close()


def test_nfc_and_ascii_files_stay_stored_as_the_walk_returned_them(tmp_path, monkeypatch):
    """ASCII and already-NFC names are unchanged: one row each, at the listed path, with an inode."""
    root = tmp_path / "music"
    ascii_path = root / "Artist" / "Album" / "01 Song.wav"
    nfc_path = root / "Artist" / ALBUM_NFC / TRACK_NFC_NAME
    _write_wav(ascii_path)
    _write_wav(nfc_path)
    listed = _walk_audio(root)
    assert str(ascii_path) in listed
    assert str(nfc_path) in listed
    library_api = _bind_library(monkeypatch, tmp_path, root)

    _run_scan(library_api)

    db = _open_db(tmp_path)
    stored = db.known_paths()
    rows = {
        row["path"]: dict(row)
        for row in db._conn.execute("SELECT * FROM scanned")
    }
    db.close()
    assert stored == set(listed)
    for path in listed:
        assert rows[path]["status"] != "unreadable"
        assert rows[path]["file_inode"] is not None
        assert rows[path]["missing_since"] is None
        _assert_openable(path)


def test_collapse_does_not_rewrite_a_lone_on_disk_nfd_row(tmp_path, monkeypatch):
    """Twin rows still collapse. A single on-disk NFD row stays on that spelling.

    The strict opener makes the NFC twin look missing, which is what a
    byte-exact share does. The keeper is the spelling that opens.
    """
    root = tmp_path / "music"
    created = _nfd_track(root)
    on_disk = _listed(root, created)
    nfc = canonical_library_path(on_disk)
    _install_strict_opener(monkeypatch, [on_disk])
    db = _open_db(tmp_path)
    db._conn.execute(
        """INSERT INTO scanned (path, status, artist, title, album, duration, scanned_at, metadata_complete)
           VALUES (?, 'tagged', 'Artist', 'Example Song', 'Demo', 1, 1, 1)""",
        (on_disk,),
    )
    db.commit()
    assert db.collapse_unicode_path_twins() == 0
    db.commit()
    assert db.known_paths() == {on_disk}

    db._conn.execute(
        """INSERT INTO scanned (path, status, artist, title, album, duration, scanned_at, metadata_complete, play_count)
           VALUES (?, 'tagged', 'Artist', 'Example Song', 'Demo', 1, 1, 1, 2)""",
        (nfc,),
    )
    db.commit()
    removed = db.collapse_unicode_path_twins()
    db.commit()
    assert removed == 1
    assert db.known_paths() == {on_disk}
    assert db.get(nfc)["play_count"] == 2
    db.close()
