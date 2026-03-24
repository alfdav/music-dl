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
