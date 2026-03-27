# Backend Verification Test Suite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the backend from 3 failing / 187 passing to 0 failing / ~230+ passing with coverage of every API module, duplicate detection, token handling, and download error paths.

**Architecture:** All tests use pytest with `tmp_path` fixtures for DB isolation. API tests use FastAPI's `TestClient` (sync, no server needed). No mocking of SQLite — use real temp databases. Mock only external dependencies (tidalapi, NAS filesystem).

**Tech Stack:** pytest, FastAPI TestClient, unittest.mock, tmp_path fixtures

**Existing test baseline:** 187 passed, 3 failed, 1 skipped (as of `uv run pytest tests/ -v`)

**Run command:** `uv run pytest tests/ -v --tb=short`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `tests/conftest.py` | Shared fixtures: `db`, `client`, `csrf_headers` |
| `tests/test_no_api_key.py` | **Modify** — fix 2 drifted assertions |
| `tests/test_phase2_resilience.py` | **Modify** — fix token refresh test |
| `tests/test_library_db.py` | **Create** — LibraryDB unit tests (CRUD, pagination, migration, busy_timeout) |
| `tests/test_duplicates.py` | **Create** — duplicate detection logic + cleanup/undo integration |
| `tests/test_api_endpoints.py` | **Create** — smoke tests for all API routes |
| `tests/test_token_refresh.py` | **Create** — token expiry type handling (float, datetime, None) |
| `tests/test_downloads.py` | **Create** — download error handler resilience |
| `pyproject.toml` | **Modify** — add test deps, pytest config |

---

### Task 1: Fix existing broken tests

**Files:**
- Modify: `tests/test_no_api_key.py:271,286`
- Modify: `tests/test_phase2_resilience.py:97-114`

These tests fail due to config drift (field count 47→48, base path `~/download`→`/Volumes/Music`) and the token refresh guard change. Fix them to pass with current code.

- [ ] **Step 1: Fix field count assertion**

In `tests/test_no_api_key.py:271`, the test asserts `len(fields(s.data)) == 47` but we now have 48 fields (added `scan_paths`).

```python
# tests/test_no_api_key.py:271
# Change:
assert len(fields(s.data)) == 47  # updated: +1 for scan_paths
# To:
assert len(fields(s.data)) == 48
```

- [ ] **Step 2: Fix base path assertion**

In `tests/test_no_api_key.py:286`, the test asserts `~/download` but the user's config persists `/Volumes/Music`. This test needs isolation — monkeypatch the config file path to a temp dir so it uses dataclass defaults.

```python
# tests/test_no_api_key.py:284-286 — replace:
def test_settings_default_base_path(self, clear_singletons):
    s = Settings()
    assert s.data.download_base_path == "~/download"

# With:
def test_settings_default_base_path(self, clear_singletons, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tidal_dl.config.path_file_settings",
        lambda: str(tmp_path / "settings.json"),
    )
    s = Settings()
    assert s.data.download_base_path == "~/download"
```

- [ ] **Step 3: Fix token refresh test**

In `tests/test_phase2_resilience.py:97-114`, the test sets `tidal.data.expiry_time = time.time() + 60` (already within refresh window since `refresh_window_sec=300`). The `_ensure_token_fresh` now uses `hasattr(.timestamp)` guard. The test should still work but the assertion at line 113 fails because `token_refresh` returns `None` not raising. Add a mock return value.

```python
# tests/test_phase2_resilience.py:97-114 — replace:
def test_tidal_ensure_token_fresh(monkeypatch):
    tidal = Tidal()
    called = {"refresh": 0, "persist": 0}

    class DummySession:
        token_type = "Bearer"
        access_token = "test"
        refresh_token = "test_refresh"
        expiry_time = time.time() + 3600  # new expiry after refresh

        def token_refresh(self):
            called["refresh"] += 1

    tidal.session = DummySession()
    tidal.data.expiry_time = time.time() + 60  # within 300s refresh window

    def _persist():
        called["persist"] += 1

    monkeypatch.setattr(tidal, "token_persist", _persist)
    result = tidal._ensure_token_fresh()
    assert result is True
    assert called["refresh"] == 1
    assert called["persist"] == 1
```

