"""Queue one track through DownloadJobService.enqueue_download and wait."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, Protocol

from tidal_dl.playlist_sync.models import DownloadResult
from tidal_dl.playlist_sync.unicode_norm import filesystem_spellings

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


def existing_library_file(
    library: Any,
    track: Any,
    file_exists: Callable[[str], bool],
) -> str | None:
    """On-disk spelling of an ISRC library row whose file is still on disk."""
    if library is None or not getattr(track, "isrc", None):
        return None
    for candidate in library(track) or []:
        raw = getattr(candidate, "path", None)
        if raw is None and isinstance(candidate, dict):
            raw = candidate.get("path")
        for spelling in filesystem_spellings(raw or ""):
            if spelling and file_exists(spelling):
                return spelling
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
        self._file_exists = os.path.exists
        self._lookup_track: Any = None
        self._library: Any = None

    def bind_lookup(self, track: Any, library: Any, file_exists: Callable[[str], bool]) -> None:
        """Remember the source row so a completed job can resolve its file."""
        self._lookup_track = track
        self._library = library
        self._file_exists = file_exists

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
                    return DownloadResult(status="completed", path=self._library_path())
                if status in _FAILED:
                    return DownloadResult(
                        status="failed",
                        error=None if row.get("error") is None else str(row.get("error")),
                        http_status=_http_from_error(row.get("error")),
                    )
            if time.monotonic() >= deadline:
                return DownloadResult(status="failed", error="timeout")
            self._sleep(0.05)

    def _library_path(self) -> str | None:
        """The indexed file for this ISRC. Job status does not carry a path."""
        return existing_library_file(self._library, self._lookup_track, self._file_exists)


def service_downloader() -> JobServiceDownloader:
    """Build a downloader that queues onto the process job service without starting it."""
    from tidal_dl.gui.services.download_job_service import DownloadJobService

    return JobServiceDownloader(DownloadJobService(autostart=False), timeout_sec=900)
