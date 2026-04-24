from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from tidal_dl.gui.services.job_events import JobEventHub
from tidal_dl.gui.services.job_models import DownloadJob, JobKind
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base


class DownloadJobService:
    def __init__(self, db_path: Path | None = None, *, autostart: bool = True) -> None:
        self._db_path = db_path or Path(path_config_base()) / "library.db"
        self.events = JobEventHub()
        self._running = threading.Event()
        self._running.set()
        self._stop = threading.Event()
        self._cancel_all = False
        self._cancelled_ids: set[int] = set()
        self._worker_started = False
        self._worker_thread: threading.Thread | None = None
        if autostart:
            self.recover_on_startup()
            self.start_worker()

    def _open_db(self) -> LibraryDB:
        db = LibraryDB(self._db_path)
        db.open()
        return db

    def recover_on_startup(self) -> int:
        db = self._open_db()
        try:
            return db.recover_download_jobs()
        finally:
            db.close()

    def start_worker(self) -> None:
        if self._worker_started:
            return
        self._worker_started = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def stop_worker(self, join_timeout: float = 2.0) -> None:
        self._stop.set()
        self._running.set()
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=join_timeout)

    def enqueue_download(self, track_ids: list[int]) -> dict:
        queued = 0
        for track_id in dict.fromkeys(track_ids):
            db = self._open_db()
            try:
                job_id = db.create_download_job_if_not_active(
                    kind=JobKind.DOWNLOAD.value,
                    track_id=track_id,
                    name=f"Track {track_id}",
                )
                if job_id is not None:
                    queued += 1
            finally:
                db.close()

        if queued == 0:
            return {"status": "already_queued", "count": 0}

        self.events.broadcast({"type": "batch_queued", "count": queued})
        return {"status": "queued", "count": queued}

    def pause(self) -> dict:
        self._running.clear()
        self.events.broadcast({"type": "queue_paused"})
        return {"status": "paused"}

    def resume(self) -> dict:
        self._running.set()
        self.events.broadcast({"type": "queue_resumed"})
        return {"status": "running"}

    def cancel(self, track_ids: list[int] | None = None) -> dict:
        db = self._open_db()
        try:
            if track_ids:
                count = db.cancel_queued_download_jobs(track_ids)
            else:
                self._cancel_all = True
                count = db.cancel_all_queued_download_jobs()
        finally:
            db.close()

        if track_ids:
            self._cancelled_ids.update(track_ids)
            for track_id in track_ids:
                self.events.broadcast(
                    {
                        "type": "cancelled",
                        "track_id": track_id,
                        "name": f"Track {track_id}",
                    }
                )
            return {"status": "cancelled", "count": count}

        self.events.broadcast({"type": "queue_cancelled", "count": count})
        self._running.set()
        return {"status": "cancelled", "count": count}

    def queue_state(self) -> dict:
        db = self._open_db()
        try:
            active_count = db.active_download_job_count()
        finally:
            db.close()
        return {
            "paused": not self._running.is_set(),
            "cancelled": self._cancel_all,
            "active_count": active_count,
        }

    def snapshot(self) -> dict:
        db = self._open_db()
        try:
            return db.download_jobs_snapshot()
        finally:
            db.close()

    def initial_events(self) -> list[dict]:
        snapshot = self.snapshot()
        events = []
        for row in snapshot["active"]:
            job = DownloadJob.from_row(row)
            events.append(
                {
                    "type": "progress",
                    "track_id": job.track_id,
                    "name": job.name,
                    "artist": job.artist,
                    "album": job.album,
                    "cover_url": job.cover_url,
                    "quality": job.quality,
                    "status": job.status.value,
                    "progress": job.progress,
                    "job_id": job.id,
                    "kind": job.kind.value,
                }
            )
        queued_count = snapshot["queued_count"]
        if queued_count > 0:
            events.append({"type": "batch_queued", "count": queued_count})
        return events

    def claim_next_for_test(self) -> DownloadJob | None:
        db = self._open_db()
        try:
            row = db.claim_next_download_job()
            return DownloadJob.from_row(row) if row else None
        finally:
            db.close()

    def is_cancelled_for_test(self, track_id: int) -> bool:
        return track_id in self._cancelled_ids

    def _is_cancel_requested(self, job: DownloadJob) -> bool:
        return self._cancel_all or job.track_id in self._cancelled_ids

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.25)