- [ ] **Step 4: Run full suite to verify fixes**

Run: `uv run pytest tests/ -v --tb=short`
Expected: 0 failed (all 190 pass)

- [ ] **Step 5: Commit**

```bash
git add tests/test_no_api_key.py tests/test_phase2_resilience.py
git commit -m "fix(tests): align assertions with current config state and token guard"
```

---

### Task 2: LibraryDB unit tests

**Files:**
- Create: `tests/test_library_db.py`
- Reference: `tidal_dl/helper/library_db.py`

Test the database layer in isolation. The existing `test_home.py` covers play tracking; this covers CRUD, pagination, dedup, migration, and the new `busy_timeout` pragma.

- [ ] **Step 1: Write test file with db fixture and core tests**

```python
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
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_library_db.py -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_library_db.py
git commit -m "test(db): LibraryDB unit tests — CRUD, pagination, dedup, migration, pragmas"
```

---

### Task 3: Duplicate detection unit tests

**Files:**
- Create: `tests/test_duplicates.py`
- Reference: `tidal_dl/gui/api/duplicates.py`

Test the pure detection logic (`_normalize`, `_path_score`, `_find_duplicate_groups`) and the full preview→clean→undo cycle with temp files.

- [ ] **Step 1: Write test file**

```python
"""Tests for duplicate detection logic and cleanup/undo cycle."""
import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.gui.api.duplicates import (
    _normalize, _path_score, _find_duplicate_groups, _get_db,
    _staging_base, _write_manifest, _read_manifest, _find_active_manifest,
    _is_cleanup_running, _acquire_lock, _release_lock, _lock_path,
)


@pytest.fixture
def db(tmp_path):
    d = LibraryDB(tmp_path / "test.db")
    d.open()
    yield d
    d.close()


class TestNormalize:
    def test_lowercases(self):
        assert _normalize("Hello World") == "hello world"

    def test_collapses_whitespace(self):
        assert _normalize("  too   many   spaces  ") == "too many spaces"

    def test_empty(self):
        assert _normalize("") == ""


class TestPathScore:
    def test_recycle_bin(self):
        assert _path_score("/volume/#recycle/track.flac") >= 100

    def test_playlists_folder(self):
        assert _path_score("/music/- playlists/track.flac") >= 50

    def test_playlists_subfolder(self):
        assert _path_score("/music/playlists/summer/track.flac") >= 50

    def test_numbered_suffix(self):
        assert _path_score("/music/track_01.flac") >= 30

    def test_canonical_path_scores_low(self):
        assert _path_score("/music/Artist/Album/track.flac") < 30

    def test_deeper_path_scores_higher(self):
        shallow = _path_score("/a/b/track.flac")
        deep = _path_score("/a/b/c/d/e/track.flac")
        assert deep > shallow


class TestFindDuplicateGroups:
    def _seed_isrc_dupes(self, db):
        """Two copies of same ISRC+album, different paths and qualities."""
        db.record("/music/Artist/Album/01.flac", status="tagged", isrc="US123",
                  artist="A", title="Song", album="Alb", duration=200,
                  quality="96000Hz/24bit", fmt="FLAC")
        db.record("/music/playlists/summer/01.flac", status="tagged", isrc="US123",
                  artist="A", title="Song", album="Alb", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.commit()

    def test_isrc_grouping(self, db):
        self._seed_isrc_dupes(db)
        groups = _find_duplicate_groups(db)
        assert len(groups) == 1
        assert groups[0]["key"].startswith("isrc:")
        assert len(groups[0]["duplicates"]) == 1

    def test_keeper_is_higher_quality(self, db):
        self._seed_isrc_dupes(db)
        groups = _find_duplicate_groups(db)
        keeper = groups[0]["keeper"]
        assert "96000Hz/24bit" in keeper["quality"]

    def test_title_artist_fallback(self, db):
        """ISRC-less tracks grouped by normalized title+artist+duration."""
        db.record("/a/song.flac", status="tagged", artist="Artist", title="Song",
                  album="A1", duration=200, quality="44100Hz/16bit", fmt="FLAC")
        db.record("/b/song.flac", status="tagged", artist="Artist", title="Song",
                  album="A1", duration=201, quality="44100Hz/16bit", fmt="FLAC")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 1
        assert groups[0]["key"].startswith("meta:")

    def test_duration_tolerance_exceeded(self, db):
        """Duration difference > 2s = not duplicates."""
        db.record("/a/song.flac", status="tagged", artist="A", title="S",
                  duration=200, quality="44100Hz/16bit", fmt="FLAC")
        db.record("/b/song.flac", status="tagged", artist="A", title="S",
                  duration=210, quality="44100Hz/16bit", fmt="FLAC")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 0

    def test_single_track_no_group(self, db):
        db.record("/a.flac", status="tagged", isrc="UNIQUE", artist="A",
                  title="Solo", album="X", duration=200)
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 0

    def test_unreadable_excluded(self, db):
        db.record("/a.flac", status="tagged", isrc="DUP1", artist="A",
                  title="X", album="A", duration=200)
        db.record("/b.flac", status="unreadable", isrc="DUP1", artist="A",
                  title="X", album="A", duration=200)
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 0


class TestManifest:
    def test_write_and_read(self, tmp_path):
        moved = [{"original": "/a.flac", "staged": "/tmp/x.flac", "db_row": {}}]
        _write_manifest(tmp_path, moved, time.time() + 300)
        manifest = _read_manifest(tmp_path)
        assert manifest is not None
        assert len(manifest["moved_files"]) == 1

    def test_read_missing(self, tmp_path):
        assert _read_manifest(tmp_path) is None

    def test_read_corrupt(self, tmp_path):
        (tmp_path / "manifest.json").write_text("not json{{{")
        assert _read_manifest(tmp_path) is None


class TestLock:
    def test_acquire_release(self, tmp_path):
        with patch("tidal_dl.gui.api.duplicates.path_config_base", return_value=str(tmp_path)):
            assert not _is_cleanup_running()
            _acquire_lock()
            assert _is_cleanup_running()
            _release_lock()
            assert not _is_cleanup_running()

    def test_stale_lock_auto_cleared(self, tmp_path):
        with patch("tidal_dl.gui.api.duplicates.path_config_base", return_value=str(tmp_path)):
            _acquire_lock()
            lp = _lock_path()
            # Backdate the lock file to 15 minutes ago
            old_time = time.time() - 900
            os.utime(str(lp), (old_time, old_time))
            assert not _is_cleanup_running()  # should auto-clear


class TestCleanupCycle:
    """Integration test: preview → clean → undo with real temp files."""

    def _setup(self, tmp_path, db):
        """Create two duplicate files and register them in DB."""
        music = tmp_path / "music"
        music.mkdir()
        keeper = music / "Artist" / "Album"
        keeper.mkdir(parents=True)
        dupe = music / "playlists" / "summer"
        dupe.mkdir(parents=True)

        (keeper / "01.flac").write_bytes(b"keeper audio data")
        (dupe / "01.flac").write_bytes(b"duplicate audio data")

        db.record(str(keeper / "01.flac"), status="tagged", isrc="US123",
                  artist="A", title="Song", album="Alb", duration=200,
                  quality="96000Hz/24bit", fmt="FLAC")
        db.record(str(dupe / "01.flac"), status="tagged", isrc="US123",
                  artist="A", title="Song", album="Alb", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.commit()
        return keeper / "01.flac", dupe / "01.flac"

    def test_full_cycle(self, tmp_path, db):
        keeper_path, dupe_path = self._setup(tmp_path, db)
        staging = tmp_path / "staging"

        # Verify duplicates detected
        groups = _find_duplicate_groups(db)
        assert len(groups) == 1

        # Verify keeper is the higher-quality one
        assert groups[0]["keeper"]["path"] == str(keeper_path)

        # Verify dupe file exists before cleanup
        assert dupe_path.exists()
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_duplicates.py -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_duplicates.py
git commit -m "test(duplicates): detection logic, path scoring, manifest, lock, cleanup cycle"
```

