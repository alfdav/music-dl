"""Tests for LibraryDB — CRUD, pagination, dedup, migration, pragmas."""
import sqlite3
import pytest
from tidal_dl.helper.library_db import LibraryDB


@pytest.fixture
def db(tmp_path):
    d = LibraryDB(tmp_path / "test.db")
    d.open()
    yield d
    d.close()


class TestPragmas:
    def test_wal_mode_enabled(self, db):
        mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_busy_timeout_set(self, db):
        timeout = db._conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000


class TestCRUD:
    def test_record_and_get(self, db):
        db.record("/music/track.flac", status="tagged", artist="Daft Punk",
                  title="One More Time", album="Discovery", duration=320,
                  quality="44100Hz/16bit", fmt="FLAC", genre="Electronic")
        db.commit()
        row = db.get("/music/track.flac")
        assert row is not None
        assert row["artist"] == "Daft Punk"
        assert row["format"] == "FLAC"
        assert row["quality"] == "44100Hz/16bit"

    def test_get_nonexistent_returns_none(self, db):
        assert db.get("/nonexistent.flac") is None

    def test_record_upsert(self, db):
        db.record("/a.flac", status="tagged", artist="A")
        db.commit()
        db.record("/a.flac", status="tagged", artist="B")
        db.commit()
        assert db.get("/a.flac")["artist"] == "B"

    def test_remove(self, db):
        db.record("/a.flac", status="tagged")
        db.commit()
        db.remove("/a.flac")
        db.commit()
        assert db.get("/a.flac") is None

    def test_is_known(self, db):
        assert not db.is_known("/a.flac")
        db.record("/a.flac", status="tagged")
        db.commit()
        assert db.is_known("/a.flac")

    def test_known_paths(self, db):
        db.record("/a.flac", status="tagged")
        db.record("/b.flac", status="unreadable")
        db.commit()
        assert db.known_paths() == {"/a.flac", "/b.flac"}


class TestPagination:
    def _seed(self, db, n=10):
        for i in range(n):
            db.record(f"/track_{i:02d}.flac", status="tagged",
                      artist=f"Artist {i % 3}", title=f"Track {i}",
                      album=f"Album {i % 2}", duration=200 + i)
        db.commit()

    def test_tracks_page_limit_offset(self, db):
        self._seed(db)
        rows, total = db.tracks_page(limit=3, offset=0)
        assert len(rows) == 3
        assert total == 10

    def test_tracks_page_search(self, db):
        self._seed(db)
        rows, total = db.tracks_page(query="Track 5", limit=50, offset=0)
        assert total == 1
        assert rows[0]["title"] == "Track 5"

    def test_artists_page(self, db):
        self._seed(db)
        rows, total = db.artists_page(limit=50, offset=0)
        assert total == 3  # Artist 0, 1, 2

    def test_all_albums(self, db):
        self._seed(db)
        albums = db.all_albums()
        assert len(albums) == 2  # Album 0, Album 1


class TestAlbumDedup:
    def test_album_tracks_dedup_by_title(self, db):
        """Two copies of same title — keep shortest path."""
        db.record("/short/a.flac", status="tagged", artist="X", title="Song", album="Alb")
        db.record("/very/long/path/a.flac", status="tagged", artist="X", title="Song", album="Alb")
        db.commit()
        tracks = db.album_tracks("X", "Alb")
        assert len(tracks) == 1
        assert tracks[0]["path"] == "/short/a.flac"

    def test_album_tracks_dedup_ignores_title_casing_and_prefers_higher_quality(self, db):
        db.record(
            "/short/old.flac",
            status="tagged",
            artist="X",
            title="Purpose For Pain",
            album="Alb",
            quality="44100Hz/16bit",
            fmt="FLAC",
        )
        db.record(
            "/very/long/path/new.flac",
            status="tagged",
            artist="X",
            title="Purpose for Pain",
            album="Alb",
            quality="96000Hz/24bit",
            fmt="FLAC",
        )
        db.commit()

        tracks = db.album_tracks("X", "Alb")

        assert len(tracks) == 1
        assert tracks[0]["path"] == "/very/long/path/new.flac"


class TestDownloadHistory:
    def test_record_and_retrieve(self, db):
        db.record_download(track_id=123, name="Track", status="done",
                           artist="A", album="B", started_at=1.0, finished_at=2.0)
        db.commit()
        history = db.download_history(limit=10)
        assert len(history) == 1
        assert history[0]["track_id"] == 123
        assert history[0]["status"] == "done"

    def test_clear_history(self, db):
        db.record_download(track_id=1, name="T1", status="done")
        db.record_download(track_id=2, name="T2", status="error")
        db.commit()
        cleared = db.clear_download_history(status="error")
        assert cleared == 1
        assert len(db.download_history()) == 1


class TestFavorites:
    def test_add_and_check(self, db):
        db.add_favorite(path="/a.flac", artist="X", title="Y")
        db.commit()
        assert db.is_favorite(path="/a.flac")
        assert "/a.flac" in db.favorite_paths()

    def test_remove_favorite(self, db):
        db.add_favorite(path="/a.flac", artist="X", title="Y")
        db.commit()
        db.remove_favorite(path="/a.flac")
        db.commit()
        assert not db.is_favorite(path="/a.flac")

    def test_duplicate_add_is_noop(self, db):
        db.add_favorite(path="/a.flac", artist="X", title="Y")
        db.commit()
        db.add_favorite(path="/a.flac", artist="X", title="Y")
        db.commit()
        assert len(db.all_favorites()) == 1


class TestMigration:
    def test_fresh_db_has_all_tables(self, db):
        tables = {r["name"] for r in db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        expected = {"scanned", "play_events", "artist_images", "playlist_covers",
                    "quality_probes", "library_meta", "download_history", "favorites"}
        assert expected.issubset(tables)

    def test_v1_to_v3_migration(self, tmp_path):
        """Create a v1-style DB, then open with LibraryDB to trigger migration."""
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE scanned (
            path TEXT PRIMARY KEY, isrc TEXT, status TEXT NOT NULL,
            artist TEXT, title TEXT, scanned_at INTEGER NOT NULL)""")
        conn.execute("INSERT INTO scanned VALUES ('/a.flac', 'US123', 'tagged', 'X', 'Y', 1000)")
        conn.commit()
        conn.close()

        db = LibraryDB(db_path)
        db.open()
        cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(scanned)")}
        assert "album" in cols
        assert "duration" in cols
        assert "quality" in cols
        assert "format" in cols
        assert "play_count" in cols
        assert "genre" in cols
        row = db.get("/a.flac")
        assert row["artist"] == "X"
        db.close()
