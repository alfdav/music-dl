"""Post-download indexing must not walk NAS trash or lie about job status."""

from __future__ import annotations

import os
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

from mutagen.flac import FLAC

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.library_scanner import is_skipped_scan_dir, path_has_skipped_scan_dir
from tidal_dl.model.downloader import DownloadOutcome


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\x00\x00" * 100)


def _settings(library_dir: Path):
    return SimpleNamespace(data=SimpleNamespace(download_base_path=str(library_dir)))


def _write_tagged_flac(path: Path, *, spaced_album_artist: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.05",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-sample_fmt",
            "s16",
            "-c:a",
            "flac",
            "-y",
            str(path),
        ],
        check=True,
    )
    audio = FLAC(path)
    audio["TITLE"] = "Harbor Light"
    audio["ARTIST"] = "Juniper Vale"
    audio["ALBUM"] = "Night Letters"
    audio["ISRC"] = "USESK0000269"
    if spaced_album_artist:
        audio["ALBUM ARTIST"] = "Nia Coltrane; Juniper Vale"
    else:
        audio["ALBUMARTIST"] = "Nia Coltrane; Juniper Vale"
    audio.save()
    return path


def _library_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    library_dir = tmp_path / "music"
    new_file = library_dir / "Horizon Chase" / "Soundtrack" / "01 Top Gear.wav"
    recycle = library_dir / "#recycle" / "Soundtrack" / "08 Menu Groove Edit.wav"
    trash = library_dir / ".Trash" / "deleted" / "old.wav"
    _write_wav(new_file)
    _write_wav(recycle)
    _write_wav(trash)
    return library_dir, new_file, recycle


def _track_directory_descent(monkeypatch) -> list[Path]:
    visited: list[Path] = []
    real_scandir = os.scandir

    def tracking_scandir(path):
        visited.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", tracking_scandir)
    return visited


def _descended_into_skipped(visited: list[Path]) -> bool:
    return any(
        is_skipped_scan_dir(path.name) or path_has_skipped_scan_dir(path / "dummy")
        for path in visited
    )


class TestScanNewDownloadsSkipsTrash:
    def test_indexes_new_file_without_descending_into_recycle(self, tmp_path, monkeypatch):
        from tidal_dl.gui.services.download_job_service import scan_new_downloads

        library_dir, new_file, recycle = _library_fixture(tmp_path)
        trash = library_dir / ".Trash" / "deleted" / "old.wav"
        visited = _track_directory_descent(monkeypatch)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        scan_new_downloads(db, _settings(library_dir), paths=[new_file])
        paths = db.known_paths()
        db.close()

        assert str(new_file) in paths
        assert str(recycle) not in paths
        assert str(trash) not in paths
        assert not _descended_into_skipped(visited)

    def test_fallback_walk_prunes_recycle_and_still_indexes_new_file(
        self, tmp_path, monkeypatch
    ):
        from tidal_dl.gui.services.download_job_service import scan_new_downloads

        library_dir, new_file, recycle = _library_fixture(tmp_path)
        trash = library_dir / ".Trash" / "deleted" / "old.wav"
        visited = _track_directory_descent(monkeypatch)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        scan_new_downloads(db, _settings(library_dir))
        paths = db.known_paths()
        db.close()

        assert str(new_file) in paths
        assert str(recycle) not in paths
        assert str(trash) not in paths
        assert not _descended_into_skipped(visited)


def _download_fakes(tmp_path: Path, output_path: Path, *, on_item=None):
    class FakeTrack:
        id = 123
        name = "Song"
        full_name = "Song"
        duration = 1
        artists = ()
        album = None

    class FakeSession:
        def track(self, track_id):
            assert track_id == 123
            return FakeTrack()

    class FakeTidal:
        session = FakeSession()

    class FakeSettings:
        data = SimpleNamespace(
            download_base_path=str(tmp_path / "music"),
            skip_existing=True,
            format_track="{track_title}",
            quality_audio="LOSSLESS",
        )

    class FakeDownload:
        def __init__(self, **kwargs):
            pass

        def item(self, **kwargs):
            if on_item is not None:
                on_item()
            return DownloadOutcome.DOWNLOADED, output_path

    return FakeSettings, FakeTidal, FakeDownload