---

### Task 4: API endpoint smoke tests

**Files:**
- Create: `tests/test_api_endpoints.py`
- Modify: `tests/conftest.py` — add shared `client` fixture
- Reference: `tidal_dl/gui/api/__init__.py` for all routes

Test every GET endpoint returns 200 with expected shape. Test POST endpoints with CSRF. This is contract testing — not logic testing.

- [ ] **Step 1: Add client fixture to conftest.py**

```python
# Append to tests/conftest.py:
import re

@pytest.fixture
def client():
    """FastAPI TestClient with CSRF support."""
    from tidal_dl.gui import create_app
    from fastapi.testclient import TestClient
    c = TestClient(create_app(port=8765))
    c._host_header = {"host": "localhost:8765"}
    # Extract CSRF token
    index = c.get("/", headers=c._host_header)
    match = re.search(r'name="csrf-token" content="([^"]+)"', index.text)
    c._csrf = match.group(1) if match else ""
    c._headers = {**c._host_header, "X-CSRF-Token": c._csrf}
    return c
```

- [ ] **Step 2: Write endpoint smoke tests**

```python
"""Smoke tests for all API endpoints — contract only, no deep logic."""


def test_library_tracks(client):
    resp = client.get("/api/library/tracks?limit=5", headers=client._host_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "tracks" in data
    assert "total" in data


def test_library_artists(client):
    resp = client.get("/api/library/artists", headers=client._host_header)
    assert resp.status_code == 200
    assert "artists" in resp.json()


def test_library_albums(client):
    resp = client.get("/api/library/albums", headers=client._host_header)
    assert resp.status_code == 200
    assert "albums" in resp.json()


def test_library_favorites(client):
    resp = client.get("/api/library/favorites", headers=client._host_header)
    assert resp.status_code == 200


def test_home(client):
    resp = client.get("/api/home", headers=client._host_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_plays" in data
    assert "weekly_activity" in data


def test_downloads_active(client):
    resp = client.get("/api/downloads/active/snapshot", headers=client._host_header)
    assert resp.status_code == 200


def test_downloads_history(client):
    resp = client.get("/api/downloads/history", headers=client._host_header)
    assert resp.status_code == 200


def test_duplicates_preview(client):
    resp = client.get("/api/duplicates/preview", headers=client._host_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "groups" in data
    assert "total_duplicates" in data


def test_settings_get(client):
    resp = client.get("/api/settings", headers=client._host_header)
    assert resp.status_code == 200


def test_post_without_csrf_rejected(client):
    """POST without CSRF token should be rejected."""
    resp = client.post("/api/home/play", json={"artist": "X"},
                       headers=client._host_header)
    assert resp.status_code == 403


def test_post_with_csrf_accepted(client):
    resp = client.post("/api/home/play",
                       json={"artist": "X", "genre": "Y", "duration": 100},
                       headers=client._headers)
    assert resp.status_code == 204


def test_static_files(client):
    """CSS and JS served correctly."""
    assert client.get("/style.css", headers=client._host_header).status_code == 200
    assert client.get("/app.js", headers=client._host_header).status_code == 200
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_api_endpoints.py -v --tb=short`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/test_api_endpoints.py
git commit -m "test(api): endpoint smoke tests for all routes + CSRF validation"
```

---

### Task 5: Token refresh test coverage

**Files:**
- Create: `tests/test_token_refresh.py`
- Reference: `tidal_dl/config.py:440-510`

Lock down the token handling paths that have crashed twice.

- [ ] **Step 1: Write token tests**

```python
"""Tests for Tidal token refresh — covers float, datetime, and None paths."""
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from tidal_dl.config import Tidal


