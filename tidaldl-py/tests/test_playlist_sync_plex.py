"""Plex writer. In-process fake only: no network, no real names, no real tokens."""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from tests.test_playlist_sync import (
    _candidate,
    _cfg,
    _ClockRng,
    _Downloads,
    _playlist,
    _run,
    _Source,
    _track,
    _wall,
)
from tidal_dl.download.api_pacing import TidalApiPacer
from tidal_dl.model.cfg import SETTINGS_HELP
from tidal_dl.model.cfg import Settings as ModelSettings
from tidal_dl.playlist_sync.config import PlaylistSyncConfig, load_config
from tidal_dl.playlist_sync.cycle import run_cycle
from tidal_dl.playlist_sync.ledger import Ledger
from tidal_dl.playlist_sync.matcher import normalize_playlist_name
from tidal_dl.playlist_sync.models import DownloadResult, Track
from tidal_dl.playlist_sync.plex_client import PlexClient, PlexError, PlexWriteBlocked
from tidal_dl.playlist_sync.plex_sink import PlexWriterSink, build_plex_sink
from tidal_dl.playlist_sync.plex_token import PlexToken, resolve_plex_token, save_plex_token_file
from tidal_dl.playlist_sync.sink import NullPlexSink

TOKEN = "example-plex-token-value"
URL = "http://plex.example.invalid:32400"
LOCAL = "/path/to/Music"
SERVER = "/music"
SECTION = "1"
MACHINE = "example-machine-id"
ARTIST = "Example Artist"
OTHER = "Other Artist"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.now += float(seconds)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakePlexServer:
    def __init__(self) -> None:
        self.playlists: list[dict] = []
        self.library: dict[str, dict] = {}
        self.hidden: dict[str, dict] = {}
        self.failures: list[tuple[str, str, int]] = []
        self.scanned_folders: list[str] = []
        self.next_playlist_id = 7001
        self.page_size: int | None = None

    def add_track(
        self,
        *,
        rating_key: str,
        title: str,
        artist: str,
        file_path: str,
        album: str = "Example Album",
        duration_ms: int = 180000,
        original_title: str | None = None,
        visible: bool = True,
        appear_after: int | None = None,
    ) -> dict:
        meta = {
            "ratingKey": rating_key,
            "title": title,
            "grandparentTitle": artist,
            "parentTitle": album,
            "duration": duration_ms,
            "type": "track",
            "addedAt": len(self.library) + len(self.hidden) + 1,
            "Media": [{"Part": [{"file": file_path}]}],
        }
        if original_title:
            meta["originalTitle"] = original_title
        if visible:
            self.library[rating_key] = meta
        else:
            self.hidden[file_path] = {
                "meta": meta,
                "appear_after": appear_after,
                "seen": 0,
                "scanned": False,
            }
        return meta

    def add_playlist(
        self,
        title: str,
        *,
        smart: object = "0",
        items: list[str] | None = None,
        rating_key: str | None = None,
        playlist_type: str = "audio",
    ) -> str:
        key = rating_key or str(self.next_playlist_id)
        self.next_playlist_id += 1
        self.playlists.append(
            {
                "rating_key": key,
                "title": title,
                "smart": smart,
                "items": list(items or []),
                "playlist_type": playlist_type,
            }
        )
        return key

    def reveal(self, file_path: str) -> None:
        pending = self.hidden.pop(file_path)
        meta = pending["meta"]
        self.library[str(meta["ratingKey"])] = meta

    def take_failure(self, method: str, path: str) -> int | None:
        for index, (verb, expected, code) in enumerate(self.failures):
            if verb == method and expected == path:
                self.failures.pop(index)
                return code
        return None

    def note_search(self) -> None:
        for pending in self.hidden.values():
            if pending["scanned"] and pending["appear_after"] is not None:
                pending["seen"] += 1

    def visible(self) -> list[dict]:
        rows = list(self.library.values())
        for pending in self.hidden.values():
            after = pending["appear_after"]
            if after is not None and pending["scanned"] and pending["seen"] >= after:
                rows.append(pending["meta"])
        return rows

    def metadata_for(self, rating_key: str) -> dict:
        if rating_key in self.library:
            return self.library[rating_key]
        for pending in self.hidden.values():
            if str(pending["meta"]["ratingKey"]) == str(rating_key):
                return pending["meta"]
        return {"ratingKey": str(rating_key), "title": "Hand Added", "type": "track"}

    def dispatch(self, method: str, path: str, params: dict, headers: dict) -> tuple[int, dict]:
        if method == "DELETE":
            return 404, {"MediaContainer": {}}
        if method == "GET" and path == "/identity":
            return 200, {"MediaContainer": {"machineIdentifier": MACHINE}}
        if method == "GET" and path == "/playlists":
            rows = [
                {
                    "ratingKey": item["rating_key"],
                    "title": item["title"],
                    "smart": item["smart"],
                    "playlistType": item["playlist_type"],
                }
                for item in self.playlists
            ]
            return 200, {"MediaContainer": {"size": len(rows), "Metadata": rows}}
        if method == "GET" and path.startswith("/playlists/") and path.endswith("/items"):
            key = path.split("/")[2]
            playlist = self._playlist(key)
            rows = [self.metadata_for(item) for item in playlist["items"]]
            return 200, self._page(rows, headers)
        if method == "POST" and path == "/playlists":
            return 200, self._create(params)
        if method == "PUT" and path.startswith("/playlists/") and path.endswith("/items"):
            key = path.split("/")[2]
            return 200, self._add(key, params)
        if method == "GET" and path == f"/library/sections/{SECTION}/refresh":
            folder = str(params.get("path") or "")
            self.scanned_folders.append(folder)
            prefix = folder.rstrip("/")
            for file_path, pending in self.hidden.items():
                parent = file_path.rsplit("/", 1)[0] if "/" in file_path else ""
                if parent == prefix:
                    pending["scanned"] = True
            return 200, {"MediaContainer": {"size": 0}}
        if method == "GET" and path == f"/library/sections/{SECTION}/all":
            if params.get("sort") == "addedAt:desc":
                limit = int(headers.get("X-Plex-Container-Size") or 100)
                rows = sorted(self.visible(), key=lambda row: int(row.get("addedAt") or 0), reverse=True)[:limit]
            else:
                self.note_search()
                wanted = str(params.get("title") or "").casefold()
                rows = [row for row in self.visible() if str(row.get("title") or "").casefold() == wanted]
            return 200, {"MediaContainer": {"size": len(rows), "totalSize": len(rows), "Metadata": rows}}
        return 404, {"MediaContainer": {}}

    def _playlist(self, key: str) -> dict:
        for item in self.playlists:
            if item["rating_key"] == key:
                return item
        raise AssertionError(f"unknown playlist {key}")

    def _create(self, params: dict) -> dict:
        first = str(params.get("uri") or "").rsplit("/", 1)[-1]
        key = str(self.next_playlist_id)
        self.next_playlist_id += 1
        self.playlists.append(
            {
                "rating_key": key,
                "title": params.get("title") or "",
                "smart": "0",
                "items": [first] if first else [],
                "playlist_type": "audio",
            }
        )
        return {"MediaContainer": {"Metadata": [{"ratingKey": key, "title": params.get("title") or ""}]}}

    def _add(self, key: str, params: dict) -> dict:
        fresh = [item for item in str(params.get("uri") or "").rsplit("/", 1)[-1].split(",") if item]
        self._playlist(key)["items"].extend(fresh)
        return {"MediaContainer": {"size": len(fresh)}}

    def _page(self, rows: list[dict], headers: dict) -> dict:
        start = int(headers.get("X-Plex-Container-Start") or 0)
        size = int(headers.get("X-Plex-Container-Size") or 100)
        if self.page_size is not None:
            size = min(size, self.page_size)
        chunk = rows[start : start + size]
        return {
            "MediaContainer": {
                "size": len(chunk),
                "totalSize": len(rows),
                "Metadata": chunk,
            }
        }


