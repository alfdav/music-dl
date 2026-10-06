"""Playlist sync core. Fakes only: no network, no real names, no tokens."""

from __future__ import annotations

import ast
import json
import os
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tidal_dl.download.api_pacing import TidalApiPacer
from tidal_dl.model.cfg import Settings as ModelSettings
from tidal_dl.playlist_sync.config import PlaylistSyncConfig, load_config, name_allowed
from tidal_dl.playlist_sync.cycle import library_candidates, run_cycle
from tidal_dl.playlist_sync.downloads import JobServiceDownloader
from tidal_dl.playlist_sync.ledger import Ledger, default_ledger_path
from tidal_dl.playlist_sync.matcher import normalize_playlist_name, normalize_title, same_recording
from tidal_dl.playlist_sync.models import Candidate, DownloadResult, PlaylistRef, Track
from tidal_dl.playlist_sync.mount import download_path_available
from tidal_dl.playlist_sync.unicode_norm import apply_prefix_map, nfc_path
from tidal_dl.playlist_sync.verify import markers_in, verify

ARTIST = "Example Artist"
OTHER = "Other Artist"


def _wall(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """Local wall clock. The daily cap uses this calendar date."""
    local_tz = datetime.now(UTC).astimezone().tzinfo
    return datetime(year, month, day, hour, minute, second, tzinfo=local_tz)


def _cfg(**kwargs) -> PlaylistSyncConfig:
    values = {
        "enabled": True,
        "dry_run": False,
        "poll_minutes": 15,
        "max_per_cycle": 5,
        "max_per_day": 30,
        "gap_sec_min": 30,
        "gap_sec_max": 60,
        "allowlist": (),
    }
    values.update(kwargs)
    return PlaylistSyncConfig(**values)


def _track(
    source: str,
    track_id: str,
    title: str,
    *,
    artist: str = ARTIST,
    duration: float | None = 180,
    isrc: str | None = None,
    available: bool = True,
    album: str = "",
    version: str = "",
    playlist_name: str = "Playlist A",
) -> Track:
    return Track(
        source=source,
        source_track_id=str(track_id),
        title=title,
        artist=artist,
        album=album,
        duration=duration,
        isrc=isrc,
        available=available,
        version=version,
        playlist_name=playlist_name,
    )


def _playlist(source: str, playlist_id: str, name: str, updated: str | None, count: int = 0) -> PlaylistRef:
    return PlaylistRef(
        source=source,
        source_playlist_id=playlist_id,
        name=name,
        last_updated=updated,
        num_tracks=count,
    )


def _candidate(title: str, *, artist: str = ARTIST, duration: float | None = 180, isrc: str | None = None,
               album: str = "", version: str = "", ident: str = "c1", path: str = "") -> Candidate:
    return Candidate(
        id=ident,
        title=title,
        artist=artist,
        duration=duration,
        isrc=isrc,
        album=album,
        version=version,
        path=path,
    )


class _Source:
    def __init__(self, name: str, playlists: list[tuple[PlaylistRef, list[Track]]]):
        self.name = name
        self._rows = {item[0].source_playlist_id: (item[0], list(item[1])) for item in playlists}
        self.track_calls: list[str] = []

    def list_playlists(self) -> list[PlaylistRef]:
        return [row[0] for row in self._rows.values()]

    def list_tracks(self, playlist: PlaylistRef) -> list[Track]:
        self.track_calls.append(playlist.source_playlist_id)
        return list(self._rows[playlist.source_playlist_id][1])

    def set_tracks(self, playlist_id: str, tracks: list[Track], updated: str) -> None:
        current = self._rows[playlist_id][0]
        self._rows[playlist_id] = (
            PlaylistRef(
                current.source,
                current.source_playlist_id,
                current.name,
                updated,
                len(tracks),
            ),
            list(tracks),
        )


class _Sink:
    def __init__(self, tracks: list[Track] | None = None, found: list[Track] | None = None):
        self.rows = list(tracks or [])
        self.found = list(found or [])
        self.appends: list[tuple[str, list[str]]] = []
        self.find_calls: list[str] = []

    def list_tracks(self, name: str) -> list[Track]:
        return list(self.rows)

    def append(self, name: str, tracks: list[Track]) -> None:
        self.appends.append((name, [track.source_track_id for track in tracks]))
        self.rows.extend(tracks)

    def find(self, track: Track) -> list[Track]:
        self.find_calls.append(track.source_track_id)
        return list(self.found)


class _Downloads:
    def __init__(self, outcomes: dict[int, DownloadResult] | None = None):
        self.calls: list[list[int]] = []
        self.depth = 0
        self.max_depth = 0
        self.events: list[str] = []
        self.outcomes = outcomes or {}

    def enqueue_download(self, track_ids: list[int]) -> dict:
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        self.events.append("enqueue")
        self.calls.append(list(track_ids))
        return {"status": "queued", "count": len(track_ids)}

    def wait_for(self, track_id: int) -> DownloadResult:
        self.events.append("wait")
        self.depth -= 1
        return self.outcomes.get(
            track_id,
            DownloadResult(status="completed", path=f"/music/{track_id}.flac"),
        )


class _ClockRng:
    def __init__(self) -> None:
        self.sleeps: list[float] = []
        self.bounds: list[tuple[float, float]] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def uniform(self, low: float, high: float) -> float:
        self.bounds.append((low, high))
        return 45

    def clock(self) -> float:
        return 0.0


def _tags_for(tracks: list[Track]):
    by_id = {track.source_track_id: track for track in tracks}

    def reader(path: str) -> dict:
        item = by_id[Path(path).stem]
        return {
            "title": item.title,
            "artist": item.artist,
            "album": item.album,
            "duration": item.duration,
            "isrc": item.isrc,
            "version": item.version,
        }

    return reader


def _run(tmp_path: Path, source: _Source, *, sink=None, downloads=None, library=None, search=None,
         tag_reader=None, settings=None, now=None, rng=None, auth=None, ledger=None,
         download_path_ready=None, path_prefixes=None, file_exists=None):
    pacing = _ClockRng() if rng is None else rng
    store = ledger or Ledger(tmp_path / "playlist_sync.db")
    report = run_cycle(
        now or _wall(2026, 10, 6, 12),
        settings=settings or _cfg(),
        sources=[source] if not isinstance(source, list) else source,
        sink=sink or _Sink(),
        ledger=store,
        downloads=downloads or _Downloads(),
        library=library or (lambda _track: []),
        search=search,
        tag_reader=tag_reader,
        clock=pacing.clock,
        rng=pacing,
        sleep=pacing.sleep,
        pacer=TidalApiPacer(delay_min=0, delay_max=0, sleeper=pacing.sleep, clock=pacing.clock),
        auth_state=auth or (lambda: "credentials_ready"),
        download_path_ready=download_path_ready or (lambda _path: True),
        path_prefixes=path_prefixes,
        file_exists=file_exists,
    )
    return report, store, pacing


def test_settings_defaults_are_safe():
    data = ModelSettings()
    assert data.playlist_sync_enabled is False
    assert data.playlist_sync_dry_run is True
    assert data.playlist_sync_poll_minutes == 15
    assert data.playlist_sync_max_per_cycle == 5
    assert data.playlist_sync_max_per_day == 30
    assert data.playlist_sync_gap_sec_min == 30.0
    assert data.playlist_sync_gap_sec_max == 60.0
    assert data.playlist_sync_allowlist == []
    loaded = load_config(data)
    assert loaded.enabled is False
    assert loaded.dry_run is True
    assert loaded.allowlist == ()


def test_disabled_cycle_does_no_work(tmp_path: Path):
    report = run_cycle(settings=PlaylistSyncConfig(), ledger=Ledger(tmp_path / "playlist_sync.db"))
    assert report.halted_reason == "disabled"
    assert report.playlists == []
    assert report.to_dict()["halted_reason"] == "disabled"


def test_settings_allowlist_loads_from_json():
    raw = {"playlist_sync_allowlist": ["Playlist A", "Playlist B", 3, None]}
    loaded = ModelSettings.from_dict(raw)
    assert loaded.playlist_sync_allowlist == ["Playlist A", "Playlist B"]
    parsed = ModelSettings.from_json(json.dumps({"playlist_sync_allowlist": ["Playlist A", "Playlist B"]}))
    assert parsed.playlist_sync_allowlist == ["Playlist A", "Playlist B"]
    fallback = ModelSettings.from_dict({"playlist_sync_allowlist": "Playlist A", "playlist_sync_max_per_cycle": "7"})
    assert fallback.playlist_sync_allowlist == []
    assert fallback.playlist_sync_max_per_cycle == 7
    config = load_config(loaded)
    assert config.allowlist == ("Playlist A", "Playlist B")
    assert name_allowed(" playlist a ", config.allowlist)
    assert name_allowed("Playlist B", config.allowlist)
    assert not name_allowed("Playlist C", config.allowlist)


def test_allowlist_comes_from_settings(tmp_path: Path):
    tidal_a = _track("tidal", "1001", "Example Song", isrc="XX0000000001")
    tidal_b = _track("tidal", "1002", "Other Song", isrc="XX0000000002", playlist_name="Playlist B")
    source = _Source(
        "tidal",
        [
            (_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [tidal_a]),
            (_playlist("tidal", "pl-b", "Playlist B", "2026-01-01"), [tidal_b]),
        ],
    )
    downloads = _Downloads()
    report, _, _ = _run(
        tmp_path,
        source,
        downloads=downloads,
        tag_reader=_tags_for([tidal_a, tidal_b]),
        settings=_cfg(allowlist=(" Playlist A ",)),
    )
    assert source.track_calls == ["pl-a"]
    assert [call[0] for call in downloads.calls] == [1001]
    assert [item.name for item in report.playlists] == ["Playlist A"]

    source.track_calls.clear()
    downloads.calls.clear()
    empty = _Source(
        "tidal",
        [
            (_playlist("tidal", "pl-a", "Playlist A", "2026-01-02"), [tidal_a]),
            (_playlist("tidal", "pl-b", "Playlist B", "2026-01-02"), [tidal_b]),
        ],
    )
    report, _, _ = _run(
        tmp_path / "all",
        empty,
        downloads=_Downloads(),
        tag_reader=_tags_for([tidal_a, tidal_b]),
        settings=_cfg(allowlist=()),
    )
    assert {item.name for item in report.playlists} == {"Playlist A", "Playlist B"}


def test_dry_run_counts_tracks_deferred_by_the_cap(tmp_path: Path):
    rows = [
        _track("tidal", str(1001 + index), f"Example Song {index}", isrc=f"XX{index:010d}", duration=180)
        for index in range(7)
    ]
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), rows)])
    downloads = _Downloads()
    report, _, _ = _run(
        tmp_path,
        source,
        downloads=downloads,
        settings=_cfg(dry_run=True, max_per_cycle=5, max_per_day=30),
    )
    playlist = report.playlists[0]
    deferred = [item for item in playlist.tracks if item.get("status") == "deferred_cap"]
    planned = [item for item in playlist.tracks if item.get("status") != "deferred_cap"]
    assert playlist.to_download == 7
    assert len(planned) == 5
    assert len(deferred) == 2
    assert all(item["action"] == "download" for item in planned)
    assert downloads.calls == []
    assert [item["status"] for item in report.skipped] == ["deferred_cap", "deferred_cap"]


