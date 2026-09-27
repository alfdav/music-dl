"""Playlist-click load path: stage timings and first-page budget.

The GUI click handler awaits GET /playlists/{id}/tracks before painting rows.
These tests use a Tidal double that pages at 50 items with 150–300 ms of
latency per HTTP-equivalent call, matching live playlist endpoints.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_gui_playlist_local_preference import (
    _fake_track,
    _FakePlaylistDB,
    _patch_playlist_library_db,
)


def _playlist_perf_artifacts(tmp_path: Path) -> Path:
    return Path(os.environ.get("PLAYLIST_PERF_ARTIFACTS") or tmp_path)


PAGE_SIZE = 50
LATENCY_SEC = 0.20
NAS_STAT_SEC = 0.015


def _iso(ts: datetime | None = None) -> str:
    value = ts or datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    return value.isoformat()


def _make_tracks(count: int):
    return [
        _fake_track(
            track_id=i + 1,
            isrc=f"ISRC{i:05d}",
            name=f"Song {i + 1}",
            artist="Artist",
            album=f"Album {(i // 12) + 1}",
        )
        for i in range(count)
    ]


class SlowTidalPlaylist:
    """Tidal playlist double: metadata GET + paged /tracks, 50-item cap."""

    def __init__(self, tracks: list, *, latency: float = LATENCY_SEC, page_cap: int = PAGE_SIZE):
        self.id = "pl-slow"
        self.name = "Slow Playlist"
        self.num_tracks = len(tracks)
        self.last_updated = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        self._etag = '"etag-v1"'
        self._all = tracks
        self.latency = latency
        self.page_cap = page_cap
        self.calls: list[tuple] = []
        self._in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def _sleep(self) -> None:
        time.sleep(self.latency)

    def tracks(self, limit=None, offset=0, **_kwargs):
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
            self.calls.append(("tracks", limit, offset, time.perf_counter()))
        try:
            self._sleep()
            cap = self.page_cap
            if limit is None:
                # tidalapi omits None and sends Session.item_limit (10000).
                # Playlist /tracks still caps around 50–100 items.
                limit = cap
            start = max(int(offset or 0), 0)
            size = max(1, min(int(limit), cap))
            return self._all[start : start + size]
        finally:
            with self._lock:
                self._in_flight -= 1


class SlowTidalSession:
    def __init__(self, playlist: SlowTidalPlaylist, *, latency: float = LATENCY_SEC):
        self._playlist = playlist
        self.latency = latency
        self.playlist_calls = 0

    def check_login(self) -> bool:
        return True

    def playlist(self, playlist_id: str):
        self.playlist_calls += 1
        time.sleep(self.latency)
        self._playlist.id = playlist_id
        return self._playlist


class CountingDB(_FakePlaylistDB):
    def __init__(self, rows_by_isrc=None, all_rows=None, *, nas_stat_sec: float = 0.0):
        super().__init__(rows_by_isrc or {}, all_rows=all_rows)
        self.all_tracks_calls = 0
        self.identity_calls = 0
        self.nas_stat_sec = nas_stat_sec
        self.stat_calls = 0

    def all_tracks(self):
        self.all_tracks_calls += 1
        return super().all_tracks()

    def tracks_for_identity(self, **kwargs):
        self.identity_calls += 1
        isrc = str(kwargs.get("isrc") or "")
        return list(self.rows_by_isrc.get(isrc, []))


def _tidal_wrapper(session: SlowTidalSession):
    return SimpleNamespace(
        session=session,
        data=SimpleNamespace(access_token="a", refresh_token="r"),
        _ensure_token_fresh=lambda refresh_window_sec=300: True,
    )


def _library_rows(tmp_path: Path, count: int, *, files: int = 0) -> list[dict]:
    rows = []
    for i in range(count):
        path = tmp_path / "library" / f"track-{i}.flac"
        if i < files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fLaC")
        rows.append({
            "path": str(path),
            "artist": "Artist",
            "title": f"Song {i + 1}",
            "album": f"Album {(i // 12) + 1}",
            "isrc": f"ISRC{i:05d}",
            "quality": "LOSSLESS",
            "format": "FLAC",
            "codec": "flac",
        })
    return rows


def _patch_nas_stat(monkeypatch, playlists_api, db: CountingDB):
    from tidal_dl.helper import library_reconcile

    real = library_reconcile.present_playable_path

    def slow_present(path, db_arg=None):
        db.stat_calls += 1
        if db.nas_stat_sec:
            time.sleep(db.nas_stat_sec)
        return real(path, db_arg)

    monkeypatch.setattr(library_reconcile, "present_playable_path", slow_present)
    monkeypatch.setattr(
        "tidal_dl.gui.api.playlists.present_playable_path",
        slow_present,
        raising=False,
    )
    return slow_present


def _bind(monkeypatch, playlists_api, session, db):
    monkeypatch.setattr(playlists_api, "get_tidal", lambda: _tidal_wrapper(session))
    _patch_playlist_library_db(monkeypatch, playlists_api, db)
    playlists_api._playlist_tracks_cache.clear()
    if hasattr(playlists_api, "_playlist_meta_cache"):
        playlists_api._playlist_meta_cache.clear()


def _stage_breakdown(playlists_api, playlist_id, **kwargs) -> dict:
    t0 = time.perf_counter()
    data = playlists_api.playlist_tracks(playlist_id, **kwargs)
    total_ms = (time.perf_counter() - t0) * 1000
    timings = dict(getattr(playlists_api, "_last_playlist_timings", {}) or {})
    timings["total_ms"] = total_ms
    timings["returned"] = len(data.get("tracks") or [])
    timings["total"] = data.get("total")
    timings["limit"] = data.get("limit")
    timings["offset"] = data.get("offset")
    timings["has_more"] = data.get("has_more")
    return {"data": data, "timings": timings}


def test_record_baseline_full_load_timings(monkeypatch, clear_singletons, tmp_path):
    """Measure the current click path for 50- and 500-track playlists."""
    from tidal_dl.gui.api import playlists as playlists_api

    rows = _library_rows(tmp_path, 2000, files=80)
    results = {}

    for count in (50, 500):
        playlist = SlowTidalPlaylist(_make_tracks(count))
        session = SlowTidalSession(playlist)
        db = CountingDB(
            {row["isrc"]: [row] for row in rows[: min(count, 80)]},
            all_rows=rows,
            nas_stat_sec=NAS_STAT_SEC,
        )
        _bind(monkeypatch, playlists_api, session, db)
        _patch_nas_stat(monkeypatch, playlists_api, db)

        t0 = time.perf_counter()
        data = playlists_api.playlist_tracks(f"pl-{count}")
        total_ms = (time.perf_counter() - t0) * 1000

        results[str(count)] = {
            "label": f"{count}-track playlist (current full GET)",
            "tidal_playlist_meta_calls": session.playlist_calls,
            "tidal_tracks_calls": len(playlist.calls),
            "tidal_tracks_call_args": playlist.calls,
            "max_in_flight_tracks_calls": playlist.max_in_flight,
            "all_tracks_calls": db.all_tracks_calls,
            "identity_calls": db.identity_calls,
            "nas_stat_calls": db.stat_calls,
            "returned_tracks": len(data.get("tracks") or []),
            "reported_total": data.get("total"),
            "total_ms": round(total_ms, 1),
            "truncated": len(data.get("tracks") or []) < count,
        }

    artifacts = _playlist_perf_artifacts(tmp_path)
    artifacts.mkdir(parents=True, exist_ok=True)
    path = artifacts / "playlist_load_before.json"
    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("\n=== PLAYLIST LOAD BEFORE ===")
    print(json.dumps(results, indent=2, default=str))

    assert results["50"]["total_ms"] > 0
    assert results["500"]["returned_tracks"] >= 50


def test_first_page_returns_under_one_second(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import playlists as playlists_api

    rows = _library_rows(tmp_path, 2000, files=80)
    playlist = SlowTidalPlaylist(_make_tracks(500))
    session = SlowTidalSession(playlist)
    db = CountingDB(
        {row["isrc"]: [row] for row in rows[:80]},
        all_rows=rows,
        nas_stat_sec=NAS_STAT_SEC,
    )
    _bind(monkeypatch, playlists_api, session, db)
    _patch_nas_stat(monkeypatch, playlists_api, db)

    t0 = time.perf_counter()
    data = playlists_api.playlist_tracks(
        "pl-500",
        limit=PAGE_SIZE,
        offset=0,
        last_updated=_iso(),
    )
    elapsed = time.perf_counter() - t0

    assert elapsed < 1.0
    assert data["limit"] == PAGE_SIZE
    assert data["offset"] == 0
    assert data["has_more"] is True
    assert data["total"] == 500
    assert len(data["tracks"]) == PAGE_SIZE
    assert data["tracks"][0]["name"] == "Song 1"
    assert data["tracks"][-1]["name"] == "Song 50"

    after = {
        "500_first_page_ms": round(elapsed * 1000, 1),
        "tidal_playlist_meta_calls": session.playlist_calls,
        "tidal_tracks_calls": len(playlist.calls),
        "all_tracks_calls": db.all_tracks_calls,
        "nas_stat_calls": db.stat_calls,
        "returned_tracks": len(data["tracks"]),
        "reported_total": data["total"],
        "timings": dict(getattr(playlists_api, "_last_playlist_timings", {}) or {}),
    }
    artifacts = _playlist_perf_artifacts(tmp_path)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "playlist_load_after.json").write_text(
        json.dumps(after, indent=2, default=str), encoding="utf-8",
    )
    print("\n=== PLAYLIST LOAD AFTER FIRST PAGE ===")
    print(json.dumps(after, indent=2, default=str))


def test_first_page_does_not_scan_full_library_or_stat_nas(
    monkeypatch, clear_singletons, tmp_path,
):
    from tidal_dl.gui.api import playlists as playlists_api

    rows = _library_rows(tmp_path, 3000, files=10)
    playlist = SlowTidalPlaylist(_make_tracks(500))
    session = SlowTidalSession(playlist)
    db = CountingDB({row["isrc"]: [row] for row in rows[:10]}, all_rows=rows)
    _bind(monkeypatch, playlists_api, session, db)
    _patch_nas_stat(monkeypatch, playlists_api, db)

    playlists_api.playlist_tracks("pl-500", limit=PAGE_SIZE, offset=0)

    assert db.all_tracks_calls == 0
    assert db.stat_calls == 0
    assert session.playlist_calls <= 1
    assert len(playlist.calls) == 1
    assert playlist.calls[0][1] == PAGE_SIZE
    assert playlist.calls[0][2] == 0


def test_remaining_pages_fetch_with_bounded_concurrency(
    monkeypatch, clear_singletons, tmp_path,
):
    from tidal_dl.gui.api import playlists as playlists_api

    playlist = SlowTidalPlaylist(_make_tracks(500), latency=0.15)
    session = SlowTidalSession(playlist, latency=0.15)
    db = CountingDB({})
    _bind(monkeypatch, playlists_api, session, db)

    first = playlists_api.playlist_tracks("pl-500", limit=PAGE_SIZE, offset=0)
    assert first["has_more"] is True

    second = playlists_api.playlist_tracks("pl-500", limit=PAGE_SIZE, offset=PAGE_SIZE)
    assert len(second["tracks"]) == PAGE_SIZE
    assert second["tracks"][0]["name"] == "Song 51"

    full = playlists_api.playlist_tracks("pl-500")
    assert len(full["tracks"]) == 500
    assert full["total"] == 500
    assert playlist.max_in_flight <= 2
    assert len(playlist.calls) >= 10


def test_cache_uses_last_updated_and_etag_invalidation(
    monkeypatch, clear_singletons, tmp_path,
):
    from tidal_dl.gui.api import playlists as playlists_api

    playlist = SlowTidalPlaylist(_make_tracks(50), latency=0.05)
    session = SlowTidalSession(playlist, latency=0.05)
    db = CountingDB({})
    _bind(monkeypatch, playlists_api, session, db)

    first = playlists_api.playlist_tracks(
        "pl-cache", limit=PAGE_SIZE, offset=0, last_updated=_iso(),
    )
    meta_calls = session.playlist_calls
    track_calls = len(playlist.calls)

    cached = playlists_api.playlist_tracks(
        "pl-cache", limit=PAGE_SIZE, offset=0, last_updated=_iso(),
    )
    assert cached["tracks"][0]["id"] == first["tracks"][0]["id"]
    assert session.playlist_calls == meta_calls
    assert len(playlist.calls) == track_calls

    playlist.last_updated = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    playlist._etag = '"etag-v2"'
    playlist._all[0] = _fake_track(track_id=99, isrc="ISRC00000", name="Replaced")

    refreshed = playlists_api.playlist_tracks(
        "pl-cache",
        limit=PAGE_SIZE,
        offset=0,
        last_updated=_iso(playlist.last_updated),
    )
    assert refreshed["tracks"][0]["name"] == "Replaced"
    assert len(playlist.calls) > track_calls


def test_paginated_first_page_stamps_local_path_without_nas(
    monkeypatch, clear_singletons, tmp_path,
):
    from tidal_dl.gui.api import playlists as playlists_api

    rows = _library_rows(tmp_path, 3, files=3)
    playlist = SlowTidalPlaylist(_make_tracks(3), latency=0.0)
    session = SlowTidalSession(playlist, latency=0.0)
    db = CountingDB({row["isrc"]: [row] for row in rows}, all_rows=rows)
    _bind(monkeypatch, playlists_api, session, db)
    _patch_nas_stat(monkeypatch, playlists_api, db)

    data = playlists_api.playlist_tracks("pl-local", limit=PAGE_SIZE, offset=0)
    track = data["tracks"][0]

    assert track["is_local"] is True
    assert track["local_path"] == rows[0]["path"]
    assert track["path"] == rows[0]["path"]
    assert db.stat_calls == 0
    assert db.all_tracks_calls == 0


def test_client_total_hint_cannot_inflate_tidal_page_fetches(
    monkeypatch, clear_singletons,
):
    from tidal_dl.gui.api import playlists as playlists_api

    playlist = SlowTidalPlaylist(_make_tracks(3), latency=0.0)
    session = SlowTidalSession(playlist, latency=0.0)
    _bind(monkeypatch, playlists_api, session, CountingDB({}))

    first = playlists_api.playlist_tracks(
        "pl-inflate", limit=PAGE_SIZE, offset=0, total=1_000_000,
    )
    assert first["total"] == 3
    assert first["has_more"] is False
    first_calls = len(playlist.calls)

    full = playlists_api.playlist_tracks("pl-inflate", total=1_000_000)
    assert len(full["tracks"]) == 3
    assert full["total"] == 3
    assert len(playlist.calls) - first_calls <= 2


def test_paginated_tracks_keep_catalog_fields_without_catalog_stash(
    monkeypatch, clear_singletons,
):
    from tidal_dl.gui.api import playlists as playlists_api

    playlist = SlowTidalPlaylist(_make_tracks(3), latency=0.0)
    session = SlowTidalSession(playlist, latency=0.0)
    _bind(monkeypatch, playlists_api, session, CountingDB({}))

    data = playlists_api.playlist_tracks("pl-fields", limit=PAGE_SIZE, offset=0)
    track = data["tracks"][0]
    assert track["id"] == 1
    assert track["name"] == "Song 1"
    assert track["artist"] == "Artist"
    assert track["album"] == "Album 1"
    assert track["cover_url"] == "cover-url"
    assert track["isrc"] == "ISRC00000"
    assert "_catalog_quality" not in track
    assert "playable" not in track


def test_static_js_playlist_first_page_and_skeleton():
    from tests.gui_js_source import read_gui_js

    js = read_gui_js()
    body = js.split("async function loadPlaylistTracks")[1].split(
        "// ---- DOWNLOAD TRIGGER ----"
    )[0]
    assert "function loadPlaylistTracks(" in js
    assert "renderPlaylistTrackSkeleton" in body
    assert "playlistTracksUrl" in body
    assert "PLAYLIST_PAGE_SIZE" in js
    assert "tracks-virtual" in js
    assert "skeleton-track" in js


class RateLimitedPlaylist(SlowTidalPlaylist):
    """Raise TooManyRequests once on a remaining page, then succeed."""

    def __init__(self, tracks: list, *, fail_offset: int = PAGE_SIZE, retry_after: int = 2, **kwargs):
        super().__init__(tracks, **kwargs)
        self.fail_offset = fail_offset
        self.retry_after = retry_after
        self.rate_limit_raises = 0
        self.attempts_by_offset: dict[int, int] = {}

    def tracks(self, limit=None, offset=0, **_kwargs):
        from tidalapi.exceptions import TooManyRequests

        off = int(offset or 0)
        with self._lock:
            self.attempts_by_offset[off] = self.attempts_by_offset.get(off, 0) + 1
            attempt = self.attempts_by_offset[off]
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
            self.calls.append(("tracks", limit, off, time.perf_counter()))
        try:
            if off == self.fail_offset and attempt == 1:
                self.rate_limit_raises += 1
                raise TooManyRequests("Too many requests", retry_after=self.retry_after)
            self._sleep()
            cap = self.page_cap
            size = cap if limit is None else max(1, min(int(limit), cap))
            start = max(off, 0)
            return self._all[start : start + size]
        finally:
            with self._lock:
                self._in_flight -= 1


def test_remaining_pages_back_off_on_tidal_429(monkeypatch, clear_singletons, tmp_path):
    """Concurrency-2 remaining pages must honor Tidal 429 instead of retrying hard."""
    from tidal_dl.download.api_pacing import reset_shared_pacer_for_tests, shared_pacer
    from tidal_dl.gui.api import playlists as playlists_api

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(float(seconds)))
    reset_shared_pacer_for_tests()

    playlist = RateLimitedPlaylist(_make_tracks(150), latency=0.0, retry_after=2)
    session = SlowTidalSession(playlist, latency=0.0)
    _bind(monkeypatch, playlists_api, session, CountingDB({}))

    first = playlists_api.playlist_tracks("pl-429", limit=PAGE_SIZE, offset=0)
    assert first["has_more"] is True
    assert playlist.rate_limit_raises == 0

    full = playlists_api.playlist_tracks("pl-429")
    pacer = shared_pacer()

    assert len(full["tracks"]) == 150
    assert playlist.rate_limit_raises == 1
    assert playlist.attempts_by_offset[PAGE_SIZE] >= 2
    assert sleeps
    assert any(wait >= 2 for wait in sleeps)
    assert pacer.rate_limit_hits >= 1
    assert playlist.max_in_flight <= 2


class AlwaysLimitedPlaylist(SlowTidalPlaylist):
    def tracks(self, limit=None, offset=0, **_kwargs):
        from tidalapi.exceptions import TooManyRequests

        off = int(offset or 0)
        with self._lock:
            self.attempts_by_offset[off] = self.attempts_by_offset.get(off, 0) + 1
            self.rate_limit_raises += 1
        raise TooManyRequests("Too many requests", retry_after=1)


def test_playlist_429_retries_are_capped(monkeypatch, clear_singletons):
    from fastapi import HTTPException

    from tidal_dl.download.api_pacing import reset_shared_pacer_for_tests
    from tidal_dl.gui.api import playlists as playlists_api

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(float(seconds)))
    reset_shared_pacer_for_tests()
    playlist = AlwaysLimitedPlaylist(_make_tracks(3), latency=0.0)
    playlist.rate_limit_raises = 0
    playlist.attempts_by_offset = {}
    session = SlowTidalSession(playlist, latency=0.0)
    _bind(monkeypatch, playlists_api, session, CountingDB({}))

    with pytest.raises(HTTPException) as caught:
        playlists_api.playlist_tracks("pl-429-cap", limit=PAGE_SIZE, offset=0)

    assert caught.value.status_code == 429
    assert caught.value.detail == "Tidal rate limit; playlist tracks paused"
    attempts = playlist.attempts_by_offset[0]
    assert attempts == playlists_api._PLAYLIST_429_RETRIES + 1
    assert sum(1 for wait in sleeps if wait == 1.0) == playlists_api._PLAYLIST_429_RETRIES


class LaterPageBlockedPlaylist(SlowTidalPlaylist):
    """Succeed on the first page, then 429 every later page until unblocked."""

    def __init__(self, tracks: list, **kwargs):
        super().__init__(tracks, **kwargs)
        self.block_from = PAGE_SIZE
        self.blocked = True
        self.attempts_by_offset: dict[int, int] = {}

    def tracks(self, limit=None, offset=0, **_kwargs):
        from tidalapi.exceptions import TooManyRequests

        off = int(offset or 0)
        with self._lock:
            self.attempts_by_offset[off] = self.attempts_by_offset.get(off, 0) + 1
        if self.blocked and off >= self.block_from:
            raise TooManyRequests("Too many requests", retry_after=1)
        return super().tracks(limit=limit, offset=offset)


def test_later_page_429_keeps_cached_pages_for_resume(monkeypatch, clear_singletons):
    """A 429 on page 2 must stay HTTP 429 and leave page 1 cached so the client can resume."""
    from fastapi import HTTPException

    from tidal_dl.download.api_pacing import reset_shared_pacer_for_tests
    from tidal_dl.gui.api import playlists as playlists_api

    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    reset_shared_pacer_for_tests()
    playlist = LaterPageBlockedPlaylist(_make_tracks(120), latency=0.0)
    session = SlowTidalSession(playlist, latency=0.0)
    _bind(monkeypatch, playlists_api, session, CountingDB({}))

    first = playlists_api.playlist_tracks("pl-429-later", limit=PAGE_SIZE, offset=0)
    assert len(first["tracks"]) == PAGE_SIZE
    assert first["has_more"] is True
    assert first["total"] == 120
    first_attempts = playlist.attempts_by_offset[0]

    with pytest.raises(HTTPException) as caught:
        playlists_api.playlist_tracks("pl-429-later", limit=PAGE_SIZE, offset=PAGE_SIZE)
    assert caught.value.status_code == 429

    again = playlists_api.playlist_tracks("pl-429-later", limit=PAGE_SIZE, offset=0)
    assert len(again["tracks"]) == PAGE_SIZE
    assert again["has_more"] is True
    assert again["tracks"][0]["id"] == first["tracks"][0]["id"]
    assert playlist.attempts_by_offset[0] == first_attempts

    playlist.blocked = False
    resumed = playlists_api.playlist_tracks(
        "pl-429-later", limit=PAGE_SIZE, offset=PAGE_SIZE,
    )
    assert len(resumed["tracks"]) == PAGE_SIZE
    assert resumed["has_more"] is True
    assert resumed["offset"] == PAGE_SIZE


def test_first_page_stamp_does_not_touch_the_filesystem(monkeypatch, clear_singletons, tmp_path):
    """Owned display match is ISRC → indexed path. Any stat fails the test."""
    import os
    from pathlib import Path

    from tidal_dl.gui.api import playlists as playlists_api

    rows = _library_rows(tmp_path, 3, files=0)
    playlist = SlowTidalPlaylist(_make_tracks(3), latency=0.0)
    session = SlowTidalSession(playlist, latency=0.0)
    db = CountingDB({row["isrc"]: [row] for row in rows}, all_rows=rows)
    _bind(monkeypatch, playlists_api, session, db)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("filesystem check on playlist first-page stamp")

    monkeypatch.setattr(os, "stat", _boom)
    monkeypatch.setattr(Path, "exists", _boom)
    monkeypatch.setattr(Path, "is_file", _boom)
    try:
        data = playlists_api.playlist_tracks("pl-nostat", limit=PAGE_SIZE, offset=0)
    finally:
        monkeypatch.undo()

    assert data["tracks"][0]["is_local"] is True
    assert data["tracks"][0]["path"] == rows[0]["path"]
    assert data["tracks"][0]["local_path"] == rows[0]["path"]
    assert db.identity_calls == 0


def test_first_page_stamp_stays_fast_on_a_large_library(monkeypatch, clear_singletons, tmp_path):
    """A few thousand indexed rows must not turn a 50-track page into seconds."""
    from tidal_dl.gui.api import playlists as playlists_api
    from tidal_dl.helper.library_db import LibraryDB

    db_path = tmp_path / "library.db"
    db = LibraryDB(db_path)
    db.open()
    now = int(time.time())
    extra = []
    for i in range(15_000):
        extra.append((
            f"/Volumes/Music/Artist/Album/extra-{i}.flac",
            f"LIB{i:05d}",
            "scanned",
            "Artist",
            f"Library Song {i}",
            "Album",
            "LOSSLESS",
            "FLAC",
            "flac",
            now,
        ))
    owned = []
    for i in range(50):
        owned.append((
            f"/Volumes/Music/Artist/Album/owned-{i}.flac",
            f"ISRC{i:05d}",
            "scanned",
            "Artist",
            f"Song {i + 1}",
            f"Album {(i // 12) + 1}",
            "LOSSLESS",
            "FLAC",
            "flac",
            now,
        ))
    db._conn.executemany(
        """INSERT INTO scanned
           (path, isrc, status, artist, title, album, quality, format, codec, scanned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        extra + owned,
    )
    db._conn.commit()

    playlist = SlowTidalPlaylist(_make_tracks(50), latency=0.0)
    session = SlowTidalSession(playlist, latency=0.0)
    monkeypatch.setattr(playlists_api, "get_tidal", lambda: _tidal_wrapper(session))
    monkeypatch.setattr(playlists_api, "_get_playlist_db", lambda: db)
    playlists_api._playlist_tracks_cache.clear()

    t0 = time.perf_counter()
    data = playlists_api.playlist_tracks("pl-big", limit=PAGE_SIZE, offset=0)
    elapsed = time.perf_counter() - t0
    db.close()

    assert elapsed < 0.5
    assert len(data["tracks"]) == 50
    assert data["tracks"][0]["local_path"] == "/Volumes/Music/Artist/Album/owned-0.flac"
    assert data["tracks"][0]["is_local"] is True
