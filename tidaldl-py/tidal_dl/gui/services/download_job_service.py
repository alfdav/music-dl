from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import requests

from tidal_dl.gui.services.job_events import JobEventHub
from tidal_dl.gui.services.job_models import DownloadJob, JobKind, JobStatus, UpgradeJobInput
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

logger = logging.getLogger("music-dl.gui")
Settings: Any = None
Tidal: Any = None
Download: Any = None


def _download_dependencies() -> tuple[Any, Any, Any]:
    global Settings, Tidal, Download
    if Settings is None or Tidal is None:
        from tidal_dl.config import Settings as _Settings, Tidal as _Tidal

        Settings = Settings or _Settings
        Tidal = Tidal or _Tidal
    if Download is None:
        from tidal_dl.download import Download as _Download

        Download = _Download
    return Settings, Tidal, Download


def scan_new_downloads(db, settings) -> None:
    from tidal_dl.gui.api.library import _AUDIO_EXTENSIONS, _read_metadata

    dl_path = Path(settings.data.download_base_path).expanduser()
    if not dl_path.is_dir():
        return

    known = db.known_paths()
    batch = 0
    for file_path in dl_path.rglob("*"):
        if file_path.suffix.lower() not in _AUDIO_EXTENSIONS:
            continue
        path_str = str(file_path)
        if path_str in known:
            continue
        meta = _read_metadata(file_path)
        if meta:
            db.record(
                path_str,
                status="tagged" if meta["isrc"] else "needs_isrc",
                isrc=meta["isrc"] or None,
                artist=meta["artist"],
                title=meta["name"],
                album=meta["album"],
                duration=meta["duration"],
                genre=meta.get("genre"),
                quality=meta["quality"],
                fmt=meta["format"],
            )
        else:
            db.record(path_str, status="unreadable")
        batch += 1
        if batch >= 50:
            db.commit()
            batch = 0

    if batch > 0:
        db.commit()

    import tidal_dl.gui.api.library as lib_mod

    lib_mod._invalidate_db_cache()


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

    def enqueue_upgrade(self, items: list[UpgradeJobInput]) -> dict:
        queued = 0
        skipped = 0
        for item in items:
            db = self._open_db()
            try:
                job_id = db.create_download_job_if_not_active(
                    kind=JobKind.UPGRADE.value,
                    track_id=item.track_id,
                    name=f"Track {item.track_id}",
                    quality=item.quality,
                    old_path=item.old_path,
                    metadata_json=json.dumps(item.metadata or {}),
                )
            finally:
                db.close()
            if job_id is None:
                skipped += 1
            else:
                queued += 1

        if queued > 0:
            self.events.broadcast({"type": "batch_queued", "count": queued})
        return {"status": "queued", "count": queued, "skipped": skipped}

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

    def execute_job_for_test(self, job: DownloadJob | None) -> None:
        if job is None:
            return
        self._execute_job(job)

    def get_job_for_test(self, job_id: int) -> DownloadJob | None:
        db = self._open_db()
        try:
            row = db.get_download_job(job_id)
            return DownloadJob.from_row(row) if row else None
        finally:
            db.close()

    def history(self, limit: int = 50) -> dict:
        db = self._open_db()
        try:
            return {"downloads": db.download_history(limit)}
        finally:
            db.close()

    def is_cancelled_for_test(self, track_id: int) -> bool:
        return track_id in self._cancelled_ids

    def _is_cancel_requested(self, job: DownloadJob) -> bool:
        return self._cancel_all or job.track_id in self._cancelled_ids

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            self._running.wait(timeout=0.25)
            if self._stop.is_set():
                break
            if not self._running.is_set():
                continue
            if self._cancel_all:
                self._cancel_all = False

            db = self._open_db()
            try:
                row = db.claim_next_download_job(kind=JobKind.DOWNLOAD.value)
            finally:
                db.close()
            if row is None:
                time.sleep(0.25)
                continue

            job = DownloadJob.from_row(row)
            try:
                self._execute_job(job)
            except Exception as exc:
                current = self.get_job_for_test(job.id) or job
                self._mark_job_error(current, exc)
                self._broadcast_error(current, exc)

    def _execute_job(self, job: DownloadJob) -> None:
        if self._is_cancel_requested(job):
            self._mark_cancelled(job)
            return
        if job.kind is not JobKind.DOWNLOAD:
            raise ValueError(f"Unsupported job kind: {job.kind.value}")
        self._execute_download_job(job)

    def _execute_download_job(self, job: DownloadJob) -> None:
        settings_cls, tidal_cls, download_cls = _download_dependencies()
        settings = settings_cls()
        started_at = job.started_at or time.time()

        if self._is_cancel_requested(job):
            self._mark_cancelled(job)
            return

        tidal = tidal_cls()
        track = tidal.session.track(job.track_id)
        name = track.full_name or track.name or job.name
        artist = ", ".join(a.name for a in track.artists if a.name) if track.artists else ""
        album = (track.album.name or "") if track.album else ""
        cover_url = self._cover_url(track)
        quality = self._quality_value(settings.data.quality_audio)

        self._update_job(
            job,
            name=name,
            artist=artist,
            album=album,
            cover_url=cover_url,
            quality=quality,
            status=JobStatus.RUNNING.value,
            progress=0,
        )
        current = self.get_job_for_test(job.id) or job
        self.events.broadcast(
            {
                "type": "progress",
                "job_id": job.id,
                "kind": job.kind.value,
                "track_id": job.track_id,
                "name": name,
                "artist": artist,
                "album": album,
                "cover_url": cover_url,
                "quality": quality,
                "status": "downloading",
                "progress": 0,
            }
        )

        if self._is_cancel_requested(current):
            self._mark_cancelled(current)
            return

        dl = download_cls(
            tidal_obj=tidal,
            path_base=settings.data.download_base_path,
            fn_logger=logger,
            skip_existing=settings.data.skip_existing,
        )

        retryable = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
            ConnectionError,
            OSError,
        )
        max_retries = 3
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            if self._is_cancel_requested(current):
                self._mark_cancelled(current)
                return
            try:
                dl.item(
                    file_template=settings.data.format_track,
                    media=track,
                    quality_audio=settings.data.quality_audio,
                )
                last_exc = None
                break
            except requests.exceptions.HTTPError as http_exc:
                if (
                    getattr(http_exc, "response", None) is not None
                    and http_exc.response.status_code == 429
                    and attempt < max_retries
                ):
                    last_exc = http_exc
                    self._mark_retrying(current, attempt + 1, max_retries)
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
            except retryable as retry_exc:
                if attempt >= max_retries:
                    raise
                last_exc = retry_exc
                self._mark_retrying(current, attempt + 1, max_retries)
                time.sleep(2 ** (attempt + 1))

        if last_exc is not None:
            raise last_exc
        if self._is_cancel_requested(current):
            self._mark_cancelled(current)
            return

        finished_at = time.time()
        self._record_history(
            track_id=job.track_id,
            name=name,
            artist=artist,
            album=album,
            status="done",
            started_at=started_at,
            finished_at=finished_at,
            cover_url=cover_url,
            quality=quality,
        )
        self._update_job(job, status=JobStatus.DONE.value, progress=100, finished_at=finished_at)
        self.events.broadcast(
            {
                "type": "complete",
                "job_id": job.id,
                "kind": job.kind.value,
                "track_id": job.track_id,
                "name": name,
                "artist": artist,
                "album": album,
                "cover_url": cover_url,
                "quality": quality,
                "status": "done",
            }
        )

        db = self._open_db()
        try:
            scan_new_downloads(db, settings)
        finally:
            db.close()

    def _cover_url(self, track) -> str:
        if not track.album:
            return ""
        for size in (320, 160):
            try:
                url = track.album.image(size)
            except Exception:
                continue
            if url:
                return url
        return ""

    def _quality_value(self, quality) -> str:
        return quality.value if hasattr(quality, "value") else str(quality or "LOSSLESS")

    def _update_job(self, job: DownloadJob, **fields) -> None:
        db = self._open_db()
        try:
            db.update_download_job(job.id, **fields)
        finally:
            db.close()

    def _record_history(self, **fields) -> None:
        db = self._open_db()
        try:
            db.record_download(**fields)
            db.commit()
        finally:
            db.close()

    def _record_error_history(self, job: DownloadJob, exc: Exception) -> None:
        try:
            self._record_history(
                track_id=job.track_id,
                name=job.name,
                artist=job.artist,
                album=job.album,
                status="error",
                error=str(exc),
                started_at=job.started_at,
                finished_at=time.time(),
                cover_url=job.cover_url,
                quality=job.quality,
            )
        except Exception:
            logger.exception("Failed to persist download error for track %s", job.track_id)

    def _mark_retrying(self, job: DownloadJob, attempt: int, max_retries: int) -> None:
        self._update_job(job, status=JobStatus.RETRYING.value)
        self.events.broadcast(
            {
                "type": "progress",
                "job_id": job.id,
                "kind": job.kind.value,
                "track_id": job.track_id,
                "name": job.name,
                "artist": job.artist,
                "album": job.album,
                "cover_url": job.cover_url,
                "quality": job.quality,
                "status": "retrying",
                "progress": job.progress,
                "retry": attempt,
                "max_retries": max_retries,
            }
        )

    def _mark_cancelled(self, job: DownloadJob) -> None:
        self._update_job(
            job,
            status=JobStatus.CANCELLED.value,
            finished_at=time.time(),
        )
        self._cancelled_ids.discard(job.track_id)
        self.events.broadcast(
            {
                "type": "cancelled",
                "job_id": job.id,
                "kind": job.kind.value,
                "track_id": job.track_id,
                "name": job.name,
            }
        )

    def _mark_job_error(self, job: DownloadJob, exc: Exception) -> None:
        self._record_error_history(job, exc)
        self._update_job(
            job,
            status=JobStatus.ERROR.value,
            error=str(exc),
            finished_at=time.time(),
        )

    def _broadcast_error(self, job: DownloadJob, exc: Exception) -> None:
        self.events.broadcast(
            {
                "type": "error",
                "job_id": job.id,
                "kind": job.kind.value,
                "track_id": job.track_id,
                "name": job.name,
                "artist": job.artist,
                "album": job.album,
                "cover_url": job.cover_url,
                "error": str(exc),
            }
        )