def test_caps_hold_across_playlists_and_reset_at_local_midnight(tmp_path: Path):
    tracks = [
        _track("tidal", str(1000 + index), f"Example Song {index}", isrc=f"XX{index:010d}", duration=180)
        for index in range(40)
    ]
    first = tracks[:20]
    second = tracks[20:]
    source = _Source(
        "tidal",
        [
            (_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), first),
            (_playlist("tidal", "pl-b", "Playlist B", "2026-01-01"), second),
        ],
    )
    downloads = _Downloads()
    sink = _Sink()
    ledger = Ledger(tmp_path / "playlist_sync.db")
    day = _wall(2026, 10, 6, 22)
    seen: list[int] = []
    for _ in range(7):
        before = len(downloads.calls)
        _run(
            tmp_path,
            source,
            sink=sink,
            downloads=downloads,
            tag_reader=_tags_for(tracks),
            now=day,
            ledger=ledger,
            settings=_cfg(max_per_cycle=5, max_per_day=30),
        )
        seen.append(len(downloads.calls) - before)
    assert seen == [5, 5, 5, 5, 5, 5, 0]
    assert len(downloads.calls) == 30
    assert downloads.max_depth == 1
    flat = [call[0] for call in downloads.calls]
    assert len(flat) == len(set(flat))
    assert flat[:5] == [1000, 1001, 1002, 1003, 1004]
    assert 1020 in flat

    _run(
        tmp_path,
        source,
        sink=sink,
        downloads=downloads,
        tag_reader=_tags_for(tracks),
        now=_wall(2026, 10, 7, 0, 5),
        ledger=ledger,
        settings=_cfg(max_per_cycle=5, max_per_day=30),
    )
    assert len(downloads.calls) == 35


def test_one_download_and_gap(tmp_path: Path):
    rows = [
        _track("tidal", "1001", "Example Song", isrc="XX0000000001"),
        _track("tidal", "1002", "Second Song", isrc="XX0000000002"),
        _track("tidal", "1003", "Third Song", isrc="XX0000000003"),
    ]
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), rows)])
    downloads = _Downloads()
    pacing = _ClockRng()
    _run(
        tmp_path,
        source,
        downloads=downloads,
        tag_reader=_tags_for(rows),
        rng=pacing,
        settings=_cfg(max_per_cycle=5),
    )
    assert downloads.max_depth == 1
    assert downloads.events == ["enqueue", "wait", "enqueue", "wait", "enqueue", "wait"]
    assert pacing.sleeps == [45, 45]
    assert pacing.bounds == [(30, 60), (30, 60)]


