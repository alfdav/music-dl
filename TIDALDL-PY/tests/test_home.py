"""Tests for Home view — DB schema, play tracking, aggregation, API."""
import pathlib
import tempfile
import time

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
