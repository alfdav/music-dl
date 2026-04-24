import asyncio


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