def test_halts_on_429_401_and_auth_without_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("auth or bulk sync was called")

    import tidal_dl.gui.api.playlists as playlists_api
    import tidal_dl.gui.api.settings as settings_api
    import tidal_dl.gui.services.download_job_service as jobs
    from tidal_dl import cli_sync

    monkeypatch.setattr(playlists_api, "sync_playlist", forbidden, raising=False)
    monkeypatch.setattr(settings_api, "ensure_tidal_logged_in", forbidden, raising=False)
    monkeypatch.setattr(cli_sync, "sync", forbidden, raising=False)
    monkeypatch.setattr(jobs.DownloadJobService, "enqueue_upgrade", forbidden, raising=False)

    rows = [
        _track("tidal", "1001", "Example Song", isrc="XX0000000001"),
        _track("tidal", "1002", "Second Song", isrc="XX0000000002"),
    ]
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), rows)])
    limited = _Downloads(
        {1001: DownloadResult(status="failed", http_status=429, error="429")}
    )
    report, _, _ = _run(tmp_path, source, downloads=limited, tag_reader=_tags_for(rows))
    assert report.halted_reason == "429"
    assert limited.calls == [[1001]]

    unauthorized = _Downloads(
        {1001: DownloadResult(status="failed", http_status=401, error="401")}
    )
    source_401 = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), rows)])
    report, _, _ = _run(
        tmp_path / "auth401",
        source_401,
        downloads=unauthorized,
        tag_reader=_tags_for(rows),
    )
    assert report.halted_reason == "401"
    assert unauthorized.calls == [[1001]]

    report, _, _ = _run(
        tmp_path / "state",
        _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), rows)]),
        downloads=_Downloads(),
        auth=lambda: "expired",
    )
    assert report.halted_reason == "auth_state=expired"
    assert report.downloaded == []


def test_unobtainable_and_failed_retry_once_per_day(tmp_path: Path):
    gone = _track("tidal", "1004", "Gone Song", isrc="XX0000000004", available=False)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [gone])])
    downloads = _Downloads()
    ledger = Ledger(tmp_path / "playlist_sync.db")
    day = _wall(2026, 10, 6, 12)
    for _ in range(2):
        report, _, _ = _run(tmp_path, source, downloads=downloads, ledger=ledger, now=day)
        assert report.playlists[0].unobtainable == 1
    assert downloads.calls == []

    ready = _track("tidal", "1004", "Gone Song", isrc="XX0000000004", available=True)
    source.set_tracks("pl-a", [ready], "2026-01-02")
    _run(
        tmp_path,
        source,
        downloads=downloads,
        ledger=ledger,
        now=_wall(2026, 10, 7, 12),
        tag_reader=_tags_for([ready]),
    )
    assert downloads.calls == [[1004]]

    failed = _track("tidal", "1005", "Retry Song", isrc="XX0000000005")
    fail_source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-02-01"), [failed])])
    fail_dl = _Downloads({1005: DownloadResult(status="failed", error="nope")})
    fail_ledger = Ledger(tmp_path / "fail" / "playlist_sync.db")
    _run(tmp_path / "fail", fail_source, downloads=fail_dl, ledger=fail_ledger, now=day, tag_reader=_tags_for([failed]))
    _run(tmp_path / "fail", fail_source, downloads=fail_dl, ledger=fail_ledger, now=day, tag_reader=_tags_for([failed]))
    assert fail_dl.calls == [[1005]]
    _run(
        tmp_path / "fail",
        fail_source,
        downloads=fail_dl,
        ledger=fail_ledger,
        now=_wall(2026, 10, 7, 8),
        tag_reader=_tags_for([failed]),
    )
    _run(
        tmp_path / "fail",
        fail_source,
        downloads=fail_dl,
        ledger=fail_ledger,
        now=_wall(2026, 10, 7, 9),
        tag_reader=_tags_for([failed]),
    )
    assert fail_dl.calls == [[1005], [1005]]


def test_cache_drops_tracks_removed_from_the_playlist(tmp_path: Path):
    first = _track("tidal", "1001", "Example Song", isrc="XX0000000001")
    second = _track("tidal", "1002", "Second Song", isrc="XX0000000002")
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [first, second])])
    downloads = _Downloads()
    sink = _Sink()
    ledger = Ledger(tmp_path / "playlist_sync.db")
    _run(
        tmp_path,
        source,
        sink=sink,
        downloads=downloads,
        ledger=ledger,
        tag_reader=_tags_for([first, second]),
    )
    assert [call[0] for call in downloads.calls] == [1001, 1002]

    source.set_tracks("pl-a", [first], "2026-01-02")
    refreshed = _Downloads()
    report, _, _ = _run(
        tmp_path,
        source,
        sink=_Sink(),
        downloads=refreshed,
        ledger=ledger,
        tag_reader=_tags_for([first, second]),
    )
    assert source.track_calls == ["pl-a", "pl-a"]
    assert [call[0] for call in refreshed.calls] == [1001]
    assert report.playlists[0].tidal_count == 1

    cached = _Downloads()
    report, _, _ = _run(
        tmp_path,
        source,
        sink=_Sink(),
        downloads=cached,
        ledger=ledger,
        tag_reader=_tags_for([first, second]),
    )
    assert source.track_calls == ["pl-a", "pl-a"]
    assert [call[0] for call in cached.calls] == [1001]
    assert report.playlists[0].tidal_count == 1
    assert [item["source_track"]["title"] for item in report.playlists[0].tracks] == ["Example Song"]


def test_only_changed_playlists_are_fetched(tmp_path: Path):
    one = _track("tidal", "1001", "Example Song", isrc="XX0000000001")
    two = _track("tidal", "1002", "Second Song", isrc="XX0000000002", playlist_name="Playlist B")
    source = _Source(
        "tidal",
        [
            (_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [one]),
            (_playlist("tidal", "pl-b", "Playlist B", "2026-01-01"), [two]),
        ],
    )
    ledger = Ledger(tmp_path / "playlist_sync.db")
    settings = _cfg(dry_run=True)
    _run(tmp_path, source, ledger=ledger, settings=settings)
    _run(tmp_path, source, ledger=ledger, settings=settings)
    assert source.track_calls == ["pl-a", "pl-b"]
    source.set_tracks("pl-a", [one], "2026-02-01")
    _run(tmp_path, source, ledger=ledger, settings=settings)
    assert source.track_calls == ["pl-a", "pl-b", "pl-a"]


def test_dedupe_keys_and_playlist_names():
    left = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    same = _track("apple", "a1", "example song", isrc="xx0000000001", duration=200, artist="EXAMPLE ARTIST")
    other = _track("tidal", "1002", "Example Song", isrc="XX0000000002", duration=180)
    assert same_recording(left, same)
    assert not same_recording(left, other)
    meta = _track("apple", "a2", "Example Song", duration=181, artist="Example Artist feat. Other Artist")
    studio = _track("tidal", "1003", "Example Song", duration=180, isrc=None)
    assert same_recording(meta, studio)
    assert not same_recording(studio, _track("apple", "a3", "Example Song", duration=184, isrc=None))
    assert normalize_playlist_name(" Playlist A ") == normalize_playlist_name("playlist a")


def test_dry_run_reports_without_queue_or_append(tmp_path: Path):
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001")
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])

    class ExplodingDownloads(_Downloads):
        def enqueue_download(self, track_ids: list[int]) -> dict:
            raise AssertionError("dry run queued a download")

    class ExplodingSink(_Sink):
        def append(self, name: str, tracks: list[Track]) -> None:
            raise AssertionError("dry run appended")

    report, _, _ = _run(
        tmp_path,
        source,
        sink=ExplodingSink(),
        downloads=ExplodingDownloads(),
        settings=_cfg(dry_run=True),
    )
    playlist = report.playlists[0]
    assert playlist.to_download == 1
    assert playlist.tracks[0]["action"] == "download"
    assert playlist.tracks[0]["source_track"]["title"] == "Example Song"
    assert playlist.tracks[0]["source_track"]["isrc"] == "XX0000000001"
    json.dumps(report.to_dict())


