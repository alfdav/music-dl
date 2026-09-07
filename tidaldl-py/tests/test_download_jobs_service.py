import asyncio
import logging
from pathlib import Path

import pytest

from tidal_dl.model.downloader import DownloadOutcome


def _service(tmp_path):
    from tidal_dl.gui.services.download_job_service import DownloadJobService

    return DownloadJobService(db_path=Path(tmp_path) / "library.db", autostart=False)


def test_job_models_normalize_db_row():
    from tidal_dl.gui.services.job_models import DownloadJob, JobKind, JobStatus

    job = DownloadJob.from_row(
        {
            "id": 1,
            "kind": "download",
            "status": "queued",
            "track_id": 123,
            "name": "Track",
            "artist": None,
            "album": None,
            "cover_url": None,
            "quality": None,
            "progress": 0,
            "error": None,
            "old_path": None,
            "new_path": None,
            "metadata_json": None,
            "created_at": 1.0,
            "started_at": None,
            "finished_at": None,
        }
    )

    assert job.kind == JobKind.DOWNLOAD
    assert job.status == JobStatus.QUEUED
    assert job.track_id == 123


def test_event_hub_broadcasts_to_subscribers():
    from tidal_dl.gui.services.job_events import JobEventHub

    async def run():
        hub = JobEventHub(max_clients=2)
        queue = hub.subscribe()
        hub.set_event_loop(asyncio.get_running_loop())
        hub.broadcast({"type": "ping"})
        assert await asyncio.wait_for(queue.get(), timeout=1) == {"type": "ping"}
        hub.unsubscribe(queue)

    asyncio.run(run())


def test_event_hub_rejects_too_many_clients():
    from tidal_dl.gui.services.job_events import JobEventHub

    hub = JobEventHub(max_clients=1)
    first = hub.subscribe()
    try:
        try:
            hub.subscribe()
        except RuntimeError as exc:
            assert str(exc) == "too_many_clients"
        else:
            raise AssertionError("expected too_many_clients")
    finally:
        hub.unsubscribe(first)


def test_worker_preserves_quality_mismatch_reason(tmp_path, caplog):
    from tidal_dl.download.streams import QualityMismatchError
    from tidal_dl.gui.services.download_job_service import DownloadJobService

    reason = "Quality mismatch: requested HI_RES_LOSSLESS but received HIGH with codec aac."

    class LocalTrack:
        id = 118
        name = "Song"
        full_name = "Song"
        artists = ()
        album = None

    class LocalTidal:
        session = type("Session", (), {"track": lambda _self, _track_id: LocalTrack()})()

    class LocalSettings:
        data = type(
            "Data",
            (),
            {
                "download_base_path": str(tmp_path / "downloads"),
                "skip_existing": True,
                "format_track": "{track_title}",
                "quality_audio": "HI_RES_LOSSLESS",
            },
        )()

    class RaisingDownload:
        def __init__(self, **_kwargs):
            pass

        def item(self, **_kwargs):
            raise QualityMismatchError(reason)

    def dependencies():
        return LocalSettings, LocalTidal, RaisingDownload

    async def run_worker():
        service = DownloadJobService(
            db_path=tmp_path / "library.db",
            autostart=False,
            dependency_provider=dependencies,
        )
        queue = service.events.subscribe()
        service.events.set_event_loop(asyncio.get_running_loop())
        try:
            assert service.enqueue_download([118]) == {"status": "queued", "count": 1}
            service.start_worker()
            events = [await asyncio.wait_for(queue.get(), timeout=1) for _ in range(3)]
        finally:
            service.stop_worker()
            service.events.unsubscribe(queue)

        event = events[-1]
        history = service.history(limit=10)["downloads"]
        status = service.job_status_for_track(118)
        assert event["type"] == "error"
        assert event["error"] == reason
        assert status == {
            "job_id": "118",
            "status": "error",
            "progress": 0.0,
            "title": "Song",
            "artist": "",
            "started_at": status["started_at"],
            "finished_at": status["finished_at"],
            "error": reason,
        }
        assert history[0]["status"] == "error"
        assert history[0]["error"] == reason
        assert not any(item["type"] == "complete" for item in events)

    asyncio.run(run_worker())

    matching_records = [
        record
        for record in caplog.records
        if record.name == "music-dl.gui" and record.levelno == logging.ERROR and record.getMessage() == reason
    ]
    assert len(matching_records) == 1