class FakeSession:
    def __init__(self, server: FakePlexServer) -> None:
        self.server = server
        self.calls: list[dict] = []

    def request(self, method: str, url: str, params=None, headers=None, timeout=None, **_kwargs):
        parsed = urlsplit(url)
        call = {
            "method": method.upper(),
            "url": url,
            "path": parsed.path,
            "params": dict(params or {}),
            "headers": dict(headers or {}),
            "timeout": timeout,
        }
        self.calls.append(call)
        code = self.server.take_failure(call["method"], parsed.path)
        if code is not None:
            return FakeResponse(code, {"MediaContainer": {}})
        status, payload = self.server.dispatch(call["method"], parsed.path, call["params"], call["headers"])
        return FakeResponse(status, payload)


class BoomSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def request(self, *_args, **_kwargs):
        self.calls.append({"called": True})
        raise AssertionError("request was sent")


def _stack(tmp_path: Path, clock: Clock | None = None, *, dry_run: bool = False, timeout: float = 600, poll: float = 10):
    timer = clock or Clock()
    server = FakePlexServer()
    session = FakeSession(server)
    ledger = Ledger(tmp_path / "playlist_sync.db")
    client = PlexClient(URL, PlexToken(TOKEN), SECTION, session=session, read_only=dry_run)
    sink = PlexWriterSink(
        client,
        ledger,
        local_prefix=LOCAL,
        server_prefix=SERVER,
        scan_timeout_sec=timeout,
        poll_sec=poll,
        clock=timer.clock,
        sleep=timer.sleep,
        dry_run=dry_run,
    )
    return server, session, ledger, client, sink, timer


def _mutations(session: FakeSession) -> list[dict]:
    found = []
    for call in session.calls:
        if call["method"] in {"POST", "PUT", "DELETE"} or call["path"].endswith("/refresh"):
            found.append(call)
    return found


def _methods(session: FakeSession) -> list[str]:
    return [call["method"] for call in session.calls]


def _local(name: str) -> str:
    return f"{LOCAL}/Example Artist/{name}.flac"


def _server(name: str) -> str:
    return f"{SERVER}/Example Artist/{name}.flac"


def _tags(path: str) -> dict:
    name = Path(path).stem
    if name == "Other Song":
        return {"title": "Other Song", "artist": OTHER, "album": "Example Album", "duration": 180, "isrc": "XX0000000002"}
    return {"title": "Example Song", "artist": ARTIST, "album": "Example Album", "duration": 180, "isrc": "XX0000000001"}


def _exists(path: str) -> bool:
    return path.startswith(f"{LOCAL}/")


def _db_bytes(path: Path) -> bytes:
    blob = path.read_bytes()
    for suffix in ("-wal", "-shm"):
        extra = Path(f"{path}{suffix}")
        if extra.exists():
            blob += extra.read_bytes()
    return blob


def _plex_track(track_id: str, title: str, *, artist: str = ARTIST) -> Track:
    return Track(source="plex", source_track_id=track_id, title=title, artist=artist, album="Example Album", duration=180)