def test_union_across_tidal_apple_and_plex(tmp_path: Path):
    plex_only = _track("plex", "p1", "Plex Only", isrc="XX0000000001", duration=200)
    shared = _track("plex", "p2", "Shared Song", isrc="XX0000000002", duration=180)
    tidal_shared = _track("tidal", "1002", "Shared Song", isrc="XX0000000002", duration=180)
    local = _track("tidal", "1008", "Local Song", isrc="XX0000000008", duration=190)
    tidal_new = _track("tidal", "1003", "Tidal Song", isrc="XX0000000003", duration=210)
    gone = _track("tidal", "1004", "Gone Song", isrc="XX0000000004", duration=170, available=False)
    apple_shared = _track("apple", "a2", "Shared Song", duration=181, playlist_name="playlist a")
    apple_new = _track("apple", "a6", "Apple Song", duration=220, playlist_name="playlist a")
    ambiguous = _track("apple", "a7", "Ambiguous Song", duration=230, playlist_name="playlist a")
    tidal = _Source(
        "tidal",
        [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [tidal_shared, local, tidal_new, gone])],
    )
    apple = _Source(
        "apple",
        [(_playlist("apple", "ap-a", " playlist a ", "2026-01-01"), [apple_shared, apple_new, ambiguous])],
    )
    sink = _Sink([plex_only, shared])
    downloads = _Downloads()
    local_file = tmp_path / "local.flac"
    local_file.write_bytes(b"local")

    def library(track: Track) -> list[Candidate]:
        if track.isrc == "XX0000000008":
            return [
                _candidate(
                    "Local Song",
                    duration=190,
                    isrc="XX0000000008",
                    ident="row-8",
                    path=str(local_file),
                )
            ]
        return []

    def search(track: Track) -> list[Candidate]:
        if track.title == "Apple Song":
            return [_candidate("Apple Song", duration=220, isrc="XX0000000006", ident="1006")]
        if track.title == "Ambiguous Song":
            return [
                _candidate("Ambiguous Song", duration=230, isrc="XX0000000011", ident="2001"),
                _candidate("Ambiguous Song", duration=230, isrc="XX0000000012", ident="2002"),
            ]
        return []

    catalog = [tidal_shared, local, tidal_new, gone, apple_shared, apple_new, ambiguous]
    report, _, _ = _run(
        tmp_path,
        [tidal, apple],
        sink=sink,
        downloads=downloads,
        library=library,
        search=search,
        tag_reader=_tags_for(catalog + [_track("tidal", "1006", "Apple Song", isrc="XX0000000006", duration=220)]),
    )
    assert len(report.playlists) == 1
    playlist = report.playlists[0]
    assert playlist.name == "Playlist A"
    assert playlist.tidal_count == 4
    assert playlist.apple_count == 3
    assert playlist.plex_count == 2
    assert playlist.union_count == 7
    assert playlist.to_download == 2
    assert playlist.already_local == 1
    assert playlist.unobtainable == 1
    assert playlist.unmatched == 0
    assert len(playlist.needs_review) == 1
    assert playlist.needs_review[0]["source_track"]["title"] == "Ambiguous Song"
    assert [call[0] for call in downloads.calls] == [1003, 1006]
    assert sink.rows[0].source_track_id == "p1"
    assert sink.rows[1].source_track_id == "p2"
    assert [track.source_track_id for track in sink.rows] == ["p1", "p2", "1008", "1003", "a6"]
    assert all(name == "Playlist A" for name, _ids in sink.appends)


def test_verify_rules():
    source = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)

    def check(candidate: Candidate, confidence: str):
        assert verify(source, candidate).confidence == confidence

    check(_candidate("Example Song", artist=OTHER, isrc="XX0000000099", ident="cover"), "reject")
    apple = _track("apple", "a1", "Example Song", duration=180)
    other_artist = verify(apple, _candidate("Example Song", artist=OTHER, isrc=None, ident="other"))
    assert other_artist.confidence == "reject"
    assert other_artist.reasons == ("artist_mismatch",)
    cover = verify(apple, _candidate("Example Song (Cover)", artist=OTHER, isrc=None, ident="cover-title"))
    assert cover.confidence == "reject"
    check(_candidate("Example Song (Originally Performed by Example Artist)"), "reject")
    check(_candidate("Example Song (Sped Up)"), "reject")
    check(_candidate("Example Song (Slowed)"), "reject")
    check(_candidate("Example Song (8-Bit)"), "reject")
    check(_candidate("Example Song (Versi\u00f3n Ac\u00fastica)"), "reject")
    check(_candidate("Example Song (Karaoke)"), "reject")
    check(_candidate("Example Song (Tribute)"), "reject")
    check(_candidate("Example Song (In the Style of Example Artist)"), "reject")
    check(_candidate("Example Song (Live)"), "reject")
    check(_candidate("Example Song (Remix)"), "reject")
    check(_candidate("Example Song (Instrumental)"), "reject")
    check(_candidate("Example Song (En Vivo)"), "reject")
    check(_candidate("Example Song (Tributo)"), "reject")
    check(_candidate("Example Song (Remastered)"), "confirmed")
    check(_candidate("Example Song (Remastered 2011)"), "confirmed")
    check(_candidate("Example Song (2011 Remaster)"), "confirmed")
    check(_candidate("Example Song - Remaster"), "confirmed")
    check(_candidate("Example Song (Album Version)"), "confirmed")
    check(_candidate("Example Song (Mono Version)"), "confirmed")
    check(_candidate("Example Song [Stereo Version]"), "confirmed")
    check(_candidate("Example Song", version="Album Version"), "confirmed")
    check(_candidate("Example Song", version="Remastered 2011"), "confirmed")
    check(_candidate("Example Song", version="Live"), "reject")
    check(_candidate("Example Song", version="Acoustic Version"), "reject")
    check(_candidate("Example Song", version="Karaoke Version"), "reject")
    check(_candidate("Example Song", version="Versi\u00f3n Ac\u00fastica"), "reject")
    check(
        _candidate("Example Song (feat. Other Artist)", artist="Example Artist feat. Other Artist"),
        "confirmed",
    )
    check(_candidate("EXÁMPLE SONG", artist="Exámple Artist"), "confirmed")
    check(_candidate("Example Song", duration=183), "confirmed")
    check(_candidate("Example Song", duration=184), "review")
    check(_candidate("Example Song", duration=185), "review")
    check(_candidate("Example Song", duration=186), "reject")
    mismatch = verify(source, _candidate("Example Song", artist=OTHER, isrc="XX0000000001", ident="same-isrc"))
    assert mismatch.confidence == "review"
    assert mismatch.isrc_ok is True
    assert mismatch.artist_ok is False
    live_source = _track("tidal", "1009", "Example Song (Live)", duration=180, isrc="XX0000000009")
    assert verify(live_source, _candidate("Example Song - Live", isrc="XX0000000009", ident="live")).confidence == (
        "confirmed"
    )
    remix = verify(live_source, _candidate("Example Song (Remix)", isrc="XX0000000009", ident="remix"))
    assert remix.confidence == "reject"
    assert remix.version_ok is False
    alive = _track("tidal", "1010", "Alive", duration=180, isrc="XX0000000010")
    assert "live" not in markers_in("Alive")
    assert verify(alive, _candidate("Alive", isrc="XX0000000010", ident="alive")).confidence == "confirmed"