def test_service_enqueue_suppresses_duplicate_active_jobs(tmp_path):
    service = _service(tmp_path)

    result = service.enqueue_download([10, 10])
    duplicate = service.enqueue_download([10])

    assert result == {"status": "queued", "count": 1}
    assert duplicate == {"status": "already_queued", "count": 0}
    assert service.queue_state()["active_count"] == 1


def test_service_startup_recovery_keeps_queued_and_interrupts_running(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1, 2])
    claimed = service.claim_next_for_test()
    assert claimed is not None

    recovered = service.recover_on_startup()

    assert recovered == 1
    snapshot = service.snapshot()
    assert snapshot["queued_count"] == 1


def test_service_pause_resume_and_cancel_queued(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1, 2])

    assert service.pause() == {"status": "paused"}
    assert service.queue_state()["paused"] is True
    assert service.resume() == {"status": "running"}

    result = service.cancel([1])
    assert result == {"status": "cancelled", "count": 1, "active_count": 1}


def test_service_cancel_all_while_paused_clears_queued_jobs(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1])
    service.pause()

    result = service.cancel()

    assert result == {"status": "cancelled", "count": 1, "active_count": 0}
    assert service.queue_state() == {
        "paused": False,
        "cancelled": True,
        "active_count": 0,
    }
    assert service.snapshot() == {
        "active": [],
        "queued_count": 0,
        "active_count": 0,
        "paused": False,
    }


def test_service_cancel_all_clears_claimed_jobs_from_snapshot(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1])
    assert service.claim_next_for_test() is not None

    result = service.cancel()

    assert result["active_count"] == 0
    assert service.snapshot()["queued_count"] == 0
    assert service.snapshot()["active"] == []
    assert service.queue_state()["active_count"] == 0


def test_service_cancels_claimed_job_at_safe_checkpoint(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1])
    job = service.claim_next_for_test()

    result = service.cancel([1])

    assert result == {"status": "cancelled", "count": 0, "active_count": 1}
    assert service.is_cancelled_for_test(job.track_id) is True


def test_service_initial_events_include_running_jobs_and_queue_summary(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1, 2])
    running = service.claim_next_for_test()
    assert running is not None

    events = service.initial_events()

    assert events == [
        {
            "type": "progress",
            "track_id": 1,
            "name": "Track 1",
            "artist": "",
            "album": "",
            "cover_url": "",
            "quality": "",
            "status": "running",
            "progress": 0.0,
            "job_id": running.id,
            "kind": "download",
        },
        {
            "type": "batch_queued",
            "count": 1,
            "queued_count": 1,
            "active_count": 2,
            "paused": False,
        },
    ]


def test_enqueue_batch_queued_reports_remaining_queue(tmp_path):
    service = _service(tmp_path)
    events = []
    service.events.broadcast = events.append

    service.enqueue_download([1])
    service.claim_next_for_test()
    service.enqueue_download([2, 3])

    batch = [event for event in events if event["type"] == "batch_queued"]
    assert batch[-1]["count"] == 2
    assert batch[-1]["queued_count"] == 2
    assert batch[-1]["active_count"] == 3


@pytest.mark.parametrize(
    "download_outcome",
    [DownloadOutcome.DOWNLOADED, DownloadOutcome.COPIED, DownloadOutcome.SKIPPED],
)
def test_worker_executes_download_job_and_records_history(
    tmp_path, monkeypatch, download_outcome
):
    service = _service(tmp_path)
    service.enqueue_download([123])

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

    class FakeSettingsData:
        download_base_path = str(tmp_path)
        skip_existing = True
        format_track = "{track_title}"
        quality_audio = "LOSSLESS"

    class FakeSettings:
        data = FakeSettingsData()

    class FakeDownload:
        def __init__(self, **kwargs):
            pass

        def item(self, **kwargs):
            return download_outcome, tmp_path / "Song.flac"

    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.scan_new_downloads", lambda *args: None)

    job = service.claim_next_for_test()
    service.execute_job_for_test(job)

    history = service.history(limit=10)["downloads"]
    assert history[0]["track_id"] == 123
    assert history[0]["status"] == "done"


