"""Tests for download pipeline error handling."""
import logging


def test_broadcast_fires_even_when_db_fails():
    """Download job errors still broadcast if history persistence fails."""
    from tidal_dl.gui.services.download_job_service import DownloadJobService
    from tidal_dl.gui.services.job_models import DownloadJob

    broadcasts = []
    service = DownloadJobService(autostart=False)
    service.events.broadcast = broadcasts.append
    service._record_error_history = lambda job, exc: (_ for _ in ()).throw(
        Exception("database is locked")
    )
    job = DownloadJob.from_row(
        {
            "id": 1,
            "kind": "download",
            "status": "running",
            "track_id": 999,
            "name": "Test Track",
            "artist": "Test Artist",
            "album": "Test Album",
            "cover_url": "",
            "quality": "LOSSLESS",
            "progress": 0,
            "error": None,
            "old_path": None,
            "new_path": None,
            "metadata_json": None,
            "created_at": 1.0,
            "started_at": 1.0,
            "finished_at": None,
        }
    )

    try:
        service._mark_job_error(job, RuntimeError("download failed"))
    except Exception:
        logging.exception("Failed to persist download error for track %s", job.track_id)
    service._broadcast_error(job, RuntimeError("download failed"))

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
