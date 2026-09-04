"""Stale scanned rows outside music roots must drop on open.

Vanished in-root files stay in the ledger so reconcile can migrate
identity via missing_since. This module must not DELETE those rows.
"""

from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

from tidal_dl.helper import library_scanner
from tidal_dl.helper.library_db import LibraryDB


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\x00\x00" * 8)


def _seed(db: LibraryDB, path: Path | str, *, artist: str, title: str, album: str = "Album") -> None:
    db.record(
        str(path),
        status="tagged",
        artist=artist,
        title=title,
        album=album,
        duration=1,
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
        metadata_complete=True,
    )


def test_path_under_music_roots_rejects_qa_cache_path(tmp_path: Path) -> None:
    music = tmp_path / "Volumes" / "Music"
    music.mkdir(parents=True)
    qa = tmp_path / "Users" / "hackbook" / ".cache" / "tactica" / "music-dl-pr149-qa"
    leftover = qa / "Sting" / "The Last Ship.flac"

    assert library_scanner.path_under_music_roots(music / "Sting" / "keep.flac", [music]) is True
    assert library_scanner.path_under_music_roots(leftover, [music]) is False


def test_drop_stale_keeps_missing_file_under_root_and_play_history(tmp_path: Path) -> None:
    music = tmp_path / "music"
    keep = music / "Artist" / "Album" / "keep.flac"
    missing = music / "Artist" / "Album" / "gone.flac"
    _write_wav(keep)

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed(db, keep, artist="Artist", title="Keep")
    _seed(db, missing, artist="Artist", title="Gone")
    db.log_play_event(path=str(missing), artist="Artist", duration=1, played_at=200)
    db.commit()

    dropped = library_scanner.drop_stale_library_rows(db, [music])
    paths = db.known_paths()
    row = db.get(str(missing))
    plays = db._conn.execute(
        "SELECT COUNT(*) FROM play_events WHERE path = ?", (str(missing),)
    ).fetchone()[0]
    db.close()

    assert dropped == 0
    assert str(keep) in paths
    assert str(missing) in paths
    assert row is not None
    assert row.get("missing_since") is None
    assert plays == 1
    assert keep.is_file()


def test_drop_stale_removes_path_outside_root_and_leaves_disk_file(tmp_path: Path) -> None:
    music = tmp_path / "Volumes" / "Music"
    music.mkdir(parents=True)
    qa = tmp_path / "Users" / "hackbook" / ".cache" / "tactica" / "music-dl-pr149-qa"
    leftover = qa / "Sting" / "The Last Ship (Live at the Rijksmuseum).flac"
    _write_wav(leftover)

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed(
        db,
        leftover,
        artist="Sting",
        title="Night Watch",
        album="The Last Ship (Live at the Rijksmuseum)",
    )
    db.commit()

    dropped = library_scanner.drop_stale_library_rows(db, [music])
    paths = db.known_paths()
    db.close()

    assert dropped == 1
    assert str(leftover) not in paths
    assert leftover.is_file()


def test_drop_stale_keeps_missing_row_when_root_is_unmounted(tmp_path: Path) -> None:
    music = tmp_path / "Volumes" / "Music"
    missing = music / "Sting" / "Night Watch.flac"

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed(db, missing, artist="Sting", title="Night Watch")
    db.commit()

    dropped = library_scanner.drop_stale_library_rows(db, [music])
    paths = db.known_paths()
    db.close()

    assert dropped == 0
    assert str(missing) in paths


def test_library_search_and_recents_drop_unrooted_without_sync(tmp_path: Path, monkeypatch) -> None:
    import tidal_dl.gui.api.home as home_api
    import tidal_dl.gui.api.library as library_api

    music = tmp_path / "Volumes" / "Music"
    keep = music / "Local" / "Album" / "keep.flac"
    missing = music / "Local" / "Album" / "gone.flac"
    leftover = (
        tmp_path / "Users" / "hackbook" / ".cache" / "tactica" / "music-dl-pr149-qa"
        / "Sting" / "The Last Ship (Live at the Rijksmuseum).flac"
    )
    _write_wav(keep)
    leftover.parent.mkdir(parents=True, exist_ok=True)

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed(db, keep, artist="Local", title="Keep")
    _seed(db, missing, artist="Local", title="Gone Night Watch")
    _seed(
        db,
        leftover,
        artist="Sting",
        title="Night Watch",
        album="The Last Ship (Live at the Rijksmuseum)",
    )
    db.log_play_event(path=str(leftover), artist="Sting", duration=1, played_at=200)
    db.log_play_event(path=str(keep), artist="Local", duration=1, played_at=100)
    db.log_play_event(path=str(missing), artist="Local", duration=1, played_at=50)
    db.commit()
    db.close()

    class FakeSettings:
        data = SimpleNamespace(download_base_path=str(music), scan_paths=str(music))

    monkeypatch.setattr(library_api, "Settings", FakeSettings)
    monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
    monkeypatch.setattr(home_api, "path_config_base", lambda: str(tmp_path))
    library_api._stale_purge_key = None
    library_api._close_thread_db()
    home_api._close_thread_db()

    recents = home_api.recent_plays(limit=20)
    recent_paths = {track["path"] for track in recents["tracks"]}
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    after_recents = db.known_paths()
    missing_plays = db._conn.execute(
        "SELECT COUNT(*) FROM play_events WHERE path = ?", (str(missing),)
    ).fetchone()[0]
    db.close()

    assert str(leftover) not in recent_paths
    assert str(leftover) not in after_recents
    assert str(missing) in after_recents
    assert str(keep) in after_recents
    assert missing_plays == 1

    search = library_api.library_search(q="Night Watch", type="tracks", limit=20)
    search_titles = {track["name"] for track in search["tracks"]}
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    paths = db.known_paths()
    db.close()

    assert "Night Watch" not in search_titles
    assert str(keep) in paths
    assert str(missing) in paths
    assert str(leftover) not in paths
    assert keep.is_file()