def test_worker_failed_outcome_records_error_without_complete(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.enqueue_download([123])

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

    download_path = tmp_path / "downloads"

    class FakeSettingsData:
        download_base_path = str(download_path)
        skip_existing = True
        format_track = "{track_title}"
        quality_audio = "LOSSLESS"

    class FakeSettings:
        data = FakeSettingsData()

    class FakeDownload:
        def __init__(self, **kwargs):
            pass

        def item(self, **kwargs):
            return DownloadOutcome.FAILED, ""

    events = []
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)
    service.events.broadcast = events.append

    job = service.claim_next_for_test()
    service.execute_job_for_test(job)

    stored = service.get_job_for_test(job.id)
    history = service.history(limit=10)["downloads"]
    assert stored.status.value == "error"
    assert [entry["status"] for entry in history].count("error") == 1
    assert not any(entry["status"] == "done" for entry in history)
    assert any(event["type"] == "error" for event in events)
    assert not any(event["type"] == "complete" for event in events)
    assert not download_path.exists()


def test_worker_terminalizes_cancelled_claimed_job_without_success_history(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.enqueue_download([123])
    job = service.claim_next_for_test()
    service.cancel([123])
    events = []
    service.events.broadcast = events.append

    class FakeSettingsData:
        download_base_path = str(tmp_path)
        skip_existing = True
        format_track = "{track_title}"
        quality_audio = "LOSSLESS"

    class FakeSettings:
        data = FakeSettingsData()

    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)

    service.execute_job_for_test(job)

    stored = service.get_job_for_test(job.id)
    history = service.history(limit=10)["downloads"]
    assert stored.status.value == "cancelled"
    assert history == []
    assert any(event["type"] == "cancelled" for event in events)
    assert not any(event["type"] == "complete" for event in events)


def test_service_enqueue_upgrade_uses_shared_active_suppression(tmp_path):
    from tidal_dl.gui.services.job_models import UpgradeJobInput

    service = _service(tmp_path)
    service.enqueue_download([123])

    result = service.enqueue_upgrade(
        [
            UpgradeJobInput(
                track_id=123,
                old_path="/music/old.flac",
                quality="HI_RES_LOSSLESS",
            ),
            UpgradeJobInput(
                track_id=456,
                old_path="/music/other.flac",
                quality="HI_RES_LOSSLESS",
            ),
        ]
    )

    assert result == {"status": "queued", "count": 1, "skipped": 1}