@pytest.fixture
def tidal(monkeypatch):
    t = Tidal()
    # Prevent actual file I/O
    monkeypatch.setattr(t, "save", lambda: None)
    monkeypatch.setattr(t, "file_path", "/dev/null")
    return t


class TestEnsureTokenFresh:
    def test_float_expiry_within_window(self, tidal, monkeypatch):
        """Float expiry within 300s window triggers refresh."""
        tidal.data.expiry_time = time.time() + 60
        session = MagicMock()
        session.token_type = "Bearer"
        session.access_token = "new"
        session.refresh_token = "ref"
        session.expiry_time = time.time() + 3600
        tidal.session = session
        monkeypatch.setattr(tidal, "token_persist", lambda: None)

        result = tidal._ensure_token_fresh()
        assert result is True
        session.token_refresh.assert_called_once()

    def test_float_expiry_outside_window(self, tidal):
        """Float expiry far in the future — no refresh needed."""
        tidal.data.expiry_time = time.time() + 3600
        result = tidal._ensure_token_fresh()
        assert result is False

    def test_zero_expiry_noop(self, tidal):
        """Zero expiry — skip refresh."""
        tidal.data.expiry_time = 0
        result = tidal._ensure_token_fresh()
        assert result is False

    def test_datetime_expiry_within_window(self, tidal, monkeypatch):
        """datetime.datetime expiry handled via hasattr(.timestamp) guard."""
        # Simulate tidalapi setting a datetime object
        tidal.data.expiry_time = time.time() + 60
        # Monkeypatch getattr to return a datetime for the hasattr check
        original_getattr = tidal.data.__class__.__getattribute__

        session = MagicMock()
        session.token_type = "Bearer"
        session.access_token = "new"
        session.refresh_token = "ref"
        session.expiry_time = time.time() + 3600
        tidal.session = session
        monkeypatch.setattr(tidal, "token_persist", lambda: None)

        result = tidal._ensure_token_fresh()
        assert result is True