def test_apple_two_candidates_and_isrc_artist_mismatch_do_not_download(tmp_path: Path):
    apple = _track("apple", "a7", "Ambiguous Song", duration=230)
    source = _Source("apple", [(_playlist("apple", "ap-a", "Playlist A", "2026-01-01"), [apple])])
    downloads = _Downloads()

    def search(_track: Track) -> list[Candidate]:
        return [
            _candidate("Ambiguous Song", duration=230, ident="2001", isrc="XX0000000011"),
            _candidate("Ambiguous Song", duration=230, ident="2002", isrc="XX0000000012"),
        ]

    report, _, _ = _run(tmp_path, source, downloads=downloads, search=search)
    assert downloads.calls == []
    assert report.playlists[0].needs_review[0]["action"] == "review"
    assert report.playlists[0].to_download == 0

    tidal = _track("tidal", "1001", "Example Song", isrc="XX0000000001")
    tidal_source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [tidal])])
    blocked = _Downloads()
    other_file = tmp_path / "other.flac"
    other_file.write_bytes(b"other")

    def library(track: Track) -> list[Candidate]:
        if track.isrc == "XX0000000001":
            return [
                _candidate(
                    "Example Song",
                    artist=OTHER,
                    isrc="XX0000000001",
                    ident="row-1",
                    path=str(other_file),
                )
            ]
        return []

    report, _, _ = _run(tmp_path / "isrc", tidal_source, downloads=blocked, library=library)
    assert blocked.calls == []
    assert report.needs_review
    assert report.added == []


def test_post_download_mismatch_is_not_appended_or_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001")
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    target = tmp_path / "1001.flac"
    target.write_bytes(b"keep")
    sink = _Sink()
    downloads = _Downloads({1001: DownloadResult(status="completed", path=str(target))})

    def reader(_path: str) -> dict:
        return {
            "title": "Example Song",
            "artist": OTHER,
            "album": "",
            "duration": 180,
            "isrc": "XX0000000001",
            "version": "",
        }

    def removed(*_args, **_kwargs):
        raise AssertionError("file deleted")

    monkeypatch.setattr(os, "remove", removed)
    monkeypatch.setattr(os, "unlink", removed)
    report, _, _ = _run(tmp_path, source, sink=sink, downloads=downloads, tag_reader=reader)
    assert sink.appends == []
    assert report.download_mismatch
    assert report.download_mismatch[0]["status"] == "download_mismatch"
    assert report.added == []
    assert target.read_bytes() == b"keep"


def test_download_mismatch_is_not_queued_again(tmp_path: Path):
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001")
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    target = tmp_path / "1001.flac"
    target.write_bytes(b"keep")
    ledger = Ledger(tmp_path / "playlist_sync.db")

    def reader(_path: str) -> dict:
        return {
            "title": "Example Song",
            "artist": OTHER,
            "album": "",
            "duration": 180,
            "isrc": "XX0000000001",
            "version": "",
        }

    first = _Downloads({1001: DownloadResult(status="completed", path=str(target))})
    report, _, _ = _run(tmp_path, source, downloads=first, ledger=ledger, tag_reader=reader)
    assert first.calls == [[1001]]
    assert report.download_mismatch[0]["status"] == "download_mismatch"
    assert report.needs_review[0]["action"] == "review"
    stored = ledger.get_track("tidal", "1001", normalize_playlist_name("Playlist A"))
    assert stored is not None
    assert stored["status"] == "download_mismatch"
    assert stored["last_failure_day"] == "2026-10-06"

    same_day = _Downloads({1001: DownloadResult(status="completed", path=str(target))})
    report, _, _ = _run(tmp_path, source, downloads=same_day, ledger=ledger, tag_reader=reader)
    assert same_day.calls == []
    assert report.needs_review[0]["action"] == "review"
    assert report.needs_review[0]["status"] == "download_mismatch"
    assert report.playlists[0].to_download == 0

    next_day = _Downloads({1001: DownloadResult(status="completed", path=str(target))})
    report, _, _ = _run(
        tmp_path,
        source,
        downloads=next_day,
        ledger=ledger,
        tag_reader=reader,
        now=_wall(2026, 10, 7, 12),
    )
    assert next_day.calls == []
    assert report.needs_review[0]["status"] == "download_mismatch"
    assert report.playlists[0].to_download == 0


def test_package_never_references_bulk_sync_or_tokens():
    root = Path(__file__).resolve().parents[1] / "tidal_dl" / "playlist_sync"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    for banned in ("sync_playlist", "cli_sync", "enqueue_upgrade", "Upgrade All", "token.json", "login_oauth"):
        assert banned not in text
    for path in root.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"))


def test_tidal_source_reuses_catalog_helpers():
    from tidal_dl.playlist_sync.tidal_source import TidalSource

    class Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    artist = Obj(name=ARTIST, id=1)
    album = Obj(name="Example Album", id=2, image=lambda _size: "")

    def raw(track_id: int, allow: bool, ready: bool, title: str):
        return Obj(
            id=track_id,
            name=title,
            full_name=None,
            artists=[artist],
            album=album,
            duration=180,
            isrc="XX0000000001",
            allow_streaming=allow,
            stream_ready=ready,
            audio_quality="HIGH",
            media_metadata_tags=[],
            version="",
        )

    playlist = Obj(
        tracks=lambda limit, offset: []
        if offset
        else [raw(1001, False, True, "Example Song"), raw(1002, True, True, "Second Song")]
    )
    session = Obj(
        user=Obj(playlists=lambda: [Obj(id="pl-a", name="Playlist A", num_tracks=2, last_updated="2026-01-01")]),
        playlist=lambda _playlist_id: playlist,
    )
    tidal = TidalSource(session)
    listed = tidal.list_playlists()
    assert listed[0].name == "Playlist A"
    tracks = tidal.list_tracks(listed[0])
    assert [(item.source_track_id, item.available) for item in tracks] == [("1001", False), ("1002", True)]