def test_append_keeps_hand_added_tracks_and_skips_duplicates(tmp_path: Path):
    server, session, _ledger, client, sink, _clock = _stack(tmp_path)
    server.add_track(rating_key="5001", title="Kept Song", artist=ARTIST, file_path=_server("Kept Song"))
    server.add_track(rating_key="5002", title="Hand Added", artist=ARTIST, file_path=_server("Hand Added"))
    server.add_track(rating_key="5003", title="Example Song", artist=ARTIST, file_path=_server("Example Song"))
    server.add_playlist("Playlist A", smart="0", items=["5001", "5002"], rating_key="4001")

    names = [name for name in dir(PlexClient) if not name.startswith("_")]
    assert not any(word in name.lower() for name in names for word in ("delete", "remove", "clear", "move", "reorder"))

    first = sink.append("Playlist A", [_plex_track("5003", "Example Song"), _plex_track("5001", "Kept Song")])
    assert first.status == "added"
    assert first.rating_keys == ["5003"]
    assert server.playlists[0]["items"] == ["5001", "5002", "5003"]

    second = sink.append("Playlist A", [_plex_track("5003", "Example Song")])
    assert second.status == "already_present"
    assert server.playlists[0]["items"] == ["5001", "5002", "5003"]
    puts = [call for call in session.calls if call["method"] == "PUT"]
    assert len(puts) == 1
    assert "5003" in puts[0]["params"]["uri"]
    assert "5001" not in puts[0]["params"]["uri"].rsplit("/", 1)[-1].split(",")
    assert "DELETE" not in _methods(session)
    assert client.section_id == SECTION


def test_removed_upstream_track_stays_on_the_plex_playlist(tmp_path: Path):
    server, session, ledger, _client, sink, _clock = _stack(tmp_path)
    server.add_track(
        rating_key="5001",
        title="Kept Song",
        artist=OTHER,
        original_title=ARTIST,
        file_path=_server("Kept Song"),
    )
    server.add_track(rating_key="5002", title="Removed Song", artist=ARTIST, file_path=_server("Removed Song"))
    server.add_playlist("Playlist A", smart="0", items=["5001", "5002"], rating_key="4001")
    kept = _track("tidal", "1001", "Kept Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [kept])])
    downloads = _Downloads()
    _run(tmp_path, source, sink=sink, downloads=downloads, ledger=ledger, library=lambda _item: [])
    assert downloads.calls == []
    assert server.playlists[0]["items"] == ["5001", "5002"]
    assert _mutations(session) == []
    assert "DELETE" not in _methods(session)


def test_smart_playlist_is_refused(tmp_path: Path):
    server, session, ledger, _client, sink, _clock = _stack(tmp_path)
    server.add_playlist("playlist a", smart="1", items=[], rating_key="8001")
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    local_file = _local("Example Song")

    def library(track: Track):
        if track.source_track_id == "1001":
            from tidal_dl.playlist_sync.models import Candidate

            return [Candidate(id="row-1", title="Example Song", artist=ARTIST, duration=180, isrc="XX0000000001", path=local_file)]
        return []

    downloads = _Downloads()
    report, store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=downloads,
        ledger=ledger,
        library=library,
        file_exists=_exists,
    )
    assert downloads.calls == []
    assert report.added == []
    assert [item["status"] for item in report.plex_errors] == ["refused_smart"]
    stored = store.get_track("tidal", "1001", normalize_playlist_name("Playlist A"))
    assert stored is not None
    assert stored["status"] != "added"
    assert _mutations(session) == []
    assert not any(call["method"] in {"POST", "PUT"} for call in session.calls)


def test_missing_playlist_is_created_then_appended(tmp_path: Path):
    server, session, _ledger, _client, sink, _clock = _stack(tmp_path)
    result = sink.append(
        "Playlist A",
        [_plex_track("5001", "Example Song"), _plex_track("5002", "Other Song", artist=OTHER)],
    )
    assert result.status == "added"
    assert result.rating_keys == ["5001", "5002"]
    created = [call for call in session.calls if call["method"] == "POST"]
    assert len(created) == 1
    assert created[0]["path"] == "/playlists"
    assert created[0]["params"]["type"] == "audio"
    assert created[0]["params"]["smart"] == "0"
    assert created[0]["params"]["title"] == "Playlist A"
    assert created[0]["params"]["uri"] == (
        f"server://{MACHINE}/com.plexapp.plugins.library/library/metadata/5001"
    )
    appended = [call for call in session.calls if call["method"] == "PUT"]
    assert len(appended) == 1
    assert appended[0]["params"]["uri"].endswith("/5002")
    assert server.playlists[0]["items"] == ["5001", "5002"]
    assert "DELETE" not in _methods(session)


def test_scan_waits_for_the_file_then_uses_the_path_cache(tmp_path: Path):
    server, session, ledger, _client, sink, clock = _stack(tmp_path)
    server.add_track(
        rating_key="5001",
        title="Example Song",
        artist=ARTIST,
        file_path=_server("Example Song"),
        visible=False,
        appear_after=3,
    )
    track = _track("tidal", "1001", "Example Song", duration=180)
    first = sink.append("Playlist A", [track], paths=[_local("Example Song")])
    assert first.status == "added"
    assert first.rating_keys == ["5001"]
    assert server.scanned_folders == [f"{SERVER}/Example Artist"]
    assert clock.sleeps == [10, 10]
    assert ledger.get_plex_rating_key(_server("Example Song")) == "5001"
    refresh = [call for call in session.calls if call["path"].endswith("/refresh")]
    assert len(refresh) == 1
    assert refresh[0]["params"]["path"] == f"{SERVER}/Example Artist"

    second = sink.append("Playlist A", [track], paths=[_local("Example Song")])
    assert second.status == "already_present"
    assert [call for call in session.calls if call["path"].endswith("/refresh")] == refresh
    assert server.scanned_folders == [f"{SERVER}/Example Artist"]