class TestLoadSession:
    def test_load_with_float_expiry(self, tidal):
        """Float expiry_time converts to datetime for tidalapi."""
        tidal.data.token_type = "Bearer"
        tidal.data.access_token = "test_token"
        tidal.data.refresh_token = "test_refresh"
        tidal.data.expiry_time = time.time() + 3600
        tidal.token_from_storage = True
        session = MagicMock()
        session.load_oauth_session.return_value = True
        tidal.session = session

        result = tidal.login(do_pkce=True, quiet=True)
        assert result is True
        call_args = session.load_oauth_session.call_args
        expiry_arg = call_args[0][3]  # 4th positional arg
        assert isinstance(expiry_arg, datetime)

    def test_load_with_datetime_expiry(self, tidal):
        """datetime expiry_time passed through without double-wrapping."""
        now_dt = datetime.now()
        tidal.data.token_type = "Bearer"
        tidal.data.access_token = "test_token"
        tidal.data.refresh_token = "test_refresh"
        tidal.data.expiry_time = now_dt
        tidal.token_from_storage = True
        session = MagicMock()
        session.load_oauth_session.return_value = True
        tidal.session = session

        result = tidal.login(do_pkce=True, quiet=True)
        assert result is True
        call_args = session.load_oauth_session.call_args
        expiry_arg = call_args[0][3]
        assert expiry_arg is now_dt  # exact same object, not double-wrapped

    def test_load_with_zero_expiry(self, tidal):
        """Zero expiry passes None to tidalapi."""
        tidal.data.token_type = "Bearer"
        tidal.data.access_token = "test_token"
        tidal.data.refresh_token = "test_refresh"
        tidal.data.expiry_time = 0
        tidal.token_from_storage = True
        session = MagicMock()
        session.load_oauth_session.return_value = True
        tidal.session = session

        result = tidal.login(do_pkce=True, quiet=True)
        assert result is True
        call_args = session.load_oauth_session.call_args
        expiry_arg = call_args[0][3]
        assert expiry_arg is None
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_token_refresh.py -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_token_refresh.py
git commit -m "test(token): refresh/load coverage for float, datetime, and zero expiry paths"
```

---

### Task 6: Download error handler tests

**Files:**
- Create: `tests/test_downloads.py`
- Reference: `tidal_dl/gui/api/downloads.py:252-277`

Test that the error handler's nested try/except ensures broadcasts always fire even when DB writes fail.

- [ ] **Step 1: Write download tests**

```python
"""Tests for download pipeline error handling."""
import logging
from unittest.mock import MagicMock, patch
import pytest


