"""Incremental library path reconciler — identity-preserving folder moves."""

from __future__ import annotations

import os
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
    def test_playback_of_missing_path_reconciles_and_retries(self, tmp_path, monkeypatch):
        import re

        from fastapi.testclient import TestClient

        import tidal_dl.gui.api.library as library_api
        import tidal_dl.gui.api.playback as playback_api
        from tidal_dl.gui import create_app

        root = tmp_path / "Music"
        src = root / "A" / "song.wav"
        dest = root / "B" / "song.wav"
        _write_wav(src, frames=8000)

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(root), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(library_api, "request_path_reconcile", lambda **_kw: {"status": "debounced"})
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

        with TestClient(create_app(port=8765, job_db_path=tmp_path / "jobs.db")) as client:
            index = client.get("/", headers={"host": "localhost:8765"})
            match = re.search(r'name="csrf-token" content="([^"]+)"', index.text)
            headers = {"host": "localhost:8765"}
            if match:
                headers["X-CSRF-Token"] = match.group(1)
            resp = client.get(
                "/api/playback/local",
                params={"path": str(src)},
                headers=headers,
            )
        assert resp.status_code == 200


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