def test_scan_timeout_retries_on_the_next_cycle_without_a_new_download(tmp_path: Path):
    server, session, ledger, _client, sink, clock = _stack(tmp_path)
    server_path = _server("Example Song")
    server.add_track(
        rating_key="5001",
        title="Example Song",
        artist=OTHER,
        file_path=server_path,
        visible=False,
        appear_after=None,
    )
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    first_dl = _Downloads({1001: DownloadResult(status="completed", path=_local("Example Song"))})
    report, store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=first_dl,
        ledger=ledger,
        library=lambda _item: [],
        tag_reader=_tags,
        file_exists=_exists,
    )
    assert first_dl.calls == [[1001]]
    assert [item["status"] for item in report.pending_plex] == ["pending_plex"]
    assert report.added == []
    assert not any(call["method"] in {"POST", "PUT", "DELETE"} for call in session.calls)
    stored = store.get_track("tidal", "1001", normalize_playlist_name("Playlist A"))
    assert stored is not None
    assert stored["status"] == "downloaded"
    assert stored["local_path"] == _local("Example Song")
    assert sum(clock.sleeps) == 600
    assert clock.now == 600

    server.reveal(server_path)
    second_dl = _Downloads({1001: DownloadResult(status="completed", path=_local("Example Song"))})
    again, store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=second_dl,
        ledger=ledger,
        library=lambda _item: [],
        tag_reader=_tags,
        file_exists=_exists,
    )
    assert second_dl.calls == []
    assert again.added
    assert again.pending_plex == []
    assert store.get_track("tidal", "1001", normalize_playlist_name("Playlist A"))["status"] == "added"
    assert server.playlists[0]["items"] == ["5001"]
    assert sum(clock.sleeps) == 600


def test_second_pending_track_does_not_wait_another_timeout(tmp_path: Path):
    server, session, ledger, _client, sink, clock = _stack(tmp_path)
    server.add_track(
        rating_key="5001",
        title="Example Song",
        artist=ARTIST,
        file_path=f"{SERVER}/Example Artist/Example Song.flac",
        visible=False,
        appear_after=None,
    )
    server.add_track(
        rating_key="5002",
        title="Other Song",
        artist=OTHER,
        file_path=f"{SERVER}/Other Artist/Other Song.flac",
        visible=False,
        appear_after=None,
    )
    first = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    second = _track("tidal", "1002", "Other Song", artist=OTHER, isrc="XX0000000002", duration=200)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [first, second])])
    downloads = _Downloads(
        {
            1001: DownloadResult(status="completed", path=_local("Example Song")),
            1002: DownloadResult(status="completed", path=f"{LOCAL}/Other Artist/Other Song.flac"),
        }
    )

    def tags(path: str) -> dict:
        if path.endswith("Other Song.flac"):
            return {"title": "Other Song", "artist": OTHER, "duration": 200, "isrc": "XX0000000002"}
        return _tags(path)

    def exists(path: str) -> bool:
        return path.startswith(f"{LOCAL}/")

    report, store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=downloads,
        ledger=ledger,
        library=lambda _item: [],
        tag_reader=tags,
        file_exists=exists,
        settings=_cfg(max_per_cycle=5),
    )
    assert [call[0] for call in downloads.calls] == [1001, 1002]
    assert [item["status"] for item in report.pending_plex] == ["pending_plex", "pending_plex"]
    assert report.added == []
    assert sum(clock.sleeps) == 600
    assert server.scanned_folders == [f"{SERVER}/Example Artist", f"{SERVER}/Other Artist"]
    assert not any(call["method"] in {"POST", "PUT", "DELETE"} for call in session.calls)
    for track_id, filename in (("1001", "Example Song.flac"), ("1002", "Other Song.flac")):
        stored = store.get_track("tidal", track_id, normalize_playlist_name("Playlist A"))
        assert stored is not None
        assert stored["status"] == "downloaded"
        assert stored["local_path"].endswith(filename)


def _forbid_login_and_bulk_sync(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _two_playlist_source() -> _Source:
    first = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    second = _track("tidal", "1002", "Other Song", artist=OTHER, isrc="XX0000000002", duration=200)
    later = _track(
        "tidal",
        "1002",
        "Other Song",
        artist=OTHER,
        isrc="XX0000000002",
        duration=200,
        playlist_name="Playlist B",
    )
    return _Source(
        "tidal",
        [
            (_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [first, second]),
            (_playlist("tidal", "pl-b", "Playlist B", "2026-01-01"), [later]),
        ],
    )


def _assert_plex_read_halted(report, downloads: _Downloads, session: FakeSession, caplog: pytest.LogCaptureFixture) -> None:
    assert report.halted_reason == "plex_unavailable"
    assert downloads.calls == []
    assert report.downloaded == []
    assert report.added == []
    assert report.pending_plex == []
    assert all(playlist.to_download == 0 for playlist in report.playlists)
    assert _mutations(session) == []
    assert not any(call["method"] in {"POST", "PUT", "DELETE"} for call in session.calls)
    dumped = json.dumps(report.to_dict())
    assert TOKEN not in dumped
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("status", [500, 0])
def test_list_tracks_error_halts_as_plex_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
):
    caplog.set_level(logging.DEBUG)
    _forbid_login_and_bulk_sync(monkeypatch)
    server, session, ledger, _client, sink, _clock = _stack(tmp_path)
    server.failures.append(("GET", "/playlists", status))
    source = _two_playlist_source()
    downloads = _Downloads(
        {
            1001: DownloadResult(status="completed", path=_local("Example Song")),
            1002: DownloadResult(status="completed", path=_local("Other Song")),
        }
    )
    report, _store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=downloads,
        ledger=ledger,
        library=lambda _item: [],
        tag_reader=_tags,
        file_exists=_exists,
    )
    assert source.track_calls == []
    assert server.playlists == []
    _assert_plex_read_halted(report, downloads, session, caplog)


def test_find_401_halts_as_plex_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.DEBUG)
    _forbid_login_and_bulk_sync(monkeypatch)
    server, session, ledger, _client, sink, _clock = _stack(tmp_path)
    server.failures.append(("GET", f"/library/sections/{SECTION}/all", 401))
    source = _two_playlist_source()
    downloads = _Downloads(
        {
            1001: DownloadResult(status="completed", path=_local("Example Song")),
            1002: DownloadResult(status="completed", path=_local("Other Song")),
        }
    )
    report, _store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=downloads,
        ledger=ledger,
        library=lambda _item: [],
        tag_reader=_tags,
        file_exists=_exists,
    )
    assert source.track_calls == ["pl-a"]
    assert server.playlists == []
    assert report.halted_reason != "401"
    _assert_plex_read_halted(report, downloads, session, caplog)