class TestWorkerPostDownloadIndexing:
    def test_worker_indexes_output_file_skips_recycle_and_reaches_done(
        self, tmp_path, monkeypatch
    ):
        from tidal_dl.gui.services import download_job_service as job_mod
        from tidal_dl.gui.services.download_job_service import DownloadJobService

        library_dir, new_file, recycle = _library_fixture(tmp_path)
        trash = library_dir / ".Trash" / "deleted" / "old.wav"
        visited = _track_directory_descent(monkeypatch)
        service = DownloadJobService(db_path=tmp_path / "library.db", autostart=False)
        service.enqueue_download([123])
        scan_calls = []
        real_scan = job_mod.scan_new_downloads

        def tracking_scan(db, settings, paths=None):
            scan_calls.append(paths)
            return real_scan(db, settings, paths)

        fakes = _download_fakes(tmp_path, new_file)
        monkeypatch.setattr(job_mod, "Settings", fakes[0])
        monkeypatch.setattr(job_mod, "Tidal", fakes[1])
        monkeypatch.setattr(job_mod, "Download", fakes[2])
        monkeypatch.setattr(job_mod, "scan_new_downloads", tracking_scan)

        job = service.claim_next_for_test()
        service.execute_job_for_test(job)

        stored = service.get_job_for_test(job.id)
        history = service.history(limit=10)["downloads"]
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        db.close()

        assert scan_calls == [[new_file]]
        assert stored.status.value == "done"
        assert history[0]["status"] == "done"
        assert str(new_file) in paths
        assert str(recycle) not in paths
        assert str(trash) not in paths
        assert not _descended_into_skipped(visited)

    def test_worker_exposes_indexing_status_before_terminal_done(
        self, tmp_path, monkeypatch
    ):
        from tidal_dl.gui.services import download_job_service as job_mod
        from tidal_dl.gui.services.download_job_service import DownloadJobService

        _library_dir, new_file, _recycle = _library_fixture(tmp_path)
        service = DownloadJobService(db_path=tmp_path / "library.db", autostart=False)
        service.enqueue_download([123])
        events = []
        service.events.broadcast = events.append
        seen_during_index = {}
        real_scan = job_mod.scan_new_downloads

        def tracking_scan(*args, **kwargs):
            seen_during_index["job"] = service.get_job_for_test(job.id)
            seen_during_index["api"] = service.job_status_for_track(123)
            seen_during_index["snapshot"] = service.snapshot()
            seen_during_index["history"] = [
                row["status"] for row in service.history(limit=10)["downloads"]
            ]
            return real_scan(*args, **kwargs)

        fakes = _download_fakes(tmp_path, new_file)
        monkeypatch.setattr(job_mod, "Settings", fakes[0])
        monkeypatch.setattr(job_mod, "Tidal", fakes[1])
        monkeypatch.setattr(job_mod, "Download", fakes[2])
        monkeypatch.setattr(job_mod, "scan_new_downloads", tracking_scan)

        job = service.claim_next_for_test()
        service.execute_job_for_test(job)

        assert seen_during_index["job"].status.value == "indexing"
        assert seen_during_index["api"]["status"] == "indexing"
        assert seen_during_index["snapshot"]["active"]
        assert seen_during_index["snapshot"]["active"][0]["status"] == "indexing"
        assert "done" not in seen_during_index["history"]
        assert any(
            event.get("type") == "progress" and event.get("status") == "indexing"
            for event in events
        )
        stored = service.get_job_for_test(job.id)
        assert stored.status.value == "done"
        assert service.history(limit=10)["downloads"][0]["status"] == "done"

    def test_cancel_during_indexing_does_not_mark_done(self, tmp_path, monkeypatch):
        from tidal_dl.gui.services import download_job_service as job_mod
        from tidal_dl.gui.services.download_job_service import DownloadJobService

        _library_dir, new_file, _recycle = _library_fixture(tmp_path)
        service = DownloadJobService(db_path=tmp_path / "library.db", autostart=False)
        service.enqueue_download([123])
        events = []
        service.events.broadcast = events.append
        real_scan = job_mod.scan_new_downloads

        def cancel_during_scan(*args, **kwargs):
            service.cancel()
            return real_scan(*args, **kwargs)

        fakes = _download_fakes(tmp_path, new_file)
        monkeypatch.setattr(job_mod, "Settings", fakes[0])
        monkeypatch.setattr(job_mod, "Tidal", fakes[1])
        monkeypatch.setattr(job_mod, "Download", fakes[2])
        monkeypatch.setattr(job_mod, "scan_new_downloads", cancel_during_scan)

        job = service.claim_next_for_test()
        service.execute_job_for_test(job)

        stored = service.get_job_for_test(job.id)
        history = service.history(limit=10)["downloads"]
        assert stored.status.value == "cancelled"
        assert history == []
        assert any(event["type"] == "cancelled" for event in events)
        assert not any(event["type"] == "complete" for event in events)


class TestScanPersistsAlbumArtist:
    def test_scan_new_downloads_persists_album_artist_from_tags(self, tmp_path):
        from tidal_dl.gui.services.download_job_service import scan_new_downloads

        library_dir = tmp_path / "music"
        tagged = _write_tagged_flac(
            library_dir / "Nia Coltrane" / "Night Letters" / "04 Harbor Light.flac",
            spaced_album_artist=True,
        )
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        scan_new_downloads(db, _settings(library_dir), paths=[tagged])
        row = db.get(str(tagged))
        db.close()

        assert row is not None
        assert row["artist"] == "Juniper Vale"
        assert row["album"] == "Night Letters"
        assert row["album_artist"]
        assert "Nia Coltrane" in row["album_artist"]

    def test_register_downloaded_track_persists_album_artist_from_tags(self, tmp_path, monkeypatch):
        from tidal_dl.download import registry as registry_mod

        monkeypatch.setattr(registry_mod, "path_config_base", lambda: str(tmp_path / "config"))
        tagged = _write_tagged_flac(
            tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "04 Harbor Light.flac",
            spaced_album_artist=True,
        )
        registry_mod.register_downloaded_track(tagged)

        db = LibraryDB(tmp_path / "config" / "library.db")
        db.open()
        row = db.get(str(tagged))
        db.close()

        assert row is not None
        assert row["album_artist"]
        assert "Nia Coltrane" in row["album_artist"]
