"""Queue one track through DownloadJobService.enqueue_download and wait."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from tidal_dl.playlist_sync.models import DownloadResult

_DONE = {"done", "completed"}
_FAILED = {"error", "failed", "cancelled"}


class DownloadClient(Protocol):
    def enqueue_download(self, track_ids: list[int]) -> dict:
        """Queue track ids. Playlist sync passes a one-item list."""

    def wait_for(self, track_id: int) -> DownloadResult:
        """Block until that track is completed or failed."""


def _http_from_error(error: object) -> int | None:
    text = str(error or "")
    if "429" in text:
        return 429
    if "401" in text:
        return 401
    return None


class JobServiceDownloader:
    """One-track adapter over an object that implements enqueue_download."""

    def __init__(
        self,
        service: Any,
        *,
        sleep: Callable[[float], None] | None = None,
        timeout_sec: float = 900.0,
    ) -> None:
        self._service = service
        self._sleep = sleep or time.sleep
        self._timeout = timeout_sec

    def enqueue_download(self, track_ids: list[int]) -> dict:
        if len(track_ids) != 1:
            raise ValueError("playlist sync queues one track at a time")
        return self._service.enqueue_download(list(track_ids))

    def wait_for(self, track_id: int) -> DownloadResult:
        poll = getattr(self._service, "poll_download", None)
        if callable(poll):
            result = poll(track_id)
            if isinstance(result, DownloadResult):
                return result
        return self._poll_jobs(track_id)

    def _poll_jobs(self, track_id: int) -> DownloadResult:
        status_for = getattr(self._service, "job_status_for_track", None)
        if not callable(status_for):
            return DownloadResult(status="failed", error="timeout")
        deadline = time.monotonic() + self._timeout
        while True:
            row = status_for(track_id)
            if isinstance(row, dict):
                status = str(row.get("status") or "")
                if status in _DONE:
                    path = row.get("new_path") or row.get("path")
                    return DownloadResult(status="completed", path=str(path) if path else None)
                if status in _FAILED:
                    return DownloadResult(
                        status="failed",
                        error=None if row.get("error") is None else str(row.get("error")),
                        http_status=_http_from_error(row.get("error")),
                    )
            if time.monotonic() >= deadline:
                return DownloadResult(status="failed", error="timeout")
            self._sleep(0.05)


def service_downloader() -> JobServiceDownloader:
    """Build a downloader that queues onto the process job service without starting it."""
    from tidal_dl.gui.services.download_job_service import DownloadJobService

    return JobServiceDownloader(DownloadJobService(autostart=False), timeout_sec=900)
