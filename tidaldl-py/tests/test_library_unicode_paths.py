"""NFC/NFD library path twins must count as one file.

Live 1.7.8 Zeratool (2026-08-31): GET /api/library/search?q=Alizée returned
two rows for one inode — macOS os.walk NFD vs tag/download NFC. Do not
rewrite files or rename artist folders.
"""

from __future__ import annotations

import os
import unicodedata
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from tidal_dl.helper.library_db import LibraryDB

ARTIST_NFC = "Alizée"
ARTIST_NFD = unicodedata.normalize("NFD", ARTIST_NFC)
ALBUM_NFC = "Mes Courants Électriques"
ALBUM_NFD = unicodedata.normalize("NFD", ALBUM_NFC)
TITLE = "J'en ai marre !"


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _nfd(value: str) -> str:
    return unicodedata.normalize("NFD", value)


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\x00\x00" * 8)


def _alizee_strings(root: str = "/Volumes/Music") -> tuple[str, str]:
    nfc = f"{root}/{ARTIST_NFC}/{ALBUM_NFC}/{TITLE}.flac"
    nfd = _nfd(nfc)
    assert nfc != nfd
    return nfc, nfd


def _hardlink_alizee_pair(library_dir: Path) -> tuple[str, str]:
    nfc = library_dir / ARTIST_NFC / ALBUM_NFC / f"{TITLE}.wav"
    nfd = library_dir / ARTIST_NFD / ALBUM_NFD / f"{TITLE}.wav"
    _write_wav(nfc)
    nfd.parent.mkdir(parents=True, exist_ok=True)
    if nfc.resolve() != nfd.resolve():
        os.link(nfc, nfd)
    assert os.stat(nfc).st_ino == os.stat(nfd).st_ino
    assert os.stat(nfc).st_dev == os.stat(nfd).st_dev
    return str(nfc), str(nfd)


def _insert_raw(db: LibraryDB, path: str, *, artist: str, title: str, album: str) -> None:
    assert db._conn
    db._conn.execute(
        """INSERT INTO scanned (path, status, artist, title, album, duration,
                                scanned_at, metadata_complete)
           VALUES (?, 'tagged', ?, ?, ?, 1, 1, 1)""",
        (path, artist, title, album),
    )


@pytest.fixture
def db(tmp_path):
    opened = LibraryDB(tmp_path / "test.db")
    opened.open()
    yield opened
    opened.close()


class TestUnicodeFormHypothesis:
    def test_alizee_nfc_and_nfd_are_distinct_strings(self):
        nfc, nfd = _alizee_strings()
        assert "é" in ARTIST_NFC
        assert ARTIST_NFC != ARTIST_NFD
        assert nfc != nfd
        assert _nfc(nfd) == nfc
        assert unicodedata.normalize("NFD", nfc) == nfd