def test_worker_executes_upgrade_job_and_marks_new_path(tmp_path, monkeypatch):
    from tidal_dl.gui.services.job_models import UpgradeJobInput
    from tidal_dl.helper.library_db import LibraryDB

    old_path = tmp_path / "old.flac"
    old_path.write_bytes(b"old audio")
    new_path = tmp_path / "new.flac"
    new_path.write_bytes(b"new audio")

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    db.record(
        str(old_path),
        status="tagged",
        isrc="US-TST-00-00001",
        artist="Test Artist",
        title="Song",
        album="Album",
        quality="44100Hz/16bit",
        fmt="FLAC",
    )
    db.set_probe("US-TST-00-00001", 999, "LOSSLESS")
    db.commit()
    db.close()

    service = _service(tmp_path)
    service.enqueue_upgrade(
        [
            UpgradeJobInput(
                track_id=123,
                old_path=str(old_path),
                quality="HI_RES_LOSSLESS",
            )
        ]
    )

    class FakeArtist:
        name = "Test Artist"

    class FakeAlbum:
        name = "Album"

        def image(self, size):
            return f"https://img.example.com/{size}.jpg"

    class FakeTrack:
        id = 123
        name = "Song"
        full_name = "Song"
        artists = (FakeArtist(),)
        album = FakeAlbum()

    class FakeSession:
        def track(self, track_id):
            assert track_id == 123
            return FakeTrack()

    class FakeTidal:
        session = FakeSession()

    class FakeSettingsData:
        download_base_path = str(tmp_path)
        skip_existing = True
        format_track = "{track_title}"
        quality_audio = "LOSSLESS"
        upgrade_target_quality = "HI_RES_LOSSLESS"

    class FakeSettings:
        data = FakeSettingsData()

    class FakeDownload:
        def __init__(self, **kwargs):
            pass

        def item(self, **kwargs):
            assert kwargs["duplicate_action_override"] == "redownload"
            return "downloaded", new_path

    class FakeDownloadOutcome:
        DOWNLOADED = "downloaded"
        COPIED = "copied"

    events = []
    registered = []
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)
    monkeypatch.setattr(
        "tidal_dl.gui.services.download_job_service.DownloadOutcome",
        FakeDownloadOutcome,
        raising=False,
    )
    monkeypatch.setattr(
        "tidal_dl.gui.services.download_job_service.register_downloaded_track",
        registered.append,
        raising=False,
    )
    monkeypatch.setattr(
        "tidal_dl.gui.services.download_job_service.cleanup_replaced_track_files",
        lambda *args, **kwargs: [str(old_path)],
        raising=False,
    )
    service.events.broadcast = events.append

    job = service.claim_next_for_test()
    service.execute_job_for_test(job)

    stored = service.get_job_for_test(job.id)
    complete_events = [event for event in events if event["type"] == "upgrade_complete"]

    assert stored.status.value == "done"
    assert stored.new_path == str(new_path)
    assert registered == [new_path]
    assert complete_events
    assert complete_events[0]["old_path"] == str(old_path)
    assert complete_events[0]["new_path"] == str(new_path)
    assert complete_events[0]["removed_paths"] == [str(old_path)]

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    try:
        assert db.get_probe("US-TST-00-00001") is None
    finally:
        db.close()


def test_worker_upgrade_renames_replacement_to_original_path_after_cleanup(tmp_path, monkeypatch):
    from tidal_dl.gui.services.job_models import UpgradeJobInput
    from tidal_dl.helper.library_db import LibraryDB

    album_dir = tmp_path / "Artist" / "Album"
    album_dir.mkdir(parents=True)
    old_path = album_dir / "Song.flac"
    duplicate_path = album_dir / "Song 2.flac"
    replacement_path = album_dir / "Song_01.flac"
    for path, content in (
        (old_path, b"old"),
        (duplicate_path, b"duplicate"),
        (replacement_path, b"replacement"),
    ):
        path.write_bytes(content)

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    for path in (old_path, duplicate_path, replacement_path):
        db.record(
            str(path),
            status="tagged",
            isrc="US-TST-00-00002",
            artist="Test Artist",
            title="Song",
            album="Album",
            quality="96000Hz/24bit" if path == replacement_path else "44100Hz/16bit",
            duration=193 if path == replacement_path else 181,
            fmt="FLAC",
        )
    db.commit()
    db.close()

    service = _service(tmp_path)
    service.enqueue_upgrade(
        [
            UpgradeJobInput(
                track_id=123,
                old_path=str(old_path),
                quality="HI_RES_LOSSLESS",
            )
        ]
    )

    class FakeArtist:
        name = "Test Artist"

    class FakeAlbum:
        name = "Album"

        def image(self, size):
            return f"https://img.example.com/{size}.jpg"

    class FakeTrack:
        id = 123
        name = "Song"
        full_name = "Song"
        artists = (FakeArtist(),)
        album = FakeAlbum()

    class FakeSession:
        def track(self, track_id):
            assert track_id == 123
            return FakeTrack()

    class FakeTidal:
        session = FakeSession()

    class FakeSettingsData:
        download_base_path = str(tmp_path)
        skip_existing = True
        format_track = "{track_title}"
        quality_audio = "LOSSLESS"
        upgrade_target_quality = "HI_RES_LOSSLESS"

    class FakeSettings:
        data = FakeSettingsData()

    class FakeDownload:
        def __init__(self, **kwargs):
            pass

        def item(self, **kwargs):
            assert kwargs["duplicate_action_override"] == "redownload"
            return "downloaded", replacement_path

    class FakeDownloadOutcome:
        DOWNLOADED = "downloaded"
        COPIED = "copied"

    events = []
    registered = []
    trashed = []

    def fake_trash(path: str) -> None:
        trashed.append(path)
        Path(path).unlink(missing_ok=True)

    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)
    monkeypatch.setattr(
        "tidal_dl.gui.services.download_job_service.DownloadOutcome",
        FakeDownloadOutcome,
        raising=False,
    )
    monkeypatch.setattr(
        "tidal_dl.gui.services.download_job_service.register_downloaded_track",
        registered.append,
        raising=False,
    )
    monkeypatch.setattr("tidal_dl.gui.services.upgrade_jobs.trash_file", fake_trash)
    service.events.broadcast = events.append

    job = service.claim_next_for_test()
    service.execute_job_for_test(job)

    complete_events = [event for event in events if event["type"] == "upgrade_complete"]
    stored = service.get_job_for_test(job.id)

    assert old_path.exists()
    assert not replacement_path.exists()
    assert not duplicate_path.exists()
    assert registered == [old_path]
    assert complete_events
    assert complete_events[0]["old_path"] == str(old_path)
    assert complete_events[0]["new_path"] == str(old_path)
    assert set(complete_events[0]["removed_paths"]) == {str(old_path), str(duplicate_path)}
    assert set(trashed) == {str(old_path), str(duplicate_path)}
    assert stored.status.value == "done"
    assert stored.new_path == str(old_path)

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    try:
        row = db.get(str(old_path))
        assert row is not None
        assert row["artist"] == "Test Artist"
        assert row["title"] == "Song"
        assert row["album"] == "Album"
        assert row["quality"] == "96000Hz/24bit"
        assert int(row["duration"] or 0) == 193
        assert db.has_live_isrc("US-TST-00-00002")
    finally:
        db.close()