def test_unmapped_path_makes_no_plex_calls(tmp_path: Path):
    _server_obj, session, _ledger, _client, sink, _clock = _stack(tmp_path)
    track = _track("tidal", "1001", "Example Song")
    outside = sink.append("Playlist A", [track], paths=["/elsewhere/Example Song.flac"])
    assert outside.status == "unmapped_path"
    assert session.calls == []

    empty = PlexWriterSink(
        _client,
        _ledger,
        local_prefix="",
        server_prefix="",
        clock=_clock.clock,
        sleep=_clock.sleep,
        dry_run=False,
    )
    missing = empty.append("Playlist A", [track], paths=[_local("Example Song")])
    assert missing.status == "unmapped_path"
    assert session.calls == []


def test_dry_run_cycle_records_only_gets_and_downloads_nothing(tmp_path: Path):
    server = FakePlexServer()
    session = FakeSession(server)
    ledger = Ledger(tmp_path / "playlist_sync.db")
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    downloads = _Downloads()
    pacing = _ClockRng()
    cfg = PlaylistSyncConfig(
        enabled=True,
        dry_run=True,
        plex_url=URL,
        plex_section_id=SECTION,
        plex_local_prefix=LOCAL,
        plex_server_prefix=SERVER,
    )
    report = run_cycle(
        _wall(2026, 10, 6, 12),
        settings=cfg,
        sources=[source],
        ledger=ledger,
        downloads=downloads,
        library=lambda _item: [],
        clock=pacing.clock,
        rng=pacing,
        sleep=pacing.sleep,
        pacer=TidalApiPacer(delay_min=0, delay_max=0, sleeper=pacing.sleep, clock=pacing.clock),
        auth_state=lambda: "credentials_ready",
        download_path_ready=lambda _path: True,
        plex_session=session,
        plex_token_resolver=lambda: PlexToken(TOKEN),
    )
    assert downloads.calls == []
    assert report.playlists[0].to_download == 1
    assert session.calls
    assert _methods(session) == ["GET"] * len(session.calls)
    assert _mutations(session) == []
    assert TOKEN not in report.to_dict().__repr__()

    blocked = BoomSession()
    client = PlexClient(URL, PlexToken(TOKEN), SECTION, session=blocked, read_only=True)
    with pytest.raises(PlexWriteBlocked):
        client.create_playlist("Playlist A", "5001")
    with pytest.raises(PlexWriteBlocked):
        client.add_to_playlist("4001", ["5001"])
    with pytest.raises(PlexWriteBlocked):
        client.scan_path(f"{SERVER}/Example Artist")
    assert blocked.calls == []

    _dry_server, dry_session, _dry_ledger, _dry_client, dry_sink, _dry_clock = _stack(tmp_path / "dry", dry_run=True)
    assert dry_sink.append("Playlist A", [_plex_track("5001", "Example Song")]).status == "dry_run"
    assert dry_session.calls == []


def test_token_never_leaks(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    server, session, ledger, client, sink, _clock = _stack(tmp_path)
    server.add_track(rating_key="5001", title="Example Song", artist=ARTIST, file_path=_server("Example Song"))
    ok = sink.append("Playlist A", [_plex_track("5001", "Example Song")])
    assert ok.status == "added"

    server.failures.append(("POST", "/playlists", 500))
    failed = sink.append("Playlist B", [_plex_track("5001", "Example Song")])
    assert failed.status == "failed"
    assert failed.detail == "500"

    server.failures.append(("PUT", "/playlists/7001/items", 401))
    server.add_playlist("Playlist C", smart="0", items=[], rating_key="7001")
    denied = sink.append("Playlist C", [_plex_track("5002", "Other Song", artist=OTHER)])
    assert denied.status == "failed"
    assert denied.detail == "401"

    server.failures.append(("GET", "/library/sections/1/all", 401))
    with pytest.raises(PlexError) as caught:
        client.search_tracks("Example Song")
    messages = " ".join(
        [
            caplog.text,
            repr(PlexToken(TOKEN)),
            str(PlexToken(TOKEN)),
            repr(client),
            str(client),
            repr(sink),
            str(sink),
            str(caught.value),
            repr(ok),
            repr(failed),
            repr(denied),
        ]
    )
    assert TOKEN not in messages
    assert "plex.example.invalid" not in repr(client)
    assert "plex.example.invalid" not in repr(sink)

    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-02"), [row])])
    server.failures.append(("POST", "/playlists", 401))
    report, _store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=_Downloads({1001: DownloadResult(status="completed", path=_local("Example Song"))}),
        ledger=ledger,
        library=lambda _item: [],
        tag_reader=_tags,
        file_exists=_exists,
    )
    import json

    dumped = json.dumps(report.to_dict())
    assert TOKEN not in dumped
    assert TOKEN not in caplog.text
    assert TOKEN.encode() not in _db_bytes(ledger.path)
    for call in session.calls:
        assert TOKEN not in call["url"]
        assert TOKEN not in str(call["params"])
        assert call["headers"].get("X-Plex-Token") == TOKEN
        for name, value in call["headers"].items():
            if name != "X-Plex-Token":
                assert TOKEN not in str(value)