def test_job_service_downloader_queues_one_track():
    seen: list[list[int]] = []

    class Service:
        def enqueue_download(self, track_ids: list[int]) -> dict:
            seen.append(list(track_ids))
            return {"status": "queued", "count": 1}

        def poll_download(self, track_id: int) -> DownloadResult:
            return DownloadResult(status="completed", path=f"/music/{track_id}.flac")

    client = JobServiceDownloader(Service())
    assert client.enqueue_download([1001])["count"] == 1
    assert client.wait_for(1001).status == "completed"
    assert seen == [[1001]]
    with pytest.raises(ValueError):
        client.enqueue_download([1001, 1002])

    class StatusService:
        def __init__(self, status: str, error: str | None = None) -> None:
            self.status = status
            self.error = error

        def enqueue_download(self, track_ids: list[int]) -> dict:
            return {"status": "queued", "count": len(track_ids)}

        def job_status_for_track(self, track_id: int) -> dict:
            return {"status": self.status, "error": self.error, "job_id": str(track_id)}

    done = JobServiceDownloader(StatusService("done"), sleep=lambda _seconds: None, timeout_sec=900)
    assert done.wait_for(1001).status == "completed"
    assert done.wait_for(1001).path is None
    failed = JobServiceDownloader(StatusService("error", "429"), sleep=lambda _seconds: None, timeout_sec=900)
    assert failed.wait_for(1002).status == "failed"
    assert failed.wait_for(1002).http_status == 429
    waiting = JobServiceDownloader(StatusService("running"), sleep=lambda _seconds: None, timeout_sec=0)
    timed_out = waiting.wait_for(1003)
    assert timed_out.status == "failed"
    assert timed_out.error == "timeout"


def test_real_job_status_resolves_the_file_from_the_library(tmp_path: Path):
    audio = tmp_path / "example.flac"
    audio.write_bytes(b"audio")
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])

    class Service:
        def __init__(self) -> None:
            self.calls: list[list[int]] = []

        def enqueue_download(self, track_ids: list[int]) -> dict:
            self.calls.append(list(track_ids))
            return {"status": "queued", "count": len(track_ids)}

        def job_status_for_track(self, track_id: int) -> dict:
            return {
                "job_id": str(track_id),
                "status": "done",
                "progress": 100.0,
                "title": "Example Song",
                "artist": ARTIST,
                "started_at": 1.0,
                "finished_at": 2.0,
                "error": None,
            }

    service = Service()
    client = JobServiceDownloader(service, sleep=lambda _seconds: None)
    bare = client.wait_for(1001)
    assert bare.status == "completed"
    assert bare.path is None

    missing, _, _ = _run(
        tmp_path / "missing",
        source,
        downloads=JobServiceDownloader(Service(), sleep=lambda _seconds: None),
        library=lambda _item: [],
    )
    assert missing.download_mismatch
    assert "downloaded_file_not_found" in missing.download_mismatch[0]["reasons"]

    lookups = {"n": 0}

    def library(_track: Track) -> list[Candidate]:
        lookups["n"] += 1
        if lookups["n"] == 1:
            return []
        return [_candidate("Example Song", isrc="XX0000000001", ident="row-1", path=str(audio))]

    def reader(path: str) -> dict:
        assert path == str(audio)
        return {"title": "Example Song", "artist": ARTIST, "duration": 180, "isrc": "XX0000000001"}

    sink = _Sink()
    report, _, _ = _run(
        tmp_path / "found",
        source,
        sink=sink,
        downloads=client,
        library=library,
        tag_reader=reader,
    )
    assert service.calls == [[1001]]
    assert report.download_mismatch == []
    assert sink.appends == [("Playlist A", ["1001"])]


def _patch_library_db(monkeypatch: pytest.MonkeyPatch, events: list[object], database: object) -> None:
    def opener() -> object:
        events.append("open")
        return database

    monkeypatch.setattr("tidal_dl.playlist_sync.cycle.open_library_db", opener)


def _cycle_with_default_library(tmp_path: Path, source: _Source, **kwargs):
    pacing = _ClockRng()
    return run_cycle(
        _wall(2026, 10, 6, 12),
        settings=kwargs.get("settings", _cfg(dry_run=True)),
        sources=[source],
        sink=kwargs.get("sink") or _Sink(),
        ledger=Ledger(tmp_path / "playlist_sync.db"),
        downloads=kwargs.get("downloads") or _Downloads(),
        tag_reader=kwargs.get("tag_reader"),
        clock=pacing.clock,
        rng=pacing,
        sleep=pacing.sleep,
        pacer=TidalApiPacer(delay_min=0, delay_max=0, sleeper=pacing.sleep, clock=pacing.clock),
        auth_state=kwargs.get("auth_state", lambda: "credentials_ready"),
        download_path_ready=kwargs.get("download_path_ready", lambda _path: True),
    )


def test_omitted_library_opens_the_db_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio = tmp_path / "example.flac"
    audio.write_bytes(b"audio")
    events: list[object] = []
    titles = {
        "XX0000000001": "Example Song",
        "XX0000000002": "Second Song",
        "XX0000000003": "Third Song",
    }
    misses = {"XX0000000003": 0}

    class FakeDB:
        def tracks_by_isrc(self, isrc: str) -> list[dict]:
            events.append(("lookup", isrc))
            if isrc == "XX0000000003":
                misses[isrc] += 1
                if misses[isrc] == 1:
                    return []
            return [
                {
                    "path": str(audio),
                    "title": titles[isrc],
                    "artist": ARTIST,
                    "duration": 180,
                    "isrc": isrc,
                }
            ]

        def close(self) -> None:
            events.append("close")

    class Service:
        def __init__(self) -> None:
            self.calls: list[list[int]] = []

        def enqueue_download(self, track_ids: list[int]) -> dict:
            self.calls.append(list(track_ids))
            return {"status": "queued", "count": len(track_ids)}

        def job_status_for_track(self, track_id: int) -> dict:
            return {
                "job_id": str(track_id),
                "status": "done",
                "progress": 100.0,
                "title": "Third Song",
                "artist": ARTIST,
                "started_at": 1.0,
                "finished_at": 2.0,
                "error": None,
            }

    _patch_library_db(monkeypatch, events, FakeDB())
    rows = [
        _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180),
        _track("tidal", "1002", "Second Song", isrc="XX0000000002", duration=180),
        _track("tidal", "1003", "Third Song", isrc="XX0000000003", duration=180),
    ]
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), rows)])
    service = Service()

    def reader(path: str) -> dict:
        assert path == str(audio)
        return {"title": "Third Song", "artist": ARTIST, "duration": 180, "isrc": "XX0000000003"}

    report = _cycle_with_default_library(
        tmp_path,
        source,
        settings=_cfg(),
        downloads=JobServiceDownloader(service, sleep=lambda _seconds: None),
        tag_reader=reader,
    )
    assert events == [
        "open",
        ("lookup", "XX0000000001"),
        ("lookup", "XX0000000002"),
        ("lookup", "XX0000000003"),
        ("lookup", "XX0000000003"),
        "close",
    ]
    assert report.playlists[0].already_local == 2
    assert report.playlists[0].to_download == 1
    assert service.calls == [[1003]]
    assert report.download_mismatch == []


def test_early_halt_never_opens_the_library_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    events: list[object] = []

    class FakeDB:
        def tracks_by_isrc(self, isrc: str) -> list[dict]:
            events.append(("lookup", isrc))
            return []

        def close(self) -> None:
            events.append("close")

    _patch_library_db(monkeypatch, events, FakeDB())
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    expired = _cycle_with_default_library(
        tmp_path / "auth",
        source,
        auth_state=lambda: "expired",
    )
    assert expired.halted_reason == "auth_state=expired"
    assert events == []

    blocked = _cycle_with_default_library(
        tmp_path / "mount",
        source,
        download_path_ready=lambda _path: False,
    )
    assert blocked.halted_reason == "download_path_unavailable"
    assert events == []


