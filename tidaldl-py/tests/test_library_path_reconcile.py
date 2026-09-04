"""Incremental library path reconciler — identity-preserving folder moves."""

from __future__ import annotations

import os
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

from tidal_dl.helper.library_db import LibraryDB


def _write_wav(path: Path, *, frames: int = 44100, extra: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\x00\x00" * frames)
    if extra:
        with path.open("ab") as handle:
            handle.write(extra)
    return path


def _identity_from_path(path: Path, **meta) -> dict:
    st = path.stat()
    return {
        "file_size": st.st_size,
        "file_mtime": int(st.st_mtime),
        "file_inode": st.st_ino,
        "file_device": st.st_dev,
        **meta,
    }


def _open_db(tmp_path: Path) -> LibraryDB:
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    return db


def _seed(
    db: LibraryDB,
    path: Path,
    *,
    artist: str = "Billy Idol",
    title: str = "Flesh For Fantasy",
    album: str = "Greatest Hits",
    duration: int = 278,
    codec: str = "pcm",
    play_count: int = 0,
    with_identity: bool = True,
    **extra,
) -> dict:
    identity = _identity_from_path(path) if with_identity and path.is_file() else {}
    db.record(
        str(path),
        status="tagged",
        artist=artist,
        title=title,
        album=album,
        duration=duration,
        quality="WAV",
        fmt="WAV",
        codec=codec,
        metadata_complete=True,
        **identity,
        **extra,
    )
    if play_count:
        db._conn.execute(
            "UPDATE scanned SET play_count = ?, last_played = 1700000000 WHERE path = ?",
            (play_count, str(path)),
        )
    db.commit()
    return db.get(str(path))


def _metadata_for(path: Path, **overrides) -> dict:
    meta = {
        "name": path.stem,
        "artist": "Billy Idol",
        "album": "Greatest Hits",
        "duration": 278,
        "codec": "pcm",
        "isrc": "",
        "genre": None,
        "quality": "WAV",
        "format": "WAV",
        "album_artist": "Billy Idol",
    }
    meta.update(overrides)
    return meta


def _reconciler(db: LibraryDB, roots: list[Path], metadata: dict[str, dict] | None = None, **kwargs):
    from tidal_dl.helper.library_reconcile import PathReconciler

    reads: list[str] = []
    catalog = metadata or {}

    def read_metadata(path: Path) -> dict | None:
        reads.append(str(path))
        key = str(path)
        if key in catalog:
            return catalog[key]
        return _metadata_for(path)

    reconciler = PathReconciler(
        db,
        [Path(root) for root in roots],
        read_metadata=read_metadata,
        **kwargs,
    )
    reconciler.metadata_reads = reads
    return reconciler


class TestMovedFileResolvesInBrowseAndPlayback:
    def test_indexed_file_moved_within_root_is_visible_at_new_path(self, tmp_path):
        root = tmp_path / "Music"
        src = root / "Billy Idol" / "Greatest Hits" / "01 Flesh For Fantasy.wav"
        dest = root / "Billy Idol" / "Hits" / "01 Flesh For Fantasy.wav"
        _write_wav(src)
        db = _open_db(tmp_path)
        _seed(db, src, play_count=20)
        db.log_play_event(str(src), artist="Billy Idol", duration=278, played_at=1700000000)
        db.commit()

        rec = _reconciler(db, [root], metadata={
            str(src): _metadata_for(src, name="Flesh For Fantasy"),
            str(dest): _metadata_for(dest, name="Flesh For Fantasy"),
        })
        rec.reconcile(force=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)

        rec.reconcile(force=True)

        tracks = db.album_tracks("Billy Idol", "Greatest Hits")
        paths = {row["path"] for row in tracks}
        assert str(dest) in paths
        assert str(src) not in paths
        assert Path(tracks[0]["path"]).is_file()
        page, total = db.tracks_page()
        assert total == 1
        assert page[0]["path"] == str(dest)
        db.close()


class TestIdentityMigration:
    def test_external_move_migrates_row_instead_of_recreate(self, tmp_path):
        root = tmp_path / "Music"
        src = root / "A" / "track.wav"
        dest = root / "B" / "track.wav"
        _write_wav(src)
        db = _open_db(tmp_path)
        _seed(db, src, artist="Artist", title="Track", album="Album", duration=1)
        rec = _reconciler(db, [root], metadata={
            str(src): _metadata_for(src, name="Track", artist="Artist", album="Album", duration=1),
            str(dest): _metadata_for(dest, name="Track", artist="Artist", album="Album", duration=1),
        })
        rec.reconcile(force=True)
        row_id_before = db._conn.execute(
            "SELECT rowid FROM scanned WHERE path = ?", (str(src),)
        ).fetchone()[0]

        dest.parent.mkdir(parents=True)
        src.rename(dest)
        rec.reconcile(force=True)

        assert db.get(str(src)) is None
        row = db.get(str(dest))
        assert row is not None
        row_id_after = db._conn.execute(
            "SELECT rowid FROM scanned WHERE path = ?", (str(dest),)
        ).fetchone()[0]
        assert row_id_after == row_id_before
        db.close()

    def test_move_between_album_dirs_preserves_history_and_favorites(self, tmp_path):
        root = tmp_path / "Music"
        src = root / "Billy Idol" / "Greatest Hits" / "07 Flesh For Fantasy.wav"
        dest = root / "Billy Idol" / "Vital Idol" / "07 Flesh For Fantasy.wav"
        _write_wav(src)
        db = _open_db(tmp_path)
        _seed(db, src, play_count=20)
        db.add_favorite(path=str(src), artist="Billy Idol", title="Flesh For Fantasy", album="Greatest Hits")
        db.log_play_event(str(src), artist="Billy Idol", duration=278, played_at=1700000010)
        db.log_play_event(str(src), artist="Billy Idol", duration=278, played_at=1700000020)
        db.commit()

        rec = _reconciler(db, [root], metadata={
            str(src): _metadata_for(src, name="Flesh For Fantasy"),
            str(dest): _metadata_for(dest, name="Flesh For Fantasy"),
        })
        rec.reconcile(force=True)
        dest.parent.mkdir(parents=True)
        src.rename(dest)
        rec.reconcile(force=True)

        row = db.get(str(dest))
        assert row["play_count"] == 20
        assert row["last_played"] == 1700000000
        assert db.is_favorite(path=str(dest))
        assert not db.is_favorite(path=str(src))
        events = db._conn.execute(
            "SELECT path FROM play_events ORDER BY played_at"
        ).fetchall()
        assert [e["path"] for e in events] == [str(dest), str(dest)]
        db.close()


class TestMissingAndNew:
    def test_deletion_marks_missing_and_hides_from_browse(self, tmp_path):
        root = tmp_path / "Music"
        path = root / "Artist" / "Album" / "gone.wav"
        _write_wav(path)
        db = _open_db(tmp_path)
        _seed(db, path, artist="Artist", title="Gone", album="Album", duration=1)
        rec = _reconciler(db, [root], metadata={
            str(path): _metadata_for(path, name="Gone", artist="Artist", album="Album", duration=1),
        })
        rec.reconcile(force=True)
        path.unlink()
        rec.reconcile(force=True)

        row = db.get(str(path))
        assert row is not None
        assert row["missing_since"] is not None
        assert db.album_tracks("Artist", "Album") == []
        assert db.all_albums() == []
        assert db.artists_page()[1] == 0
        assert db.tracks_page()[1] == 0
        db.close()

    def test_genuinely_new_file_is_indexed(self, tmp_path):
        root = tmp_path / "Music"
        existing = root / "A" / "old.wav"
        newbie = root / "A" / "new.wav"
        _write_wav(existing)
        db = _open_db(tmp_path)
        _seed(db, existing, artist="A", title="Old", album="LP", duration=1)
        rec = _reconciler(db, [root], metadata={
            str(existing): _metadata_for(existing, name="Old", artist="A", album="LP", duration=1),
            str(newbie): _metadata_for(newbie, name="New", artist="A", album="LP", duration=1),
        })
        rec.reconcile(force=True)
        _write_wav(newbie)
        rec.reconcile(force=True)

        row = db.get(str(newbie))
        assert row is not None
        assert row["title"] == "New"
        assert row["missing_since"] is None
        db.close()


class TestMatchGuards:
    def test_edition_and_size_difference_is_not_merged(self, tmp_path):
        from tidal_dl.helper.library_reconcile import FileIdentity, plan_path_reconcile

        vanished = FileIdentity(
            path="/Music/Billy Idol/Greatest Hits/07 Billy Idol - Flesh For Fantasy.flac",
            size=8_000_000,
            duration=278,
            codec="flac",
            title="Flesh For Fantasy",
            artist="Billy Idol",
            album="Greatest Hits",
            isrc="USCH39900058",
        )
        appeared = FileIdentity(
            path="/Music/Billy Idol/Greatest Hits/Flesh For Fantasy (Remastered 1999).flac",
            size=9_500_000,
            duration=278,
            codec="flac",
            title="Flesh For Fantasy (Remastered 1999)",
            artist="Billy Idol",
            album="Greatest Hits",
            isrc="USCH39900058",
        )
        plan = plan_path_reconcile([vanished], [appeared])
        assert plan.migrations == []
        assert vanished.path in plan.mark_missing
        assert appeared.path in plan.index_new

    def test_same_basename_different_edition_not_merged(self):
        from tidal_dl.helper.library_reconcile import FileIdentity, plan_path_reconcile

        vanished = FileIdentity(
            path="/Music/old/Flesh For Fantasy.flac",
            size=1_000,
            duration=278,
            codec="flac",
            title="Flesh For Fantasy",
            artist="Billy Idol",
            album="Vital Idol",
        )
        appeared = FileIdentity(
            path="/Music/new/Flesh For Fantasy.flac",
            size=2_000,
            duration=278,
            codec="flac",
            title="Flesh For Fantasy (Remastered 1999)",
            artist="Billy Idol",
            album="Vital Idol",
        )
        plan = plan_path_reconcile([vanished], [appeared])
        assert plan.migrations == []

    def test_two_equally_good_candidates_stay_unresolved(self):
        from tidal_dl.helper.library_reconcile import FileIdentity, plan_path_reconcile

        vanished = FileIdentity(
            path="/Music/old/track.wav",
            size=100,
            duration=10,
            codec="pcm",
            title="Song",
            artist="Artist",
            album="Album",
        )
        a1 = FileIdentity(
            path="/Music/new/a.wav",
            size=100,
            duration=10,
            codec="pcm",
            title="Song",
            artist="Artist",
            album="Album",
        )
        a2 = FileIdentity(
            path="/Music/new/b.wav",
            size=100,
            duration=10,
            codec="pcm",
            title="Song",
            artist="Artist",
            album="Album",
        )
        plan = plan_path_reconcile([vanished], [a1, a2])
        assert plan.migrations == []
        assert vanished.path in plan.mark_missing
        assert {a1.path, a2.path} <= set(plan.index_new)


class TestCheapChangeDetection:
    def test_unchanged_root_does_near_zero_work(self, tmp_path):
        root = tmp_path / "Music"
        track = root / "A" / "Album" / "t.wav"
        _write_wav(track)
        db = _open_db(tmp_path)
        _seed(db, track, artist="A", title="T", album="Album", duration=1)

        file_stats: list[str] = []
        real_stat = os.stat

        def spy_stat(path, *args, **kwargs):
            target = str(path)
            if Path(target).is_file() and Path(target).suffix.lower() in {".wav", ".flac", ".mp3"}:
                file_stats.append(target)
            return real_stat(path, *args, **kwargs)

        rec = _reconciler(
            db,
            [root],
            metadata={str(track): _metadata_for(track, name="T", artist="A", album="Album", duration=1)},
            stat_fn=spy_stat,
        )
        rec.reconcile(force=True)
        rec.metadata_reads.clear()
        file_stats.clear()
        rec.reconcile(force=True)

        assert rec.metadata_reads == []
        assert file_stats == []
        db.close()

    def test_nested_directory_change_is_not_skipped(self, tmp_path):
        root = tmp_path / "Music"
        src = root / "deep" / "nested" / "album" / "track.wav"
        dest = root / "deep" / "nested" / "other" / "track.wav"
        _write_wav(src)
        db = _open_db(tmp_path)
        _seed(db, src, artist="A", title="Track", album="Album", duration=1)
        rec = _reconciler(db, [root], metadata={
            str(src): _metadata_for(src, name="Track", artist="A", album="Album", duration=1),
            str(dest): _metadata_for(dest, name="Track", artist="A", album="Album", duration=1),
        })
        first = rec.reconcile(force=True)
        assert not first.unchanged or db.dir_signatures()

        root_mtime = os.stat(root).st_mtime
        known_count = len(db.known_paths())
        dest.parent.mkdir(parents=True)
        src.rename(dest)
        assert os.stat(root).st_mtime == root_mtime
        assert len(list(root.rglob("*.wav"))) == known_count

        rec.reconcile(force=True)
        assert db.get(str(dest)) is not None
        assert db.get(str(src)) is None
        db.close()


class TestLegacyAndInodeFallback:
    def test_legacy_null_size_inode_relocates_via_tags_and_basename(self, tmp_path):
        root = tmp_path / "Music"
        src = root / "A" / "Flesh For Fantasy.wav"
        dest = root / "B" / "Flesh For Fantasy.wav"
        _write_wav(src, frames=44100)
        db = _open_db(tmp_path)
        db.record(
            str(src),
            status="tagged",
            artist="Billy Idol",
            title="Flesh For Fantasy",
            album="Greatest Hits",
            duration=1,
            codec="pcm",
            metadata_complete=True,
        )
        db.commit()
        row = db.get(str(src))
        assert row["file_size"] is None
        assert row["file_inode"] is None

        rec = _reconciler(db, [root], metadata={
            str(src): _metadata_for(src, name="Flesh For Fantasy", duration=1),
            str(dest): _metadata_for(dest, name="Flesh For Fantasy", duration=1),
        })
        rec.reconcile(force=True)
        dest.parent.mkdir(parents=True)
        src.rename(dest)
        rec.reconcile(force=True)

        assert db.get(str(dest)) is not None
        assert db.get(str(src)) is None
        db.close()

    def test_inode_zero_falls_back_to_content_identity(self, tmp_path):
        from tidal_dl.helper.library_reconcile import FileIdentity, plan_path_reconcile

        vanished = FileIdentity(
            path="/Music/old/song.wav",
            size=500,
            inode=0,
            device=1,
            duration=12,
            codec="pcm",
            title="Song",
            artist="Artist",
            album="Album",
        )
        appeared = FileIdentity(
            path="/Music/new/song.wav",
            size=500,
            inode=0,
            device=1,
            duration=12,
            codec="pcm",
            title="Song",
            artist="Artist",
            album="Album",
        )
        other = FileIdentity(
            path="/Music/new/other.wav",
            size=500,
            inode=0,
            device=1,
            duration=12,
            codec="pcm",
            title="Different",
            artist="Artist",
            album="Album",
        )
        plan = plan_path_reconcile([vanished], [appeared, other])
        assert plan.migrations == [(vanished.path, appeared.path)]


class TestUnreadableDirectory:
    def test_unreadable_directory_is_skipped_without_pruning(self, tmp_path, monkeypatch):
        root = tmp_path / "Music"
        keep = root / "A" / "keep.wav"
        hidden_dir = root / "offline"
        hidden = hidden_dir / "lost.wav"
        _write_wav(keep)
        _write_wav(hidden)
        db = _open_db(tmp_path)
        _seed(db, keep, artist="A", title="Keep", album="LP", duration=1)
        _seed(db, hidden, artist="B", title="Lost", album="LP2", duration=1)
        rec = _reconciler(db, [root], metadata={
            str(keep): _metadata_for(keep, name="Keep", artist="A", album="LP", duration=1),
            str(hidden): _metadata_for(hidden, name="Lost", artist="B", album="LP2", duration=1),
        })
        rec.reconcile(force=True)

        real_scandir = os.scandir

        def selective_scandir(path):
            if Path(path) == hidden_dir:
                raise OSError("volume offline")
            return real_scandir(path)

        rec.scandir_fn = selective_scandir
        rec.reconcile(force=True)

        assert db.get(str(hidden)) is not None
        assert db.get(str(hidden))["missing_since"] is None
        assert db.get(str(keep))["missing_since"] is None
        db.close()


class TestScanFingerprintRegression:
    def test_background_scan_does_not_skip_nested_move(self, tmp_path, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        root = tmp_path / "Music"
        src = root / "deep" / "nested" / "album" / "track.wav"
        dest = root / "deep" / "nested" / "moved" / "track.wav"
        _write_wav(src)

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(root), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
        monkeypatch.setattr(library_api, "_album_cards", lambda db, *args, **kwargs: [])
        monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)
        monkeypatch.setattr(library_api, "_has_local_art", lambda path: False)
        monkeypatch.setattr(
            library_api,
            "_read_metadata",
            lambda path, scan_dirs=None: {
                "path": str(path),
                "name": "Track",
                "artist": "A",
                "album": "Album",
                "duration": 1,
                "isrc": "",
                "genre": None,
                "quality": "WAV",
                "format": "WAV",
                "codec": "pcm",
                "metadata_complete": True,
                "is_local": True,
            },
        )
        library_api._scan_running = True
        library_api._background_scan(False)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        assert str(src) in db.known_paths()
        db.close()

        dest.parent.mkdir(parents=True)
        src.rename(dest)
        library_api._scan_running = True
        library_api._background_scan(False)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        assert str(dest) in db.known_paths()
        assert str(src) not in db.known_paths() or db.get(str(src)) is None
        row = db.get(str(dest))
        assert row is not None
        assert row["missing_since"] is None
        db.close()


class TestPlaybackBackstop:
    def _playback_client(self, tmp_path, monkeypatch, root):
        import re

        from fastapi.testclient import TestClient

        import tidal_dl.gui.api.library as library_api
        import tidal_dl.gui.api.playback as playback_api
        from tidal_dl.gui import create_app

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(root), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        orig_init = threading.Thread.__init__

        def patched_thread_init(self, *args, **kwargs):
            if kwargs.get("name") == "library-path-reconcile":
                kwargs = dict(kwargs, target=lambda: None)
            return orig_init(self, *args, **kwargs)

        monkeypatch.setattr(threading.Thread, "__init__", patched_thread_init)
        monkeypatch.setattr(playback_api, "get_download_paths", lambda: [str(root)])
        monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
        monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)
        monkeypatch.setattr(library_api, "_has_local_art", lambda path: False)
        monkeypatch.setattr(
            library_api,
            "_read_metadata",
            lambda path, scan_dirs=None: {
                "path": str(path),
                "name": "Song",
                "artist": "A",
                "album": "LP",
                "duration": 1,
                "isrc": "",
                "genre": None,
                "quality": "WAV",
                "format": "WAV",
                "codec": "pcm",
                "metadata_complete": True,
                "is_local": True,
            },
        )
        library_api._reconcile_running = False
        library_api._scan_running = False
        library_api._reconcile_last_at = 0.0
        library_api._playback_migration_cache.clear()

        client = TestClient(create_app(port=8765, job_db_path=tmp_path / "jobs.db"))
        index = client.get("/", headers={"host": "localhost:8765"})
        match = re.search(r'name="csrf-token" content="([^"]+)"', index.text)
        headers = {"host": "localhost:8765"}
        if match:
            headers["X-CSRF-Token"] = match.group(1)
        return client, headers, library_api

    def test_playback_serves_cached_migration_after_reconcile(self, tmp_path, monkeypatch):
        root = tmp_path / "Music"
        src = root / "A" / "song.wav"
        dest = root / "B" / "song.wav"
        _write_wav(src, frames=8000)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _seed(db, src, artist="A", title="Song", album="LP", duration=1)
        rec = _reconciler(db, [root], metadata={
            str(src): _metadata_for(src, name="Song", artist="A", album="LP", duration=1),
            str(dest): _metadata_for(dest, name="Song", artist="A", album="LP", duration=1),
        })
        rec.reconcile(force=True)
        dest.parent.mkdir(parents=True)
        src.rename(dest)
        result = rec.reconcile(force=True)
        db.close()

        client, headers, library_api = self._playback_client(tmp_path, monkeypatch, root)
        library_api._remember_playback_migrations(result.migrations)
        with client:
            resp = client.get(
                "/api/playback/local",
                params={"path": str(src)},
                headers=headers,
            )
        assert resp.status_code == 200

    def test_playback_serves_scan_time_move_from_cache(self, tmp_path, monkeypatch):
        root = tmp_path / "Music"
        src = root / "A" / "song.wav"
        dest = root / "B" / "song.wav"
        _write_wav(src, frames=8000)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _seed(db, src, artist="A", title="Song", album="LP", duration=1)
        rec = _reconciler(db, [root], metadata={
            str(src): _metadata_for(src, name="Song", artist="A", album="LP", duration=1),
            str(dest): _metadata_for(dest, name="Song", artist="A", album="LP", duration=1),
        })
        rec.reconcile(force=True)
        dest.parent.mkdir(parents=True)
        src.rename(dest)
        db.close()

        client, headers, library_api = self._playback_client(tmp_path, monkeypatch, root)
        library_api._scan_running = True
        library_api._background_scan(False)
        assert library_api.playback_resolved_path(str(src)) == str(dest)

        reconcile_calls = 0
        walk_calls = 0

        def boom(**kwargs):
            nonlocal reconcile_calls
            reconcile_calls += 1
            return {"status": "started"}

        class SpyReconciler:
            def reconcile(self, **kwargs):
                nonlocal walk_calls
                walk_calls += 1
                raise AssertionError("GET playback must not sync-reconcile")

        monkeypatch.setattr(library_api, "request_path_reconcile", boom)
        monkeypatch.setattr(library_api, "_path_reconciler", lambda db, scan_dirs: SpyReconciler())
        with client:
            resp = client.get(
                "/api/playback/local",
                params={"path": str(src)},
                headers=headers,
            )
        assert resp.status_code == 200
        assert reconcile_calls == 0
        assert walk_calls == 0

    def test_playback_queues_guarded_reconcile_for_known_missing_row(self, tmp_path, monkeypatch):
        root = tmp_path / "Music"
        src = root / "A" / "song.wav"
        _write_wav(src, frames=8000)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _seed(db, src, artist="A", title="Song", album="LP", duration=1)
        db.close()
        src.unlink()

        client, headers, library_api = self._playback_client(tmp_path, monkeypatch, root)
        reconcile_calls: list[dict] = []

        def track_reconcile(**kwargs):
            reconcile_calls.append(kwargs)
            return {"status": "started"}

        monkeypatch.setattr(library_api, "request_path_reconcile", track_reconcile)
        with client:
            resp = client.get(
                "/api/playback/local",
                params={"path": str(src)},
                headers=headers,
            )
        playback_calls = [call for call in reconcile_calls if call.get("force") is False]
        assert resp.status_code == 202
        assert len(playback_calls) == 1

    def test_playback_forbidden_path_never_triggers_reconcile(self, tmp_path, monkeypatch):
        root = tmp_path / "Music"
        root.mkdir()
        client, headers, library_api = self._playback_client(tmp_path, monkeypatch, root)
        reconcile_calls = 0
        walk_calls = 0

        def boom(**kwargs):
            nonlocal reconcile_calls
            reconcile_calls += 1
            return {"status": "started"}

        class SpyReconciler:
            def reconcile(self, **kwargs):
                nonlocal walk_calls
                walk_calls += 1
                raise AssertionError("walk should not run")

        monkeypatch.setattr(library_api, "request_path_reconcile", boom)
        monkeypatch.setattr(library_api, "_path_reconciler", lambda db, scan_dirs: SpyReconciler())
        with client:
            for _ in range(5):
                resp = client.get(
                    "/api/playback/local",
                    params={"path": "/etc/passwd"},
                    headers=headers,
                )
                assert resp.status_code == 403
        assert reconcile_calls == 0
        assert walk_calls == 0

    def test_playback_rejects_traversal_symlink_and_encoded_paths(self, tmp_path, monkeypatch):
        from urllib.parse import quote

        root = tmp_path / "Music"
        secret = tmp_path / "secret.flac"
        secret.write_bytes(b"secret")
        inside = root / "A" / "song.wav"
        _write_wav(inside, frames=8000)
        link = root / "escape.wav"
        link.symlink_to(secret)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _seed(db, inside, artist="A", title="Song", album="LP", duration=1)
        db.close()

        client, headers, library_api = self._playback_client(tmp_path, monkeypatch, root)
        reconcile_calls = 0

        def boom(**kwargs):
            nonlocal reconcile_calls
            reconcile_calls += 1
            return {"status": "started"}

        monkeypatch.setattr(library_api, "request_path_reconcile", boom)
        attacks = [
            str(root / ".." / "secret.flac"),
            str(root) + "/%2e%2e/secret.flac",
            str(link),
            str(tmp_path / "not-indexed.wav"),
        ]
        with client:
            for attack in attacks:
                resp = client.get(
                    "/api/playback/local",
                    params={"path": attack},
                    headers=headers,
                )
                assert resp.status_code == 403, attack
            encoded = client.get(
                "/api/playback/local?path=" + quote(str(root) + "/../secret.flac", safe=""),
                headers=headers,
            )
            assert encoded.status_code == 403
        assert reconcile_calls == 0

    def test_playback_concurrent_missing_library_paths_coalesce(self, tmp_path, monkeypatch):
        root = tmp_path / "Music"
        src = root / "A" / "song.wav"
        _write_wav(src, frames=8000)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _seed(db, src, artist="A", title="Song", album="LP", duration=1)
        db.close()
        src.unlink()

        client, headers, library_api = self._playback_client(tmp_path, monkeypatch, root)
        orig_init = threading.Thread.__init__

        def patched_thread_init(self, *args, **kwargs):
            if kwargs.get("target") is library_api._background_path_reconcile:
                kwargs = dict(kwargs, target=lambda: None)
            if kwargs.get("name") == "library-path-reconcile":
                kwargs = dict(kwargs, target=lambda: None)
            return orig_init(self, *args, **kwargs)

        monkeypatch.setattr(threading.Thread, "__init__", patched_thread_init)
        with client:
            first = client.get(
                "/api/playback/local",
                params={"path": str(src)},
                headers=headers,
            )
            second = client.get(
                "/api/playback/local",
                params={"path": str(src)},
                headers=headers,
            )
        library_api._reconcile_running = False
        assert first.status_code == 202
        assert second.status_code == 409