class TestRecordStoresNfc:
    def test_record_nfd_path_stores_nfc_and_get_finds_either_form(self, db):
        nfc, nfd = _alizee_strings()
        db.record(nfd, status="tagged", artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()

        stored = db.get(nfd)
        assert stored is not None
        assert stored["path"] == nfc
        assert db.get(nfc)["path"] == nfc
        assert db.is_known(nfc)
        assert db.is_known(nfd)
        assert db.known_paths() == {nfc}

    def test_record_nfc_then_nfd_is_one_row(self, db):
        nfc, nfd = _alizee_strings()
        db.record(nfc, status="tagged", artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.record(nfd, status="tagged", artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()

        rows, total = db.tracks_page(query="Alizée", limit=50, offset=0)
        assert total == 1
        assert len(rows) == 1
        assert rows[0]["path"] == nfc


class TestCollapseExistingTwins:
    def test_raw_nfc_nfd_pair_collapses_to_one_nfc_row(self, db):
        nfc, nfd = _alizee_strings()
        _insert_raw(db, nfc, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        _insert_raw(db, nfd, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()
        assert len(db.known_paths()) == 2

        removed = db.collapse_unicode_path_twins()
        db.commit()

        assert removed == 1
        assert db.known_paths() == {nfc}
        albums = db.all_albums("Alizée")
        assert len(albums) == 1
        assert albums[0]["track_count"] == 1

    def test_open_collapses_twins_already_in_sqlite(self, tmp_path):
        nfc, nfd = _alizee_strings()
        db_path = tmp_path / "library.db"
        first = LibraryDB(db_path)
        first.open()
        _insert_raw(first, nfc, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        _insert_raw(first, nfd, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        first.commit()
        first.close()

        reopened = LibraryDB(db_path)
        reopened.open()
        try:
            assert reopened.known_paths() == {nfc}
            rows, total = reopened.tracks_page(query="Alizée", limit=20, offset=0)
            assert total == 1
            assert rows[0]["path"] == nfc
        finally:
            reopened.close()

    def test_same_inode_nfc_nfd_pair_collapses_without_rewriting_disk(self, db, tmp_path):
        nfc, nfd = _hardlink_alizee_pair(tmp_path / "Music")
        assert nfc != nfd
        _insert_raw(db, nfc, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        _insert_raw(db, nfd, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()

        db.collapse_unicode_path_twins()
        db.commit()

        assert db.known_paths() == {nfc}
        assert Path(nfc).is_file()
        assert Path(nfd).is_file()
        assert os.stat(nfc).st_ino == os.stat(nfd).st_ino
        assert Path(nfd).parent.parent.name == ARTIST_NFD

    def test_collapse_moves_play_events_and_favorites_to_nfc(self, db):
        nfc, nfd = _alizee_strings()
        _insert_raw(db, nfc, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        _insert_raw(db, nfd, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.log_play_event(nfd, artist=ARTIST_NFC, duration=1, played_at=10)
        db.add_favorite(path=nfd, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()

        db.collapse_unicode_path_twins()
        db.commit()

        events = db._conn.execute("SELECT path FROM play_events").fetchall()
        favs = db._conn.execute("SELECT path FROM favorites").fetchall()
        assert [row["path"] for row in events] == [nfc]
        assert [row["path"] for row in favs] == [nfc]

    def test_trusted_path_accepts_nfd_after_collapse(self, tmp_path, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        library_dir = tmp_path / "Music"
        nfc, nfd = _hardlink_alizee_pair(library_dir)
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _insert_raw(db, nfc, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        _insert_raw(db, nfd, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.collapse_unicode_path_twins()
        db.commit()
        db.close()

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(library_dir), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        library_api._invalidate_db_cache()

        assert library_api._exact_scanned_path(nfd) == nfc
        assert library_api._path_in_library(nfd) is True
        trusted = library_api._trusted_library_path(nfd)
        assert trusted is not None
        assert trusted.is_file()
        assert os.stat(trusted).st_ino == os.stat(nfd).st_ino

    def test_does_not_collapse_distinct_files(self, db):
        db.record("/music/Alizée/Studio/01.flac", status="tagged", artist=ARTIST_NFC,
                  title=TITLE, album=ALBUM_NFC)
        db.record("/music/Alizée/En concert (Live)/01.flac", status="tagged",
                  artist=ARTIST_NFC, title=TITLE, album="En concert (Live)")
        db.commit()

        db.collapse_unicode_path_twins()
        db.commit()

        assert len(db.known_paths()) == 2


class TestReconcilerLookupsAcceptTwins:
    def test_migrate_path_nfc_to_nfd_is_identity_noop(self, db):
        nfc, nfd = _alizee_strings()
        db.record(nfc, status="tagged", artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()

        assert db.migrate_path(nfc, nfd) is True
        assert db.known_paths() == {nfc}
        assert db.get(nfd)["path"] == nfc

    def test_migrate_path_still_moves_distinct_paths(self, db):
        nfc, _nfd = _alizee_strings()
        moved = "/Volumes/Music/Moved/song.flac"
        db.record(nfc, status="tagged", artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()

        assert db.migrate_path(nfc, moved) is True
        assert db.known_paths() == {moved}
        assert db.get(nfc) is None
        assert db.get(moved)["path"] == moved

    def test_mark_and_clear_missing_accept_nfd_of_nfc_row(self, db):
        nfc, nfd = _alizee_strings()
        db.record(nfc, status="tagged", artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()

        db.mark_missing(nfd, since=123)
        assert db.get(nfc)["missing_since"] == 123
        db.clear_missing(nfd)
        assert db.get(nfc)["missing_since"] is None

    def test_mark_missing_accepts_nfc_request_for_leftover_nfd_row(self, db):
        nfc, nfd = _alizee_strings()
        _insert_raw(db, nfd, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()

        db.mark_missing(nfc, since=456)
        row = db.get(nfc)
        assert row is not None
        assert row["path"] == nfd
        assert row["missing_since"] == 456

    def test_playback_cache_resolves_nfd_of_old_path(self, tmp_path, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        nfc, nfd = _alizee_strings()
        dest = "/Volumes/Music/Moved/song.flac"
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        library_api._playback_migration_cache.clear()
        library_api._remember_playback_migrations([(nfc, dest)])
        assert library_api.playback_resolved_path(nfd) == dest
        assert library_api.playback_resolved_path(nfc) == dest


class TestScanDoesNotCreateTwins:
    def _patch_scan(self, monkeypatch, tmp_path: Path, library_dir: Path):
        import tidal_dl.gui.api.library as library_api

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(library_dir), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
        monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)
        return library_api

    def test_scan_indexes_hardlinked_nfc_nfd_pair_once(self, tmp_path, monkeypatch):
        library_dir = tmp_path / "music"
        nfc, nfd = _hardlink_alizee_pair(library_dir)
        library_api = self._patch_scan(monkeypatch, tmp_path, library_dir)
        library_api._background_scan(rescan=False)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        rows, total = db.tracks_page(query="Alizée", limit=20, offset=0)
        albums = db.all_albums("Alizée")
        db.close()

        assert paths == {nfc}
        assert nfd not in paths
        assert total == 1
        assert rows[0]["path"] == nfc
        assert len(albums) == 1
        assert albums[0]["track_count"] == 1
        assert Path(nfc).is_file()
        assert Path(nfd).is_file()

    def test_scan_does_not_readd_nfd_when_nfc_already_known(self, tmp_path, monkeypatch):
        library_dir = tmp_path / "music"
        nfc, nfd = _hardlink_alizee_pair(library_dir)
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        db.record(nfc, status="tagged", artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()
        db.close()

        library_api = self._patch_scan(monkeypatch, tmp_path, library_dir)
        library_api._background_scan(rescan=False)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        _, total = db.tracks_page(query="Alizée", limit=20, offset=0)
        db.close()

        assert paths == {nfc}
        assert total == 1

    def test_scan_collapses_leftover_sqlite_twins(self, tmp_path, monkeypatch):
        library_dir = tmp_path / "music"
        nfc, nfd = _hardlink_alizee_pair(library_dir)
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _insert_raw(db, nfc, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        _insert_raw(db, nfd, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()
        db.close()

        library_api = self._patch_scan(monkeypatch, tmp_path, library_dir)
        library_api._background_scan(rescan=False)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        assert db.known_paths() == {nfc}
        _, total = db.tracks_page(query="Alizée", limit=20, offset=0)
        db.close()
        assert total == 1


class TestLibrarySearchEndpoint:
    def test_search_alizee_returns_one_row_for_nfc_nfd_twins(self, client, tmp_path):
        import tidal_dl.gui.api.library as library_api
        from tidal_dl.helper.path import path_config_base

        nfc, nfd = _alizee_strings()
        db = LibraryDB(Path(path_config_base()) / "library.db")
        db.open()
        _insert_raw(db, nfc, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        _insert_raw(db, nfd, artist=ARTIST_NFC, title=TITLE, album=ALBUM_NFC)
        db.commit()
        db.close()
        library_api._invalidate_db_cache()

        response = client.get(
            "/api/library/search",
            params={"q": "Alizée", "type": "tracks"},
            headers=client._host_header,
        )
        albums = client.get(
            "/api/library/search",
            params={"q": "Alizée", "type": "albums"},
            headers=client._host_header,
        )
        artists = client.get(
            "/api/library/search",
            params={"q": "Alizée", "type": "artists"},
            headers=client._host_header,
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert len(payload["tracks"]) == 1
        assert payload["tracks"][0]["path"] == nfc
        assert albums.status_code == 200
        album_payload = albums.json()
        assert album_payload["total"] == 1
        assert album_payload["albums"][0]["track_count"] == 1
        assert artists.status_code == 200
        artist_payload = artists.json()
        assert artist_payload["total"] == 1
        assert artist_payload["artists"][0]["track_count"] == 1
        assert artist_payload["artists"][0]["album_count"] == 1