def test_library_db_closes_when_the_cycle_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio = tmp_path / "example.flac"
    audio.write_bytes(b"audio")
    events: list[object] = []

    class RaisingDB:
        def tracks_by_isrc(self, isrc: str) -> list[dict]:
            events.append(("lookup", isrc))
            if isrc == "XX0000000002":
                raise RuntimeError("lookup failed")
            return [
                {
                    "path": str(audio),
                    "title": "Example Song",
                    "artist": ARTIST,
                    "duration": 180,
                    "isrc": isrc,
                }
            ]

        def close(self) -> None:
            events.append("close")

    _patch_library_db(monkeypatch, events, RaisingDB())
    rows = [
        _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180),
        _track("tidal", "1002", "Second Song", isrc="XX0000000002", duration=180),
    ]
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), rows)])
    with pytest.raises(RuntimeError, match="lookup failed"):
        _cycle_with_default_library(tmp_path / "raise", source)
    assert events == [
        "open",
        ("lookup", "XX0000000001"),
        ("lookup", "XX0000000002"),
        "close",
    ]

    events.clear()

    class HaltDB:
        def tracks_by_isrc(self, isrc: str) -> list[dict]:
            events.append(("lookup", isrc))
            if isrc == "XX0000000002":
                return []
            return [
                {
                    "path": str(audio),
                    "title": "Example Song",
                    "artist": ARTIST,
                    "duration": 180,
                    "isrc": isrc,
                }
            ]

        def close(self) -> None:
            events.append("close")

    _patch_library_db(monkeypatch, events, HaltDB())
    halted = _cycle_with_default_library(
        tmp_path / "halt",
        source,
        settings=_cfg(),
        downloads=_Downloads({1002: DownloadResult(status="failed", http_status=429, error="429")}),
    )
    assert halted.halted_reason == "429"
    assert events == [
        "open",
        ("lookup", "XX0000000001"),
        ("lookup", "XX0000000002"),
        "close",
    ]


def test_library_lookup_uses_isrc_rows():
    row = _track("tidal", "1008", "Local Song", isrc="XX0000000008", duration=190)

    class Db:
        def tracks_by_isrc(self, isrc: str) -> list[dict]:
            assert isrc == "XX0000000008"
            return [
                {
                    "path": "/music/local.flac",
                    "title": "Local Song",
                    "artist": ARTIST,
                    "duration": 190,
                    "isrc": isrc,
                }
            ]

    found = library_candidates(Db(), row)
    assert found[0].id == "/music/local.flac"
    assert verify(row, found[0]).confidence == "confirmed"


def test_ledger_file_is_not_the_library_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("tidal_dl.helper.path.path_config_base", lambda: str(tmp_path))
    path = default_ledger_path()
    assert path.name == "playlist_sync.db"
    assert path.name != "library.db"


def test_case_insensitive_playlist_merge(tmp_path: Path):
    tidal = _Source(
        "tidal",
        [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [_track("tidal", "1001", "Example Song")])],
    )
    apple = _Source(
        "apple",
        [(_playlist("apple", "ap-a", "PLAYLIST A", "2026-01-01"), [_track("apple", "a1", "Second Song", duration=200)])],
    )
    report, _, _ = _run(tmp_path, [tidal, apple], settings=_cfg(dry_run=True, max_per_cycle=5))
    assert len(report.playlists) == 1
    assert report.playlists[0].tidal_count == 1
    assert report.playlists[0].apple_count == 1
    assert report.playlists[0].union_count == 2


SONG_NFC = "Canci\u00f3n"
SONG_NFD = unicodedata.normalize("NFD", SONG_NFC)


def _live(tmp_path: Path, base: Path):
    track = _track("tidal", "1001", "Example Song", isrc="XX0000000001")
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [track])])
    downloads = _Downloads()
    pacing = _ClockRng()
    report = run_cycle(
        _wall(2026, 10, 6, 12),
        settings=_cfg(download_base_path=str(base)),
        sources=[source],
        sink=_Sink(),
        ledger=Ledger(tmp_path / "playlist_sync.db"),
        downloads=downloads,
        library=lambda _item: [],
        tag_reader=_tags_for([track]),
        clock=pacing.clock,
        rng=pacing,
        sleep=pacing.sleep,
        pacer=TidalApiPacer(delay_min=0, delay_max=0, sleeper=pacing.sleep, clock=pacing.clock),
        auth_state=lambda: "credentials_ready",
    )
    return report, downloads


def test_missing_download_path_halts_without_creating_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    missing = tmp_path / "download-missing"
    real_mkdir = Path.mkdir

    def guard(self, *args, **kwargs):
        if Path(self) == missing or missing in Path(self).parents:
            raise AssertionError("download folder was created")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", guard)
    report, downloads = _live(tmp_path, missing)
    assert report.halted_reason == "download_path_unavailable"
    assert downloads.calls == []
    assert not missing.exists()


def test_unmounted_download_path_halts_with_nothing_queued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base = tmp_path / "local-disk"
    base.mkdir()
    monkeypatch.setattr("tidal_dl.playlist_sync.mount.sys.platform", "linux")
    monkeypatch.setattr("tidal_dl.playlist_sync.mount.os.path.ismount", lambda _path: False)
    report, downloads = _live(tmp_path, base)
    assert report.halted_reason == "download_path_unavailable"
    assert downloads.calls == []
    assert base.is_dir()


def test_unwritable_download_path_halts_with_nothing_queued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base = tmp_path / "locked"
    base.mkdir()
    monkeypatch.setattr("tidal_dl.playlist_sync.mount.os.path.ismount", lambda _path: True)
    monkeypatch.setattr("tidal_dl.playlist_sync.mount.os.access", lambda _path, _mode: False)
    report, downloads = _live(tmp_path, base)
    assert report.halted_reason == "download_path_unavailable"
    assert downloads.calls == []
    assert base.is_dir()


def test_writable_mount_still_downloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base = tmp_path / "volume"
    base.mkdir()
    monkeypatch.setattr("tidal_dl.playlist_sync.mount.os.path.ismount", lambda _path: True)
    report, downloads = _live(tmp_path, base)
    assert report.halted_reason is None
    assert downloads.calls == [[1001]]


def test_macos_network_volume_uses_device_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base = tmp_path / "share"
    base.mkdir()
    monkeypatch.setattr("tidal_dl.playlist_sync.mount.os.path.isdir", lambda _path: True)
    monkeypatch.setattr("tidal_dl.playlist_sync.mount.os.path.ismount", lambda _path: False)
    monkeypatch.setattr("tidal_dl.playlist_sync.mount.sys.platform", "darwin")

    def other_device(path: str):
        return SimpleNamespace(st_dev=1 if path == "/" else 2)

    monkeypatch.setattr("tidal_dl.playlist_sync.mount.os.stat", other_device)
    assert download_path_available(str(base)) is True

    monkeypatch.setattr("tidal_dl.playlist_sync.mount.os.stat", lambda _path: SimpleNamespace(st_dev=1))
    assert download_path_available(str(base)) is False