def test_drop_stale_skips_mass_unrooted_when_library_looks_remounted(tmp_path: Path) -> None:
    music = tmp_path / "Volumes" / "Music"
    other = tmp_path / "Volumes" / "Music 1"
    music.mkdir(parents=True)
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    for index in range(150):
        _seed(db, other / f"track{index:03d}.flac", artist="A", title=f"T{index}")
    db.commit()

    dropped = library_scanner.drop_stale_library_rows(db, [music])
    paths = db.known_paths()
    db.close()

    assert dropped == 0
    assert len(paths) == 150


def test_drop_stale_does_not_wipe_empty_mount_in_root_rows(tmp_path: Path) -> None:
    music = tmp_path / "music"
    music.mkdir()
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    for index in range(150):
        _seed(db, music / f"track{index:03d}.flac", artist="A", title=f"T{index}")
    db.commit()

    dropped = library_scanner.drop_stale_library_rows(db, [music])
    paths = db.known_paths()
    db.close()

    assert dropped == 0
    assert len(paths) == 150


def test_drop_stale_treats_isdir_oserror_as_unmounted(tmp_path: Path, monkeypatch) -> None:
    music = tmp_path / "music"
    keep = music / "Artist" / "Album" / "keep.flac"
    missing = music / "Artist" / "Album" / "gone.flac"
    leftover = tmp_path / "qa-cache" / "Sting" / "Night Watch.flac"
    _write_wav(keep)

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed(db, keep, artist="Artist", title="Keep")
    _seed(db, missing, artist="Artist", title="Gone")
    _seed(db, leftover, artist="Sting", title="Night Watch")
    db.commit()

    def boom(_self) -> bool:
        raise OSError("nas flaked")

    monkeypatch.setattr(Path, "is_dir", boom)
    dropped = library_scanner.drop_stale_library_rows(db, [music])
    paths = db.known_paths()
    db.close()

    assert dropped == 1
    assert str(keep) in paths
    assert str(missing) in paths
    assert str(leftover) not in paths


def test_library_search_survives_root_isdir_oserror(tmp_path: Path, monkeypatch) -> None:
    import os

    import tidal_dl.gui.api.library as library_api

    music = tmp_path / "Volumes" / "Music"
    keep = music / "Local" / "Album" / "keep.flac"
    leftover = tmp_path / "qa-cache" / "Sting" / "Night Watch.flac"
    _write_wav(keep)

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed(db, keep, artist="Local", title="Keep")
    _seed(db, leftover, artist="Sting", title="Night Watch")
    db.commit()
    db.close()

    class FakeSettings:
        data = SimpleNamespace(download_base_path=str(music), scan_paths=str(music))

    original = Path.is_dir
    music_key = os.path.normpath(str(music))

    def boom(self) -> bool:
        if os.path.normpath(os.path.expanduser(str(self))) == music_key:
            raise OSError("nas flaked")
        return original(self)

    monkeypatch.setattr(library_api, "Settings", FakeSettings)
    monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
    monkeypatch.setattr(Path, "is_dir", boom)
    library_api._stale_purge_key = None
    library_api._close_thread_db()

    search = library_api.library_search(q="Keep", type="tracks", limit=20)
    titles = {track["name"] for track in search["tracks"]}

    assert "Keep" in titles


def test_drop_stale_keeps_row_when_is_file_raises(tmp_path: Path, monkeypatch) -> None:
    music = tmp_path / "music"
    keep = music / "Artist" / "Album" / "keep.flac"
    _write_wav(keep)
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed(db, keep, artist="Artist", title="Keep")
    db.commit()

    def boom(_self) -> bool:
        raise OSError("volume flaked")

    monkeypatch.setattr(Path, "is_file", boom)
    dropped = library_scanner.drop_stale_library_rows(db, [music])
    paths = db.known_paths()
    db.close()

    assert dropped == 0
    assert str(keep) in paths


def test_scan_drops_outside_root_without_a_successful_walk(tmp_path: Path, monkeypatch) -> None:
    import os

    import tidal_dl.gui.api.library as library_api

    music = tmp_path / "music"
    keep = music / "Local" / "Album" / "keep.flac"
    leftover = tmp_path / "qa-cache" / "Sting" / "Night Watch.flac"
    _write_wav(keep)

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed(db, keep, artist="Local", title="Keep")
    _seed(db, leftover, artist="Sting", title="Night Watch")
    db.commit()
    db.close()

    class FakeSettings:
        data = SimpleNamespace(download_base_path=str(music), scan_paths="")

    monkeypatch.setattr(library_api, "Settings", FakeSettings)
    monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
    monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)

    def explode_walk(*args, **kwargs):
        raise RuntimeError("scan interrupted")

    monkeypatch.setattr(os, "walk", explode_walk)
    library_api._scan_running = True
    try:
        library_api._background_scan(rescan=False)
    finally:
        library_api._scan_running = False

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    paths = db.known_paths()
    db.close()

    assert str(keep) in paths
    assert str(leftover) not in paths


def test_drop_stale_and_library_api_have_no_check_missing() -> None:
    scanner = Path(__file__).resolve().parents[1] / "tidal_dl" / "helper" / "library_scanner.py"
    library = Path(__file__).resolve().parents[1] / "tidal_dl" / "gui" / "api" / "library.py"
    assert "check_missing" not in scanner.read_text()
    assert "check_missing" not in library.read_text()