def test_claim_progress_event_includes_remaining_queue_counts(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.enqueue_download([1, 2])
    events = []
    service.events.broadcast = events.append

    class FakeTrack:
        id = 1
        name = "Song"
        full_name = "Song"
        duration = 1
        artists = ()
        album = None

    class FakeSession:
        def track(self, track_id):
            return FakeTrack()

    class FakeTidal:
        session = FakeSession()

    class FakeSettingsData:
        download_base_path = str(tmp_path)
        skip_existing = True
        format_track = "{track_title}"
        quality_audio = "LOSSLESS"

    class FakeSettings:
        data = FakeSettingsData()

    class FakeDownload:
        def __init__(self, **kwargs):
            pass

        def item(self, **kwargs):
            return DownloadOutcome.DOWNLOADED, tmp_path / "Song.flac"

    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.scan_new_downloads", lambda *args: None)

    job = service.claim_next_for_test()
    service.execute_job_for_test(job)

    progress = [event for event in events if event["type"] == "progress"]
    assert progress
    assert progress[0]["queued_count"] == 1
    assert progress[0]["active_count"] == 2
    assert progress[0]["paused"] is False


def test_update_job_does_not_resurrect_cancelled_status(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1])
    job = service.claim_next_for_test()

    service.cancel()
    service._update_job(job, status="running", name="Song")

    stored = service.get_job_for_test(job.id)
    assert stored.status.value == "cancelled"
    assert service.snapshot()["active"] == []
    assert service.snapshot()["queued_count"] == 0


def test_mark_retrying_after_cancel_all_does_not_broadcast_progress(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1])
    job = service.claim_next_for_test()
    service.cancel()
    events = []
    service.events.broadcast = events.append

    service._mark_retrying(job, 1, 3)

    stored = service.get_job_for_test(job.id)
    assert stored.status.value == "cancelled"
    assert service.snapshot()["active"] == []
    assert not any(event["type"] == "progress" for event in events)