def test_nfd_and_nfc_playlist_title_and_path_match(tmp_path: Path):
    assert SONG_NFD != SONG_NFC
    assert normalize_playlist_name(SONG_NFD) == normalize_playlist_name(SONG_NFC)
    assert normalize_title(SONG_NFD) == normalize_title(SONG_NFC)
    nfd_track = _track("tidal", "1001", SONG_NFD, duration=180)
    nfc_track = _track("apple", "a1", SONG_NFC, duration=181)
    assert nfd_track.title == nfc_track.title == SONG_NFC
    assert same_recording(nfd_track, _track("apple", "a1", SONG_NFC, duration=180))
    assert name_allowed(SONG_NFD, (SONG_NFC,))

    nfd_path = unicodedata.normalize("NFD", f"/music/{SONG_NFC}/track.flac")
    nfc_file = f"/music/{SONG_NFC}/track.flac"
    assert nfd_path != nfc_file
    assert nfc_path(nfd_path) == nfc_path(nfc_file)
    prefix = unicodedata.normalize("NFD", f"/music/{SONG_NFC}")
    assert apply_prefix_map(nfd_path, {prefix: f"/library/{SONG_NFC}"}) == f"/library/{SONG_NFC}/track.flac"

    tidal = _Source("tidal", [(_playlist("tidal", "pl-a", SONG_NFD, "2026-01-01"), [nfd_track])])
    apple = _Source("apple", [(_playlist("apple", "ap-a", SONG_NFC, "2026-01-01"), [nfc_track])])
    seen: list[str] = []

    def reader(path: str) -> dict:
        seen.append(path)
        return {"title": SONG_NFC, "artist": ARTIST, "duration": 180, "isrc": "XX0000000001"}

    report, _, _ = _run(
        tmp_path,
        [tidal, apple],
        settings=_cfg(max_per_cycle=5),
        downloads=_Downloads({1001: DownloadResult(status="completed", path=nfd_path)}),
        tag_reader=reader,
        path_prefixes={prefix: f"/library/{SONG_NFC}"},
    )
    assert len(report.playlists) == 1
    assert report.playlists[0].name == SONG_NFC
    assert report.playlists[0].tidal_count == 1
    assert report.playlists[0].apple_count == 1
    assert seen == [f"/library/{SONG_NFC}/track.flac"]


def test_stale_library_row_is_not_present_unless_plex_confirms(tmp_path: Path):
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    missing = unicodedata.normalize("NFD", f"/music/{SONG_NFC}.flac")
    looked: list[str] = []

    def exists(path: str) -> bool:
        looked.append(path)
        return False

    def library(_track: Track) -> list[Candidate]:
        return [_candidate("Example Song", isrc="XX0000000001", ident="row-1", path=missing)]

    empty = _Sink()
    downloads = _Downloads()
    report, _, _ = _run(
        tmp_path / "missing",
        source,
        sink=empty,
        downloads=downloads,
        library=library,
        tag_reader=_tags_for([row]),
        file_exists=exists,
    )
    assert looked == [nfc_path(missing)]
    assert downloads.calls == [[1001]]
    assert report.playlists[0].to_download == 1
    assert report.playlists[0].already_local == 0
    assert "stale_library_row" in report.playlists[0].tracks[0]["reasons"]

    plex_hit = _track("plex", "plex-1", "Example Song", isrc="XX0000000001", duration=180)
    sink = _Sink(found=[plex_hit])
    held = _Downloads()
    report, _, _ = _run(
        tmp_path / "plex",
        source,
        sink=sink,
        downloads=held,
        library=library,
        file_exists=exists,
    )
    assert held.calls == []
    assert report.playlists[0].to_download == 0
    assert report.playlists[0].already_local == 1
    assert report.playlists[0].tracks[0]["action"] == "append"
    assert "stale_library_row" in report.playlists[0].tracks[0]["reasons"]
    assert sink.appends == [("Playlist A", ["plex-1"])]


def test_plex_index_appends_when_library_db_has_no_row(tmp_path: Path):
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    plex_hit = _track("plex", "plex-1", "Example Song", isrc="XX0000000001", duration=180)
    sink = _Sink(found=[plex_hit])
    downloads = _Downloads()
    report, _, _ = _run(tmp_path, source, sink=sink, downloads=downloads, library=lambda _item: [])
    assert downloads.calls == []
    assert sink.find_calls == ["1001"]
    assert sink.appends == [("Playlist A", ["plex-1"])]
    assert report.playlists[0].already_local == 1
    assert report.playlists[0].to_download == 0


def test_plex_cover_and_other_artist_are_not_accepted(tmp_path: Path):
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    cover = _track("plex", "cover-1", "Example Song (Cover)", artist=OTHER, duration=180, isrc="XX0000000099")
    other = _track("plex", "other-1", "Example Song", artist=OTHER, duration=180, isrc="XX0000000098")
    sink = _Sink(found=[cover, other])
    downloads = _Downloads()
    report, _, _ = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=downloads,
        library=lambda _item: [],
        tag_reader=_tags_for([row]),
    )
    assert sink.find_calls == ["1001"]
    assert downloads.calls == [[1001]]
    assert report.playlists[0].already_local == 0
    assert report.playlists[0].to_download == 1
    assert all("cover-1" not in ids and "other-1" not in ids for _name, ids in sink.appends)
    assert report.needs_review == []


def test_library_candidate_without_a_path_is_stale(tmp_path: Path):
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])

    def library(_track: Track) -> list[Candidate]:
        return [_candidate("Example Song", isrc="XX0000000001", ident="row-1", path="")]

    report, _, _ = _run(tmp_path, source, library=library, settings=_cfg(dry_run=True))
    playlist = report.playlists[0]
    assert playlist.already_local == 0
    assert playlist.to_download == 1
    assert "stale_library_row" in playlist.tracks[0]["reasons"]


def test_completed_download_without_a_path_needs_an_existing_library_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    downloads = _Downloads({1001: DownloadResult(status="completed", path=None)})
    sink = _Sink()

    def removed(*_args, **_kwargs):
        raise AssertionError("file deleted")

    monkeypatch.setattr(os, "remove", removed)
    monkeypatch.setattr(os, "unlink", removed)
    report, _, _ = _run(tmp_path / "missing", source, sink=sink, downloads=downloads, library=lambda _item: [])
    assert sink.appends == []
    assert report.added == []
    assert report.download_mismatch
    assert report.download_mismatch[0]["status"] == "download_mismatch"
    assert "downloaded_file_not_found" in report.download_mismatch[0]["reasons"]

    audio = tmp_path / "example.flac"
    audio.write_bytes(b"audio")
    found = _Sink()
    again = _Downloads({1001: DownloadResult(status="completed", path=None)})
    lookups = {"n": 0}

    def library(_track: Track) -> list[Candidate]:
        lookups["n"] += 1
        if lookups["n"] == 1:
            return []
        return [_candidate("Example Song", isrc="XX0000000001", ident="row-1", path=str(audio))]

    def reader(path: str) -> dict:
        assert path == str(audio)
        return {"title": "Example Song", "artist": ARTIST, "duration": 180, "isrc": "XX0000000001"}

    report, _, _ = _run(
        tmp_path / "found",
        source,
        sink=found,
        downloads=again,
        library=library,
        tag_reader=reader,
    )
    assert report.download_mismatch == []
    assert found.appends == [("Playlist A", ["1001"])]