def test_token_resolution_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    keychain_calls: list[str] = []

    def keychain() -> str:
        keychain_calls.append("keychain")
        return "from-keychain"

    def env_of(value: str):
        def getter(key: str, default: str = "") -> str:
            if key == "MUSIC_DL_PLEX_TOKEN":
                return value
            return default

        return getter

    token_file = tmp_path / "plex_token"
    token_file.write_text("from-file\n", encoding="utf-8")

    from_env = resolve_plex_token(
        env_getter=env_of("from-env"),
        keychain_reader=keychain,
        path_resolver=lambda: token_file,
        platform="darwin",
    )
    assert from_env is not None
    assert from_env.reveal() == "from-env"
    assert keychain_calls == []

    from_keychain = resolve_plex_token(
        env_getter=env_of("   "),
        keychain_reader=keychain,
        path_resolver=lambda: token_file,
        platform="darwin",
    )
    assert from_keychain is not None
    assert from_keychain.reveal() == "from-keychain"
    assert keychain_calls == ["keychain"]

    def refuse() -> str:
        raise AssertionError("keychain was consulted")

    from_file = resolve_plex_token(
        env_getter=env_of(""),
        keychain_reader=refuse,
        path_resolver=lambda: token_file,
        platform="linux",
    )
    assert from_file is not None
    assert from_file.reveal() == "from-file"

    monkeypatch.setattr("tidal_dl.helper.path.path_config_base", lambda: str(tmp_path / "config"))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "plex_token").write_text("  example-plex-token-value \n", encoding="utf-8")
    from_default = resolve_plex_token(env_getter=env_of(""), keychain_reader=refuse, platform="linux")
    assert from_default is not None
    assert from_default.reveal() == TOKEN

    seen: list[tuple] = []

    def fake_run(args, **kwargs):
        seen.append((list(args), kwargs))
        return SimpleNamespace(returncode=0, stdout=b"example-plex-token-value\n", stderr=b"not found")

    monkeypatch.setattr("tidal_dl.playlist_sync.plex_token.subprocess.run", fake_run)
    from_command = resolve_plex_token(env_getter=env_of(""), platform="darwin")
    assert from_command is not None
    assert from_command.reveal() == TOKEN
    assert seen[0][0] == ["security", "find-generic-password", "-s", "music-dl-plex-token", "-w"]
    assert seen[0][1]["shell"] is False
    assert seen[0][1]["capture_output"] is True
    assert seen[0][1]["timeout"] == 5
    assert TOKEN not in caplog.text

    def failed_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout=TOKEN.encode(), stderr=b"not found")

    monkeypatch.setattr("tidal_dl.playlist_sync.plex_token.subprocess.run", failed_run)
    assert resolve_plex_token(env_getter=env_of(""), platform="darwin", path_resolver=lambda: tmp_path / "missing") is None

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="security", timeout=5)

    monkeypatch.setattr("tidal_dl.playlist_sync.plex_token.subprocess.run", timed_out)
    assert resolve_plex_token(env_getter=env_of(""), platform="darwin", path_resolver=lambda: tmp_path / "missing") is None

    saved = save_plex_token_file(TOKEN, tmp_path / "nested" / "plex_token")
    assert saved.stat().st_mode & 0o777 == 0o600
    assert saved.read_text(encoding="utf-8").strip() == TOKEN
    assert TOKEN not in caplog.text


def test_bad_scan_timeout_falls_back_to_600():
    for value in ("nope", "0", "-3", 0, -1, 0.0, None, ""):
        loaded = load_config(SimpleNamespace(playlist_sync_plex_scan_timeout_sec=value))
        assert loaded.plex_scan_timeout_sec == 600
    assert load_config(SimpleNamespace(playlist_sync_plex_scan_timeout_sec=45)).plex_scan_timeout_sec == 45
    assert load_config(SimpleNamespace(playlist_sync_plex_scan_timeout_sec="90")).plex_scan_timeout_sec == 90


def test_defaults_use_a_null_sink_and_settings_have_no_token(tmp_path: Path):
    data = ModelSettings()
    assert data.playlist_sync_enabled is False
    assert data.playlist_sync_dry_run is True
    assert data.playlist_sync_plex_url == ""
    assert data.playlist_sync_plex_section_id == ""
    assert data.playlist_sync_plex_local_prefix == ""
    assert data.playlist_sync_plex_server_prefix == ""
    assert data.playlist_sync_plex_scan_timeout_sec == 600
    assert not any("token" in name for name in data.__dataclass_fields__)
    for key in (
        "playlist_sync_plex_url",
        "playlist_sync_plex_section_id",
        "playlist_sync_plex_local_prefix",
        "playlist_sync_plex_server_prefix",
        "playlist_sync_plex_scan_timeout_sec",
    ):
        assert key in SETTINGS_HELP
    loaded = load_config(data)
    assert loaded.plex_url == ""
    assert loaded.plex_section_id == ""
    assert loaded.plex_scan_timeout_sec == 600

    session = FakeSession(FakePlexServer())
    ledger = Ledger(tmp_path / "playlist_sync.db")
    assert isinstance(
        build_plex_sink(loaded, ledger, session=session, token_resolver=lambda: PlexToken(TOKEN)),
        NullPlexSink,
    )
    disabled = run_cycle(
        settings=data,
        ledger=ledger,
        plex_session=session,
        plex_token_resolver=lambda: PlexToken(TOKEN),
    )
    assert disabled.halted_reason == "disabled"
    assert session.calls == []

    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001")
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    pacing = _ClockRng()
    report = run_cycle(
        _wall(2026, 10, 6, 12),
        settings=PlaylistSyncConfig(enabled=True, dry_run=True),
        sources=[source],
        ledger=Ledger(tmp_path / "empty" / "playlist_sync.db"),
        downloads=_Downloads(),
        library=lambda _item: [],
        clock=pacing.clock,
        rng=pacing,
        sleep=pacing.sleep,
        pacer=TidalApiPacer(delay_min=0, delay_max=0, sleeper=pacing.sleep, clock=pacing.clock),
        auth_state=lambda: "credentials_ready",
        download_path_ready=lambda _path: True,
        plex_session=session,
        plex_token_resolver=lambda: PlexToken(TOKEN),
    )
    assert report.halted_reason is None
    assert session.calls == []