class TestReconcileApi:
    def test_reconcile_endpoints_follow_scan_pattern(self, client):
        started = client.post("/api/library/reconcile", headers=client._headers)
        assert started.status_code == 200
        body = started.json()
        assert body["status"] in {"started", "already_running", "debounced"}
        status = client.get("/api/library/reconcile/status", headers=client._host_header)
        assert status.status_code == 200
        data = status.json()
        assert "reconciling" in data
        assert "done" in data
        assert "phase" in data

    def test_manual_refresh_forces_reconcile(self, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        calls = []

        def capture(*, force=False):
            calls.append(force)
            return {"status": "started"}

        monkeypatch.setattr(library_api, "request_path_reconcile", capture)
        assert library_api.reconcile_library_paths(force=True) == {"status": "started"}
        assert calls == [True]

    def test_focus_and_unforced_post_keep_debounce(self, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        calls = []

        def capture(*, force=False):
            calls.append(force)
            return {"status": "debounced"}

        monkeypatch.setattr(library_api, "request_path_reconcile", capture)
        assert library_api.reconcile_library_paths() == {"status": "debounced"}
        assert library_api.reconcile_library_paths(force=False) == {"status": "debounced"}
        assert calls == [False, False]

    def test_http_refresh_query_forces_focus_does_not(self, client, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        calls = []

        def capture(*, force=False):
            calls.append(force)
            return {"status": "started"}

        monkeypatch.setattr(library_api, "request_path_reconcile", capture)
        unforced = client.post("/api/library/reconcile", headers=client._headers)
        forced = client.post("/api/library/reconcile?force=true", headers=client._headers)
        assert unforced.status_code == 200
        assert forced.status_code == 200
        assert unforced.json() == {"status": "started"}
        assert forced.json() == {"status": "started"}
        assert calls == [False, True]

        views = Path(__file__).resolve().parents[1] / "tidal_dl" / "gui" / "static" / "views.js"
        source = views.read_text()
        assert "api('/library/reconcile?force=true', { method: 'POST' })" in source
        assert source.count("api('/library/reconcile', { method: 'POST' })") >= 2
        gui_init = Path(__file__).resolve().parents[1] / "tidal_dl" / "gui" / "__init__.py"
        assert "request_path_reconcile()" in gui_init.read_text()
        assert "request_path_reconcile(force=False)" in Path(
            library_api.__file__
        ).read_text()


def _album_identities(old_dir: str, new_dir: str, names: list[str], *, size: int = 1000):
    from tidal_dl.helper.library_reconcile import FileIdentity

    vanished = [
        FileIdentity(
            path=f"{old_dir}/{name}",
            size=size + index,
            duration=200 + index,
            codec="flac",
            title=f"Track {index + 1}",
            artist="Linkin Park",
            album="Hybrid Theory",
        )
        for index, name in enumerate(names)
    ]
    appeared = [
        FileIdentity(
            path=f"{new_dir}/{name}",
            size=size + index,
            duration=200 + index,
            codec="flac",
            title=f"Track {index + 1}",
            artist="Linkin Park",
            album="Hybrid Theory",
        )
        for index, name in enumerate(names)
    ]
    return vanished, appeared


class TestDirectoryMoveFastPath:
    def test_whole_directory_rename_is_one_directory_match(self):
        from tidal_dl.helper.library_reconcile import plan_path_reconcile

        names = [f"{i:02d} Track {i}.flac" for i in range(1, 9)]
        old_dir = "/Volumes/Music/Linkin Park/Linkin Park - Hybrid Theory (20th Anniversary Edition)"
        new_dir = "/Volumes/Music/Linkin Park/Hybrid Theory (20th Anniversary Edition)"
        vanished, appeared = _album_identities(old_dir, new_dir, names)

        plan = plan_path_reconcile(vanished, appeared)

        assert plan.directory_moves == [(old_dir, new_dir)]
        assert plan.file_match_comparisons == 0
        assert len(plan.migrations) == 8
        assert {(Path(old).name, Path(new).name) for old, new in plan.migrations} == {
            (name, name) for name in names
        }
        assert plan.mark_missing == []
        assert plan.index_new == []

    def test_directory_rename_different_edition_is_not_merged(self):
        from tidal_dl.helper.library_reconcile import FileIdentity, plan_path_reconcile

        names = [f"{i:02d} Hit {i}.flac" for i in range(1, 5)]
        old_dir = "/Volumes/Music/Billy Idol/Greatest Hits"
        new_dir = "/Volumes/Music/Billy Idol/Greatest Hits (Remastered)"
        vanished = [
            FileIdentity(
                path=f"{old_dir}/{name}",
                size=4000 + index,
                duration=180 + index,
                codec="flac",
                title=f"Hit {index + 1}",
                artist="Billy Idol",
                album="Greatest Hits",
            )
            for index, name in enumerate(names)
        ]
        appeared = [
            FileIdentity(
                path=f"{new_dir}/{name}",
                size=4000 + index,
                duration=180 + index,
                codec="flac",
                title=f"Hit {index + 1}",
                artist="Billy Idol",
                album="Greatest Hits (Remastered)",
            )
            for index, name in enumerate(names)
        ]

        plan = plan_path_reconcile(vanished, appeared)

        assert plan.directory_moves == []
        assert plan.migrations == []
        assert set(plan.mark_missing) == {row.path for row in vanished}
        assert set(plan.index_new) == {row.path for row in appeared}

    def test_whole_album_directory_rename_migrates_history(self, tmp_path):
        root = tmp_path / "Music"
        old_dir = root / "Linkin Park" / "Linkin Park - Hybrid Theory (20th Anniversary Edition)"
        new_dir = root / "Linkin Park" / "Hybrid Theory (20th Anniversary Edition)"
        names = [f"{i:02d} Track {i}.wav" for i in range(1, 7)]
        files = [_write_wav(old_dir / name, frames=8000 + i * 100) for i, name in enumerate(names)]
        db = _open_db(tmp_path)
        metadata = {}
        for index, path in enumerate(files):
            metadata[str(path)] = _metadata_for(
                path,
                name=f"Track {index + 1}",
                artist="Linkin Park",
                album="Hybrid Theory",
                duration=1,
            )
            _seed(
                db,
                path,
                artist="Linkin Park",
                title=f"Track {index + 1}",
                album="Hybrid Theory",
                duration=1,
                play_count=10 + index,
            )
            db.log_play_event(str(path), artist="Linkin Park", duration=1, played_at=1700000000 + index)
        db.commit()

        rec = _reconciler(db, [root], metadata=metadata)
        rec.reconcile(force=True)
        old_dir.rename(new_dir)
        for index, path in enumerate(files):
            dest = new_dir / path.name
            metadata[str(dest)] = _metadata_for(
                dest,
                name=f"Track {index + 1}",
                artist="Linkin Park",
                album="Hybrid Theory",
                duration=1,
            )

        progress = []
        result = rec.reconcile(force=True, on_progress=lambda **kw: progress.append(kw))

        assert result.directory_moves == [(str(old_dir), str(new_dir))]
        assert result.file_match_comparisons == 0
        assert len(result.migrations) == 6
        for index, name in enumerate(names):
            dest = new_dir / name
            row = db.get(str(dest))
            assert row is not None
            assert row["play_count"] == 10 + index
            assert db.get(str(old_dir / name)) is None
        events = db._conn.execute("SELECT path FROM play_events ORDER BY played_at").fetchall()
        assert [Path(row["path"]).name for row in events] == names
        assert any(item.get("phase") == "migrating" for item in progress)
        db.close()

    def test_first_run_without_dir_signatures_heals_renamed_album(self, tmp_path):
        root = tmp_path / "Music"
        old_dir = root / "Cuphead" / "Official Soundtrack FLAC"
        new_dir = root / "Cuphead" / "Official Soundtrack"
        names = [f"{i:02d} Cue {i}.wav" for i in range(1, 5)]
        files = [_write_wav(old_dir / name, frames=6000 + i * 50) for i, name in enumerate(names)]
        db = _open_db(tmp_path)
        metadata = {}
        for index, path in enumerate(files):
            db.record(
                str(path),
                status="tagged",
                artist="Cuphead",
                title=f"Cue {index + 1}",
                album="Official Soundtrack",
                duration=1,
                codec="pcm",
                metadata_complete=True,
            )
            db._conn.execute(
                "UPDATE scanned SET play_count = ? WHERE path = ?",
                (3 + index, str(path)),
            )
            metadata[str(path)] = _metadata_for(
                path, name=f"Cue {index + 1}", artist="Cuphead", album="Official Soundtrack", duration=1,
            )
        db.commit()
        assert db.dir_signatures() == {}
        assert db.get(str(files[0]))["file_size"] is None

        old_dir.rename(new_dir)
        for path in files:
            dest = new_dir / path.name
            metadata[str(dest)] = _metadata_for(
                dest, name=path.stem, artist="Cuphead", album="Official Soundtrack", duration=1,
            )

        rec = _reconciler(db, [root], metadata=metadata)
        result = rec.reconcile(force=True)

        assert result.directory_moves == [(str(old_dir), str(new_dir))]
        assert result.file_match_comparisons == 0
        for index, name in enumerate(names):
            row = db.get(str(new_dir / name))
            assert row is not None
            assert row["play_count"] == 3 + index
        db.close()

    def test_copied_remaster_directory_is_not_merged(self, tmp_path):
        root = tmp_path / "Music"
        old_dir = root / "Billy Idol" / "Greatest Hits"
        new_dir = root / "Billy Idol" / "Greatest Hits (Remastered)"
        names = [f"{i:02d} Hit {i}.wav" for i in range(1, 5)]
        files = [
            _write_wav(old_dir / name, frames=8000 + i * 400, extra=bytes([i + 1]))
            for i, name in enumerate(names)
        ]
        db = _open_db(tmp_path)
        metadata = {}
        for index, path in enumerate(files):
            metadata[str(path)] = _metadata_for(
                path, name=f"Hit {index + 1}", artist="Billy Idol", album="Greatest Hits", duration=1,
            )
            _seed(
                db,
                path,
                artist="Billy Idol",
                title=f"Hit {index + 1}",
                album="Greatest Hits",
                duration=1,
                play_count=5,
            )
        rec = _reconciler(db, [root], metadata=metadata)
        rec.reconcile(force=True)

        new_dir.mkdir(parents=True)
        for path in files:
            dest = new_dir / path.name
            dest.write_bytes(path.read_bytes())
            metadata[str(dest)] = _metadata_for(
                dest,
                name=f"Hit {names.index(path.name) + 1}",
                artist="Billy Idol",
                album="Greatest Hits (Remastered)",
                duration=1,
            )
        for path in files:
            path.unlink()

        result = rec.reconcile(force=True)

        assert result.directory_moves == []
        assert result.migrations == []
        for name in names:
            old_row = db.get(str(old_dir / name))
            new_row = db.get(str(new_dir / name))
            assert old_row is not None
            assert old_row["missing_since"] is not None
            assert old_row["play_count"] == 5
            assert new_row is not None
            assert new_row["missing_since"] is None
            assert new_row["play_count"] in (None, 0)
        db.close()


class TestRemountAndRestoreGuards:
    def test_empty_readable_root_does_not_hide_library(self, tmp_path, monkeypatch):
        from tidal_dl.helper import library_reconcile as rec_mod

        monkeypatch.setattr(rec_mod, "RECONCILE_REMOUNT_MIN_ROWS", 2)
        root = tmp_path / "Music"
        files = [
            _write_wav(root / "A" / f"{i}.wav", frames=2000)
            for i in range(4)
        ]
        db = _open_db(tmp_path)
        metadata = {}
        for path in files:
            metadata[str(path)] = _metadata_for(path, name=path.stem, artist="A", album="LP", duration=1)
            _seed(db, path, artist="A", title=path.stem, album="LP", duration=1)
        rec = _reconciler(db, [root], metadata=metadata)
        rec.reconcile(force=True)
        for path in files:
            path.unlink()

        result = rec.reconcile(force=True)
        assert result.marked_missing == []
        for path in files:
            row = db.get(str(path))
            assert row is not None
            assert row["missing_since"] is None
        assert db.tracks_page()[1] == 4
        db.close()

    def test_partial_vanished_files_still_marked_missing(self, tmp_path, monkeypatch):
        from tidal_dl.helper import library_reconcile as rec_mod

        monkeypatch.setattr(rec_mod, "RECONCILE_REMOUNT_MIN_ROWS", 2)
        root = tmp_path / "Music"
        files = [
            _write_wav(root / "A" / f"{i}.wav", frames=2000)
            for i in range(4)
        ]
        db = _open_db(tmp_path)
        metadata = {}
        for path in files:
            metadata[str(path)] = _metadata_for(path, name=path.stem, artist="A", album="LP", duration=1)
            _seed(db, path, artist="A", title=path.stem, album="LP", duration=1)
        rec = _reconciler(db, [root], metadata=metadata)
        rec.reconcile(force=True)
        files[0].unlink()

        result = rec.reconcile(force=True)
        assert result.marked_missing == [str(files[0])]
        assert db.get(str(files[0]))["missing_since"] is not None
        for path in files[1:]:
            assert db.get(str(path))["missing_since"] is None
        assert db.tracks_page()[1] == 3
        db.close()

    def test_should_skip_mass_missing_thresholds(self):
        from tidal_dl.helper.library_reconcile import should_skip_mass_missing

        assert should_skip_mass_missing(100, 100) is False
        assert should_skip_mass_missing(101, 50) is False
        assert should_skip_mass_missing(101, 51) is True

    def test_reconcile_and_scan_do_not_delete_vanished_in_root_rows(self):
        rec = Path(__file__).resolve().parents[1] / "tidal_dl" / "helper" / "library_reconcile.py"
        scan = Path(__file__).resolve().parents[1] / "tidal_dl" / "gui" / "api" / "library.py"
        rec_src = rec.read_text()
        scan_src = scan.read_text()
        assert "db.remove(" not in rec_src
        assert "DELETE FROM scanned" not in rec_src
        assert "check_missing" not in rec_src
        assert "check_missing" not in scan_src
        assert "db.mark_missing" in rec_src
        assert "db.mark_missing" in scan_src

    def test_scan_clears_missing_when_file_returns(self, tmp_path, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        root = tmp_path / "Music"
        path = root / "A" / "song.wav"
        _write_wav(path, frames=4000)
        db = _open_db(tmp_path)
        _seed(db, path, artist="A", title="Song", album="LP", duration=1)
        rec = _reconciler(db, [root], metadata={
            str(path): _metadata_for(path, name="Song", artist="A", album="LP", duration=1),
        })
        rec.reconcile(force=True)
        path.unlink()
        rec.reconcile(force=True)
        assert db.get(str(path))["missing_since"] is not None
        _write_wav(path, frames=4000)

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(root), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
        monkeypatch.setattr(library_api, "_album_cards", lambda db, *args, **kwargs: [])
        monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)
        monkeypatch.setattr(library_api, "_has_local_art", lambda path: False)
        monkeypatch.setattr(
            library_api,
            "_read_metadata",
            lambda file_path, scan_dirs=None: {
                "path": str(file_path),
                "name": "Song",
                "artist": "A",
                "album": "LP",
                "duration": 1,
                "isrc": "",
                "genre": None,
                "quality": "WAV",
                "format": "WAV",
                "codec": "pcm",
                "metadata_complete": True,
                "is_local": True,
            },
        )
        library_api._scan_running = True
        library_api._background_scan(False)
        db.close()
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        assert db.get(str(path))["missing_since"] is None
        assert db.tracks_page()[1] == 1
        db.close()

    def test_scan_migrate_populates_playback_cache(self, tmp_path, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        root = tmp_path / "Music"
        src = root / "A" / "song.wav"
        dest = root / "B" / "song.wav"
        _write_wav(src, frames=4000)
        db = _open_db(tmp_path)
        _seed(db, src, artist="A", title="Song", album="LP", duration=1)
        rec = _reconciler(db, [root], metadata={
            str(src): _metadata_for(src, name="Song", artist="A", album="LP", duration=1),
            str(dest): _metadata_for(dest, name="Song", artist="A", album="LP", duration=1),
        })
        rec.reconcile(force=True)
        dest.parent.mkdir(parents=True)
        src.rename(dest)

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(root), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
        monkeypatch.setattr(library_api, "_album_cards", lambda db, *args, **kwargs: [])
        monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)
        monkeypatch.setattr(library_api, "_has_local_art", lambda path: False)
        monkeypatch.setattr(
            library_api,
            "_read_metadata",
            lambda file_path, scan_dirs=None: {
                "path": str(file_path),
                "name": "Song",
                "artist": "A",
                "album": "LP",
                "duration": 1,
                "isrc": "",
                "genre": None,
                "quality": "WAV",
                "format": "WAV",
                "codec": "pcm",
                "metadata_complete": True,
                "is_local": True,
            },
        )
        library_api._playback_migration_cache.clear()
        library_api._scan_running = True
        library_api._background_scan(False)
        assert library_api.playback_resolved_path(str(src)) == str(dest)
        db.close()

    def test_reconcile_clears_missing_when_file_returns(self, tmp_path):
        root = tmp_path / "Music"
        path = root / "A" / "song.wav"
        _write_wav(path, frames=4000)
        db = _open_db(tmp_path)
        rec = _reconciler(db, [root], metadata={
            str(path): _metadata_for(path, name="Song", artist="A", album="LP", duration=1),
        })
        _seed(db, path, artist="A", title="Song", album="LP", duration=1)
        rec.reconcile(force=True)
        path.unlink()
        rec.reconcile(force=True)
        assert db.get(str(path))["missing_since"] is not None
        assert db.tracks_page()[1] == 0

        _write_wav(path, frames=4000)
        result = rec.reconcile(force=True)
        assert str(path) in result.cleared_missing
        assert db.get(str(path))["missing_since"] is None
        assert db.tracks_page()[1] == 1
        db.close()

    def test_unchanged_signatures_still_clear_restored_file(self, tmp_path):
        root = tmp_path / "Music"
        path = root / "A" / "song.wav"
        _write_wav(path, frames=4000)
        db = _open_db(tmp_path)
        rec = _reconciler(db, [root], metadata={
            str(path): _metadata_for(path, name="Song", artist="A", album="LP", duration=1),
        })
        _seed(db, path, artist="A", title="Song", album="LP", duration=1)
        rec.reconcile(force=True)
        path.unlink()
        rec.reconcile(force=True)
        assert db.get(str(path))["missing_since"] is not None
        assert db.tracks_page()[1] == 0

        _write_wav(path, frames=4000)
        current, _unreadable = rec.walk_dirs()
        db.replace_dir_signatures(
            {directory: info.signature for directory, info in current.items()},
            checked_at=1,
        )
        db.commit()

        result = rec.reconcile(force=True)
        assert str(path) in result.cleared_missing
        assert result.unchanged is False
        assert db.get(str(path))["missing_since"] is None
        assert db.tracks_page()[1] == 1
        db.close()


class TestUnicodePathIdentity:
    def test_nfc_row_and_nfd_walk_are_not_a_move(self, tmp_path):
        import unicodedata

        from tidal_dl.helper.library_reconcile import canon_path

        artist_nfc = "Alizée"
        artist_nfd = unicodedata.normalize("NFD", artist_nfc)
        album_nfc = "Mes Courants Électriques"
        album_nfd = unicodedata.normalize("NFD", album_nfc)
        root = tmp_path / "Music"
        nfc = root / artist_nfc / album_nfc / "01 J'en ai marre !.wav"
        nfd = root / artist_nfd / album_nfd / "01 J'en ai marre !.wav"
        _write_wav(nfc)
        nfd.parent.mkdir(parents=True, exist_ok=True)
        if nfc.resolve() != nfd.resolve():
            os.link(nfc, nfd)
        assert str(nfc) != str(nfd)
        assert canon_path(str(nfc)) == canon_path(str(nfd))

        db = _open_db(tmp_path)
        _seed(
            db, nfc, artist=artist_nfc, title="J'en ai marre !",
            album=album_nfc, duration=1, play_count=9,
        )
        rec = _reconciler(db, [root], metadata={
            str(nfc): _metadata_for(nfc, name="J'en ai marre !", artist=artist_nfc, album=album_nfc, duration=1),
            str(nfd): _metadata_for(nfd, name="J'en ai marre !", artist=artist_nfc, album=album_nfc, duration=1),
        })
        result = rec.reconcile(force=True)

        assert result.migrations == []
        assert db.tracks_page()[1] == 1
        assert db.get(str(nfc))["path"] == str(nfc)
        assert db.get(str(nfd))["path"] == str(nfc)
        assert db.get(str(nfc))["play_count"] == 9
        db.close()
