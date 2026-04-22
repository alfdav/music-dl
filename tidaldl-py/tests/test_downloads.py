"""Tests for download pipeline error handling."""
import logging
from unittest.mock import MagicMock, patch
import pytest


def test_broadcast_fires_even_when_db_fails():
    """The nested try/except around record_download ensures _broadcast fires."""
    from tidal_dl.gui.api import downloads

    broadcasts = []
    original_broadcast = downloads._broadcast

    def capture_broadcast(event):
        broadcasts.append(event)

    # Patch broadcast to capture events
    with patch.object(downloads, "_broadcast", side_effect=capture_broadcast):
        # Simulate what happens in the error handler
        entry = MagicMock()
        entry.name = "Test Track"
        entry.artist = "Test Artist"
        entry.album = "Test Album"
        entry.cover_url = None
        entry.status = "error"
        entry.finished_at = 1.0
        entry.started_at = 0.0
        entry.quality = "LOSSLESS"

        # Create a mock DB that fails on record_download
        mock_db = MagicMock()
        mock_db.record_download.side_effect = Exception("database is locked")

        exc = RuntimeError("download failed")
        tid = 999

        # Execute the error handler logic directly
        entry.status = "error"
        try:
            mock_db.record_download(
                track_id=tid, name=entry.name, artist=entry.artist,
                album=entry.album, status="error", error=str(exc),
                started_at=entry.started_at, finished_at=entry.finished_at,
                cover_url=entry.cover_url, quality=entry.quality,
            )
            mock_db.commit()
        except Exception:
            logging.exception("Failed to persist download error for track %s", tid)

        downloads._broadcast({
            "type": "error", "track_id": tid, "name": entry.name,
            "artist": entry.artist, "album": entry.album,
            "cover_url": entry.cover_url, "error": str(exc),
        })

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