def test_playlist_items_page_until_the_container_is_complete(tmp_path: Path):
    server, session, _ledger, client, _sink, _clock = _stack(tmp_path)
    server.page_size = 1
    server.add_track(rating_key="5001", title="Kept Song", artist=ARTIST, file_path=_server("Kept Song"))
    server.add_track(rating_key="5002", title="Hand Added", artist=ARTIST, file_path=_server("Hand Added"))
    server.add_playlist("Playlist A", items=["5001", "5002"], rating_key="4001")
    rows = client.playlist_items("4001")
    assert [row["ratingKey"] for row in rows] == ["5001", "5002"]
    item_calls = [call for call in session.calls if call["path"].endswith("/items")]
    assert [call["headers"]["X-Plex-Container-Start"] for call in item_calls] == ["0", "1"]


def test_ledger_migrates_local_path_and_stores_nfc_plex_paths(tmp_path: Path):
    path = tmp_path / "playlist_sync.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE tracks (
            source TEXT NOT NULL,
            source_track_id TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            isrc TEXT,
            title TEXT,
            artist TEXT,
            album TEXT,
            duration REAL,
            first_seen_at TEXT,
            status TEXT NOT NULL,
            last_failure_day TEXT,
            plex_rating_key TEXT,
            available INTEGER NOT NULL DEFAULT 1,
            version TEXT NOT NULL DEFAULT '',
            on_playlist INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (source, source_track_id, name_norm)
        )"""
    )
    connection.commit()
    connection.close()

    ledger = Ledger(path)
    columns = {row["name"] for row in ledger._conn.execute("PRAGMA table_info(tracks)")}
    assert "local_path" in columns
    tables = {row["name"] for row in ledger._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "plex_paths" in tables
    assert "plex_added" in tables

    accent = "Canci\u00f3n"
    nfd = unicodedata.normalize("NFD", f"{SERVER}/{accent}.flac")
    nfc = unicodedata.normalize("NFC", nfd)
    ledger.remember_plex_path(nfd, "5001", at="2026-10-06T00:00:00+00:00")
    assert ledger.get_plex_rating_key(nfc) == "5001"

    track = _track("tidal", "1001", "Example Song")
    name = normalize_playlist_name("Playlist A")
    ledger.set_status(
        track,
        name,
        "downloaded",
        seen_at="2026-10-06T00:00:00+00:00",
        local_path=_local("Example Song"),
    )
    ledger.set_plex_rating_key(track, name, "5001")
    ledger.set_status(track, name, "downloaded", seen_at="2026-10-06T01:00:00+00:00")
    stored = ledger.get_track("tidal", "1001", name)
    assert stored is not None
    assert stored["status"] == "downloaded"
    assert stored["local_path"] == _local("Example Song")
    assert stored["plex_rating_key"] == "5001"
    ledger.remember_plex_added(name, "5001", at="2026-10-06T00:00:00+00:00")
    ledger.remember_plex_added(name, "5001", at="2026-10-06T01:00:00+00:00")
    assert ledger.plex_added_keys(name) == {"5001"}
    ledger.close()


def test_smart_flag_values_from_plex(tmp_path: Path):
    server, _session, _ledger, client, _sink, _clock = _stack(tmp_path)
    server.add_playlist("Playlist A", smart="1", rating_key="8001")
    server.add_playlist("Playlist B", smart=1, rating_key="8002")
    server.add_playlist("Playlist C", smart=True, rating_key="8003")
    server.add_playlist("Playlist D", smart="0", rating_key="8004")
    server.add_playlist("Playlist E", smart="0", rating_key="8005", playlist_type="video")
    flags = {item["title"]: item["smart"] for item in client.list_audio_playlists()}
    assert flags == {
        "Playlist A": True,
        "Playlist B": True,
        "Playlist C": True,
        "Playlist D": False,
    }


def _local_library(track: Track) -> list:
    if track.source_track_id == "1001":
        return [_candidate("Example Song", isrc="XX0000000001", ident="row-1", path=_local("Example Song"))]
    if track.source_track_id == "1002":
        return [
            _candidate(
                "Other Song",
                artist=OTHER,
                isrc="XX0000000002",
                ident="row-2",
                path=_local("Other Song"),
            )
        ]
    return []


def test_user_removed_key_is_not_added_back_and_union_still_appends(tmp_path: Path):
    server, session, ledger, _client, sink, _clock = _stack(tmp_path)
    server.add_track(rating_key="5001", title="Example Song", artist=ARTIST, file_path=_server("Example Song"))
    server.add_track(rating_key="5002", title="Hand Added", artist=ARTIST, file_path=_server("Hand Added"))
    server.add_track(rating_key="5004", title="Kept Song", artist=ARTIST, file_path=_server("Kept Song"))
    server.add_track(rating_key="5003", title="Other Song", artist=OTHER, file_path=_server("Other Song"))
    server.add_playlist("Playlist A", items=["5002", "5004"], rating_key="4001")
    first = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [first])])
    downloads = _Downloads()
    report, store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=downloads,
        ledger=ledger,
        library=_local_library,
        file_exists=_exists,
    )
    name = normalize_playlist_name("Playlist A")
    assert downloads.calls == []
    assert report.added
    assert store.plex_added_keys(name) == {"5001"}
    assert server.playlists[0]["items"] == ["5002", "5004", "5001"]
    stored = store.get_track("tidal", "1001", name)
    assert stored is not None
    assert stored["status"] == "added"
    assert stored["plex_rating_key"] == "5001"

    server.playlists[0]["items"] = ["5002", "5004"]
    second = _track("tidal", "1002", "Other Song", artist=OTHER, isrc="XX0000000002", duration=180)
    source.set_tracks("pl-a", [first, second], "2026-01-02")
    session.calls.clear()
    again_downloads = _Downloads()
    again, store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=again_downloads,
        ledger=ledger,
        library=_local_library,
        file_exists=_exists,
    )
    writes = _mutations(session)
    assert again_downloads.calls == []
    assert [call["method"] for call in writes] == ["PUT"]
    assert "5001" not in str(writes[0]["params"].get("uri") or "")
    assert "5003" in str(writes[0]["params"].get("uri") or "")
    assert not any(call["method"] == "POST" for call in session.calls)
    assert server.playlists[0]["items"] == ["5002", "5004", "5003"]
    assert len(again.removed_in_plex) == 1
    removed = again.removed_in_plex[0]
    assert removed["action"] == "skip_removed"
    assert removed["status"] == "removed_in_plex"
    assert removed["reasons"] == ["removed_in_plex"]
    assert removed["source_track"]["title"] == "Example Song"
    assert again.playlists[0].removed_in_plex == 1
    assert again.playlists[0].to_download == 0
    assert again.playlists[0].plex_count == 2
    assert again.playlists[0].union_count == 3
    assert again.pending_plex == []
    assert [item["source_track"]["title"] for item in again.added] == ["Other Song"]
    assert again.to_dict()["removed_in_plex"][0]["status"] == "removed_in_plex"
    assert again.to_dict()["playlists"][0]["removed_in_plex"] == 1
    kept = store.get_track("tidal", "1001", name)
    assert kept is not None
    assert kept["status"] == "added"
    assert store.plex_added_keys(name) == {"5001", "5003"}


def test_dry_run_reports_removed_in_plex_without_writes(tmp_path: Path):
    server, session, ledger, _client, sink, _clock = _stack(tmp_path)
    server.add_track(rating_key="5001", title="Example Song", artist=ARTIST, file_path=_server("Example Song"))
    server.add_track(rating_key="5002", title="Hand Added", artist=ARTIST, file_path=_server("Hand Added"))
    server.add_playlist("Playlist A", items=["5002"], rating_key="4001")
    row = _track("tidal", "1001", "Example Song", isrc="XX0000000001", duration=180)
    source = _Source("tidal", [(_playlist("tidal", "pl-a", "Playlist A", "2026-01-01"), [row])])
    first, store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=_Downloads(),
        ledger=ledger,
        library=_local_library,
        file_exists=_exists,
    )
    assert first.added
    assert server.playlists[0]["items"] == ["5002", "5001"]
    server.playlists[0]["items"] = ["5002"]
    session.calls.clear()
    downloads = _Downloads()
    report, store, _pacing = _run(
        tmp_path,
        source,
        sink=sink,
        downloads=downloads,
        ledger=ledger,
        library=_local_library,
        file_exists=_exists,
        settings=_cfg(dry_run=True),
    )
    assert downloads.calls == []
    assert _mutations(session) == []
    assert server.playlists[0]["items"] == ["5002"]
    assert len(report.removed_in_plex) == 1
    assert report.removed_in_plex[0]["status"] == "removed_in_plex"
    assert report.removed_in_plex[0]["reasons"] == ["removed_in_plex"]
    assert report.playlists[0].removed_in_plex == 1
    assert report.pending_plex == []
    assert report.added == []
    name = normalize_playlist_name("Playlist A")
    assert store.get_track("tidal", "1001", name)["status"] == "added"


def test_recorded_then_removed_key_is_not_written(tmp_path: Path):
    server, session, ledger, _client, sink, _clock = _stack(tmp_path)
    server.add_track(rating_key="5001", title="Example Song", artist=ARTIST, file_path=_server("Example Song"))
    server.add_track(rating_key="5002", title="Hand Added", artist=ARTIST, file_path=_server("Hand Added"))
    server.add_track(rating_key="5004", title="Kept Song", artist=ARTIST, file_path=_server("Kept Song"))
    server.add_playlist("Playlist A", items=["5002", "5004"], rating_key="4001")
    first = sink.append("Playlist A", [_plex_track("5001", "Example Song")])
    assert first.status == "added"
    assert first.rating_keys == ["5001"]
    name = normalize_playlist_name("Playlist A")
    assert ledger.plex_added_keys(name) == {"5001"}
    assert server.playlists[0]["items"] == ["5002", "5004", "5001"]

    server.playlists[0]["items"] = ["5002", "5004"]
    session.calls.clear()
    second = sink.append("Playlist A", [_plex_track("5001", "Example Song")])
    assert second.status == "removed_in_plex"
    assert second.rating_keys == ["5001"]
    assert _mutations(session) == []
    assert server.playlists[0]["items"] == ["5002", "5004"]


def test_deleted_playlist_is_not_recreated_for_a_removed_key(tmp_path: Path):
    server, session, ledger, _client, sink, _clock = _stack(tmp_path)
    server.add_track(rating_key="5001", title="Example Song", artist=ARTIST, file_path=_server("Example Song"))
    server.add_track(rating_key="5003", title="Other Song", artist=OTHER, file_path=_server("Other Song"))
    added = sink.append("Playlist A", [_plex_track("5001", "Example Song")])
    assert added.status == "added"
    assert server.playlists[0]["items"] == ["5001"]
    server.playlists.clear()
    session.calls.clear()
    removed = sink.append("Playlist A", [_plex_track("5001", "Example Song")])
    assert removed.status == "removed_in_plex"
    assert removed.rating_keys == ["5001"]
    assert server.playlists == []
    assert _mutations(session) == []

    created = sink.append("Playlist A", [_plex_track("5003", "Other Song")])
    assert created.status == "added"
    assert created.rating_keys == ["5003"]
    assert server.playlists[0]["items"] == ["5003"]
    assert ledger.plex_added_keys(normalize_playlist_name("Playlist A")) == {"5001", "5003"}
