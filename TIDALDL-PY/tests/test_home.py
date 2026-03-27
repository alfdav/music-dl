"""Tests for Home view — DB schema, play tracking, aggregation, API."""
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


def test_home_stats_this_week_with_recent_plays(db):
    """this_week reflects only plays in the last 7 days."""
    now = int(time.time())
    old = now - 30 * 86400  # 30 days ago

    db.record("a.flac", status="tagged", artist="Linkin Park", title="Numb",
              album="Meteora", duration=200, genre="Rock")
    db.record("b.flac", status="tagged", artist="Deftones", title="Change",
              album="White Pony", duration=300, genre="Alt Rock")
    db.commit()

    for _ in range(50):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("a.flac", "Linkin Park", "Rock", 200, old),
        )
    for _ in range(8):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("b.flac", "Deftones", "Alt Rock", 300, now - 3600),
        )
    db.commit()

    stats = db.home_stats()

    assert stats["top_artist"]["name"] == "Linkin Park"
    assert stats["top_artist"]["play_count"] == 50

    assert stats["this_week"]["total_plays"] == 8
    assert stats["this_week"]["top_artist"]["name"] == "Deftones"
    assert stats["this_week"]["top_artist"]["play_count"] == 8
    assert stats["this_week"]["most_replayed"]["name"] == "Change"
    assert stats["this_week"]["most_replayed"]["play_count"] == 8
    assert stats["this_week"]["genre_breakdown"][0]["genre"] == "Alt Rock"


def test_home_stats_this_week_empty_when_no_recent(db):
    """this_week.total_plays is 0 when no plays in last 7 days."""
    now = int(time.time())
    old = now - 30 * 86400

    db.record("a.flac", status="tagged", artist="Linkin Park", title="Numb",
              album="Meteora", duration=200, genre="Rock")
    db.commit()

    for _ in range(10):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("a.flac", "Linkin Park", "Rock", 200, old),
        )
    db.commit()

    stats = db.home_stats()
    assert stats["this_week"]["total_plays"] == 0
    assert stats["this_week"]["top_artist"] is None
    assert stats["this_week"]["most_replayed"] is None


def test_home_stats_this_week_top_artists_list(db):
    """this_week.top_artists returns up to 5 artists sorted by play count."""
    now = int(time.time())
    db.record("a.flac", status="tagged", artist="A", title="T1", album="Al", duration=100)
    db.record("b.flac", status="tagged", artist="B", title="T2", album="Al", duration=100)
    db.record("c.flac", status="tagged", artist="C", title="T3", album="Al", duration=100)
    db.commit()

    for i, (path, artist, count) in enumerate([("a.flac", "A", 10), ("b.flac", "B", 5), ("c.flac", "C", 2)]):
        for _ in range(count):
            db._conn.execute(
                "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
                (path, artist, "Rock", 100, now - 3600),
            )
    db.commit()

    stats = db.home_stats()
    tw = stats["this_week"]
    assert len(tw["top_artists"]) == 3
    assert tw["top_artists"][0]["name"] == "A"
    assert tw["top_artists"][1]["name"] == "B"
    assert tw["top_artists"][2]["name"] == "C"


def test_api_home_includes_this_week():
    """GET /api/home response includes this_week key."""
    from fastapi.testclient import TestClient
    from tidal_dl.gui import create_app

    client = TestClient(create_app(port=8765))
    host = {"host": "localhost:8765"}
    resp = client.get("/api/home", headers=host)
    assert resp.status_code == 200
    data = resp.json()
    assert "this_week" in data
    assert "total_plays" in data["this_week"]
    # cover_path should not leak into API response
    if data["this_week"].get("top_artist"):
        assert "cover_path" not in data["this_week"]["top_artist"]
    if data["this_week"].get("most_replayed"):
        assert "cover_path" not in data["this_week"]["most_replayed"]


def test_home_stats_empty_includes_this_week(db):
    """home_stats returns this_week even with no data."""
    stats = db.home_stats()
    assert "this_week" in stats
    assert stats["this_week"]["total_plays"] == 0
    assert stats["this_week"]["top_artist"] is None
    assert stats["this_week"]["most_replayed"] is None
    assert isinstance(stats["this_week"]["genre_breakdown"], list)
    assert isinstance(stats["this_week"]["top_artists"], list)


def test_best_streak(db):
    """best_streak returns longest consecutive-day play run."""
    now = int(time.time())
    day = 86400
    # Seed: 5 consecutive days, gap, then 3 consecutive days
    for i in range(5):
        db.log_play_event("track.flac", artist="A", genre="Rock", played_at=now - (i * day))
    for i in range(3):
        db.log_play_event("track.flac", artist="A", genre="Rock", played_at=now - ((i + 7) * day))
    db.commit()

    stats = db.home_stats()
    assert stats["best_streak"] == 5


def test_best_streak_empty(db):
    """best_streak is 0 when no play events exist."""
    stats = db.home_stats()
    assert stats["best_streak"] == 0


def test_completionist_albums(db):
    """completionist_albums counts albums with every track played."""
    now = int(time.time())
    # Album A: 3 tracks, all played
    for i in range(3):
        path = f"/music/albumA/track{i}.flac"
        db.record(path, status="tagged", artist="X", album="Album A", title=f"T{i}")
        db.log_play_event(path, artist="X", genre="Pop", played_at=now - i)
    # Album B: 3 tracks, only 1 played
    for i in range(3):
        path = f"/music/albumB/track{i}.flac"
        db.record(path, status="tagged", artist="X", album="Album B", title=f"T{i}")
    db.log_play_event("/music/albumB/track0.flac", artist="X", genre="Pop", played_at=now)
    # Album C: 2 tracks, both played
    for i in range(2):
        path = f"/music/albumC/track{i}.flac"
        db.record(path, status="tagged", artist="Y", album="Album C", title=f"T{i}")
        db.log_play_event(path, artist="Y", genre="Jazz", played_at=now - i)
    db.commit()

    stats = db.home_stats()
    assert stats["completionist_albums"]["complete"] == 2  # Album A and C
    assert stats["completionist_albums"]["total"] >= 3


def test_recent_albums(db):
    """recent_albums returns 3 most recently scanned albums."""
    for i in range(5):
        db.record(f"/music/album{i}/t.flac", status="tagged", artist=f"A{i}", album=f"Album {i}", title="T")
    db.commit()

    stats = db.home_stats()
    assert len(stats["recent_albums"]) == 3
    # Most recent should be last inserted
    assert stats["recent_albums"][0]["album"] == "Album 4"


def test_top_album_from_play_events(db):
    """top_album should be derived from play_events, not scanned.play_count."""
    now = int(time.time())
    db.record("a.flac", status="tagged", artist="Daft Punk", title="One More Time",
              album="Discovery", duration=320, genre="Electronic")
    db.record("b.flac", status="tagged", artist="Daft Punk", title="Around the World",
              album="Homework", duration=420, genre="Electronic")
    db.commit()

    for _ in range(10):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("a.flac", "Daft Punk", "Electronic", 320, now - 3600),
        )
    for _ in range(3):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("b.flac", "Daft Punk", "Electronic", 420, now - 3600),
        )
    db.commit()

    stats = db.home_stats()
    assert stats["top_album"]["album"] == "Discovery"
    assert stats["top_album"]["play_count"] == 10