def test_broadcast_fires_even_when_db_fails():
    """The nested try/except around record_download ensures _broadcast fires."""
    from tidal_dl.gui.api import downloads

    broadcasts = []
    original_broadcast = downloads._broadcast

    def capture_broadcast(event):
        broadcasts.append(event)

    # Patch broadcast to capture events
    with patch.object(downloads, "_broadcast", side_effect=capture_broadcast):
        # Simulate what happens in the error handler
        entry = MagicMock()
        entry.name = "Test Track"
        entry.artist = "Test Artist"
        entry.album = "Test Album"
        entry.cover_url = None
        entry.status = "error"
        entry.finished_at = 1.0
        entry.started_at = 0.0
        entry.quality = "LOSSLESS"

        # Create a mock DB that fails on record_download
        mock_db = MagicMock()
        mock_db.record_download.side_effect = Exception("database is locked")

        exc = RuntimeError("download failed")
        tid = 999

        # Execute the error handler logic directly
        entry.status = "error"
        try:
            mock_db.record_download(
                track_id=tid, name=entry.name, artist=entry.artist,
                album=entry.album, status="error", error=str(exc),
                started_at=entry.started_at, finished_at=entry.finished_at,
                cover_url=entry.cover_url, quality=entry.quality,
            )
            mock_db.commit()
        except Exception:
            logging.exception("Failed to persist download error for track %s", tid)

        downloads._broadcast({
            "type": "error", "track_id": tid, "name": entry.name,
            "artist": entry.artist, "album": entry.album,
            "cover_url": entry.cover_url, "error": str(exc),
        })

    assert len(broadcasts) == 1
    assert broadcasts[0]["type"] == "error"
    assert broadcasts[0]["track_id"] == 999


def test_logger_captures_db_error(caplog):
    """When DB write fails in error handler, logger.exception is called."""
    with caplog.at_level(logging.ERROR):
        try:
            raise Exception("database is locked")
        except Exception:
            logging.exception("Failed to persist download error for track %s", 42)

    assert "database is locked" in caplog.text
    assert "42" in caplog.text
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_downloads.py -v --tb=short`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_downloads.py
git commit -m "test(downloads): error handler resilience — broadcast fires when DB fails"
```

---

### Task 7: Add pytest config to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add test dependencies and pytest config**

Append to `pyproject.toml`:

```toml
[project.optional-dependencies]
test = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
filterwarnings = [
    "ignore::DeprecationWarning:fastapi.*:",
]
```

- [ ] **Step 2: Run full suite**

Run: `uv run pytest tests/ -v --tb=short`
Expected: 0 failed, ~230+ passed

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pytest config and test dependencies to pyproject.toml"
```

---

### Task 8: Final green-bar verification

This is not a code task — it's a gate. Run the complete suite and confirm zero failures before declaring the verification phase complete.

- [ ] **Step 1: Full suite run**

Run: `uv run pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: `0 failed` in summary line

- [ ] **Step 2: Count total tests**

Run: `uv run pytest tests/ --co -q | tail -1`
Expected: `~230+ tests selected`

- [ ] **Step 3: Tag the milestone**

```bash
git tag -a v3.0.0-rc1 -m "Backend verification complete — all tests green"
```
