import asyncio
from pathlib import Path


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
    assert result == {"status": "cancelled", "count": 1}


def test_service_cancels_claimed_job_at_safe_checkpoint(tmp_path):
    service = _service(tmp_path)
    service.enqueue_download([1])
    job = service.claim_next_for_test()

    result = service.cancel([1])

    assert result == {"status": "cancelled", "count": 0}
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
        {"type": "batch_queued", "count": 1},
    ]


def test_worker_executes_download_job_and_records_history(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.enqueue_download([123])

    class FakeTrack:
        id = 123
        name = "Song"
        full_name = "Song"
        duration = 1
        artists = []
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
            return None

    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.scan_new_downloads", lambda *args: None)

    job = service.claim_next_for_test()
    service.execute_job_for_test(job)

    history = service.history(limit=10)["downloads"]
    assert history[0]["track_id"] == 123
    assert history[0]["status"] == "done"


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
