"""Tests for Home view — DB schema, play tracking, aggregation, API."""
import pytest

from tidal_dl.helper.library_db import LibraryDB


@pytest.fixture
def db(tmp_path):
    db = LibraryDB(tmp_path / "test.db")
    db.open()
    yield db
    db.close()


def test_schema_v3_columns_exist(db):
    """play_count, last_played, genre columns on scanned table."""
    cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(scanned)")}
    assert "play_count" in cols
    assert "last_played" in cols
    assert "genre" in cols


def test_play_events_table_exists(db):
    """play_events table created with correct columns."""
    row = db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='play_events'"
    ).fetchone()
    assert row is not None
    cols = {r["name"] for r in db._conn.execute("PRAGMA table_info(play_events)")}
    assert cols == {"id", "path", "artist", "genre", "duration", "played_at"}


def test_increment_play_count(db):
    """increment_play increments play_count and sets last_played."""
    db.record("test.flac", status="tagged", artist="Daft Punk", title="One More Time")
    db.commit()

    db.increment_play("test.flac")
    db.commit()

    row = db.get("test.flac")
    assert row["play_count"] == 1
    assert row["last_played"] is not None

    db.increment_play("test.flac")
    db.commit()
    row = db.get("test.flac")
    assert row["play_count"] == 2


def test_increment_play_unknown_path_is_noop(db):
    """increment_play on unknown path does nothing, no error."""
    db.increment_play("/nonexistent.flac")  # should not raise


def test_log_play_event(db):
    """log_play_event inserts a row into play_events."""
    db.log_play_event(path="test.flac", artist="Daft Punk", genre="Electronic", duration=320)
    db.commit()

    rows = db._conn.execute("SELECT * FROM play_events").fetchall()
    assert len(rows) == 1
    assert rows[0]["artist"] == "Daft Punk"
    assert rows[0]["genre"] == "Electronic"
    assert rows[0]["duration"] == 320
    assert rows[0]["played_at"] > 0


def test_log_play_event_null_path(db):
    """Tidal streams have null path."""
    db.log_play_event(path=None, artist="Coldplay", genre="Alt Rock", duration=240)
    db.commit()
    rows = db._conn.execute("SELECT * FROM play_events").fetchall()
    assert len(rows) == 1
    assert rows[0]["path"] is None


def test_home_stats_empty(db):
    """home_stats returns valid structure even with no data."""
    stats = db.home_stats()
    assert stats["total_plays"] == 0
    assert stats["top_artist"] is None
    assert stats["most_replayed"] is None
    assert stats["track_count"] == 0
    assert stats["album_count"] == 0
    assert stats["listening_time_hours"] == 0
    assert isinstance(stats["genre_breakdown"], list)
    assert isinstance(stats["weekly_activity"], list)
    assert len(stats["weekly_activity"]) == 7


def test_home_stats_with_data(db):
    """home_stats aggregates play data correctly."""
    # Insert tracks
    db.record("a.flac", status="tagged", artist="Daft Punk", title="One More Time",
              album="Discovery", duration=320, genre="Electronic")
    db.record("b.flac", status="tagged", artist="Daft Punk", title="Around the World",
              album="Homework", duration=420, genre="Electronic")
    db.record("c.flac", status="tagged", artist="Coldplay", title="Yellow",
              album="Parachutes", duration=270, genre="Alt Rock")
    db.commit()

    # Simulate plays
    for _ in range(10):
        db.increment_play("a.flac")
        db.log_play_event(path="a.flac", artist="Daft Punk", genre="Electronic", duration=320)
    for _ in range(5):
        db.increment_play("b.flac")
        db.log_play_event(path="b.flac", artist="Daft Punk", genre="Electronic", duration=420)
    for _ in range(3):
        db.increment_play("c.flac")
        db.log_play_event(path="c.flac", artist="Coldplay", genre="Alt Rock", duration=270)
    db.commit()

    stats = db.home_stats()
    assert stats["total_plays"] == 18
    assert stats["top_artist"]["name"] == "Daft Punk"
    assert stats["most_replayed"]["name"] == "One More Time"
    assert stats["most_replayed"]["play_count"] == 10
    assert stats["track_count"] == 3
    assert stats["album_count"] == 3  # Discovery, Homework, Parachutes
    assert stats["listening_time_hours"] >= 0
    # genre_breakdown sourced from play_events (18 plays), not scanned (3 tracks)
    assert len(stats["genre_breakdown"]) >= 1
    assert stats["genre_breakdown"][0]["genre"] == "Electronic"
    assert stats["genre_breakdown"][0]["count"] == 15  # 10 + 5 Electronic plays


def test_genre_normalization():
    """Genre variants are normalized to canonical forms."""
    from tidal_dl.gui.api.library import _normalize_genre

    assert _normalize_genre("Electronica/Dance") == "Electronic"
    assert _normalize_genre("Electronica") == "Electronic"
    assert _normalize_genre("Hip-Hop/Rap") == "Hip-Hop"
    assert _normalize_genre("Hip Hop") == "Hip-Hop"
    assert _normalize_genre("R&B/Soul") == "R&B"
    assert _normalize_genre("Alternative Rock") == "Alt Rock"
    assert _normalize_genre("Alt-Rock") == "Alt Rock"
    assert _normalize_genre("Rock") == "Rock"  # passthrough
    assert _normalize_genre(None) is None
    assert _normalize_genre("") is None


def test_api_home_returns_200():
    """GET /api/home returns 200 with expected structure."""
    from fastapi.testclient import TestClient
    from tidal_dl.gui import create_app

    client = TestClient(create_app(port=8765))
    host = {"host": "localhost:8765"}
    resp = client.get("/api/home", headers=host)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_plays" in data
    assert "weekly_activity" in data
    assert len(data["weekly_activity"]) == 7


def test_api_home_play_returns_204():
    """POST /api/home/play returns 204."""
    from fastapi.testclient import TestClient
    from tidal_dl.gui import create_app

    client = TestClient(create_app(port=8765))
    host = {"host": "localhost:8765"}

    # Get CSRF token
    index = client.get("/", headers=host)
    import re
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', index.text)
    token = csrf.group(1) if csrf else ""

    resp = client.post(
        "/api/home/play",
        json={"artist": "Daft Punk", "genre": "Electronic", "duration": 320},
        headers={**host, "X-CSRF-Token": token},
    )
    assert resp.status_code == 204