def test_cancel_all_during_metadata_does_not_emit_downloading_progress(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.enqueue_download([123])
    job = service.claim_next_for_test()
    events = []
    service.events.broadcast = events.append

    class FakeTrack:
        id = 123
        name = "Song"
        full_name = "Song"
        duration = 1
        artists = ()
        album = None

    class FakeSession:
        def track(self, track_id):
            service.cancel()
            return FakeTrack()

    class FakeTidal:
        session = FakeSession()

    class FakeSettingsData:
        download_base_path = str(tmp_path)
        skip_existing = True
        format_track = "{track_title}"
        quality_audio = "LOSSLESS"

    class FakeSettings:
        data = FakeSettingsData()

    class FakeDownload:
        def __init__(self, **kwargs):
            raise AssertionError("download should not start after cancel-all")

    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)

    service.execute_job_for_test(job)

    stored = service.get_job_for_test(job.id)
    assert stored.status.value == "cancelled"
    assert service.snapshot()["active"] == []
    assert not any(event["type"] == "progress" for event in events)
    assert any(event["type"] == "cancelled" for event in events)


def test_cancel_all_during_retryable_failure_does_not_mark_retrying(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.enqueue_download([123])
    job = service.claim_next_for_test()
    events = []
    service.events.broadcast = events.append

    class FakeTrack:
        id = 123
        name = "Song"
        full_name = "Song"
        duration = 1
        artists = ()
        album = None

    class FakeSession:
        def track(self, track_id):
            return FakeTrack()

    class FakeTidal:
        session = FakeSession()

    class FakeSettingsData:
        download_base_path = str(tmp_path)
        skip_existing = True
        format_track = "{track_title}"
        quality_audio = "LOSSLESS"

    class FakeSettings:
        data = FakeSettingsData()

    class FakeDownload:
        def __init__(self, **kwargs):
            pass

        def item(self, **kwargs):
            service.cancel()
            raise ConnectionError("network dropped")

    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.time.sleep", lambda *_args: None)

    service.execute_job_for_test(job)

    stored = service.get_job_for_test(job.id)
    assert stored.status.value == "cancelled"
    assert service.snapshot()["active"] == []
    assert not any(event.get("status") == "retrying" for event in events)
    assert not any(
        event["type"] == "progress" and event.get("status") == "retrying" for event in events
    )


def test_mark_retrying_cancels_when_update_job_refuses_active_status(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1])
    job = service.claim_next_for_test()
    service.cancel()
    service._cancel_all = False
    events = []
    service.events.broadcast = events.append

    scheduled = service._mark_retrying(job, 1, 3)

    stored = service.get_job_for_test(job.id)
    assert scheduled is False
    assert stored.status.value == "cancelled"
    assert any(event["type"] == "cancelled" for event in events)
    assert not any(event["type"] == "progress" for event in events)


def test_refused_retry_update_finishes_cancel_without_backoff(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.enqueue_download([123])
    job = service.claim_next_for_test()
    events = []
    item_calls = []
    slept = []
    service.events.broadcast = events.append

    class FakeTrack:
        id = 123
        name = "Song"
        full_name = "Song"
        duration = 1
        artists = ()
        album = None

    class FakeSession:
        def track(self, track_id):
            return FakeTrack()

    class FakeTidal:
        session = FakeSession()

    class FakeSettingsData:
        download_base_path = str(tmp_path)
        skip_existing = True
        format_track = "{track_title}"
        quality_audio = "LOSSLESS"

    class FakeSettings:
        data = FakeSettingsData()

    class FakeDownload:
        def __init__(self, **kwargs):
            pass

        def item(self, **kwargs):
            item_calls.append(1)
            raise ConnectionError("network dropped")

    original_update = service._update_job

    def refuse_retrying(job_to_update, **fields):
        if fields.get("status") == "retrying":
            return False
        return original_update(job_to_update, **fields)

    service._update_job = refuse_retrying
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)
    monkeypatch.setattr(
        "tidal_dl.gui.services.download_job_service.time.sleep",
        lambda seconds: slept.append(seconds),
    )

    service.execute_job_for_test(job)

    stored = service.get_job_for_test(job.id)
    assert stored.status.value == "cancelled"
    assert item_calls == [1]
    assert slept == []
    assert any(event["type"] == "cancelled" for event in events)
    assert not any(event.get("status") == "retrying" for event in events)
