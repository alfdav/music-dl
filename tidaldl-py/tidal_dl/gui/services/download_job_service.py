from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import requests

from tidal_dl.constants import QUALITY_STRING_TO_ENUM
from tidal_dl.gui.services.job_events import JobEventHub
from tidal_dl.gui.services.job_models import DownloadJob, JobKind, JobStatus, UpgradeJobInput
from tidal_dl.gui.services.upgrade_jobs import (
    cleanup_replaced_track_files,
    norm,
    resolve_tidal_album,
)
from tidal_dl.helper.library_db import LibraryDB, is_sqlite_lock_error
from tidal_dl.helper.path import format_path_media, path_config_base
from tidal_dl.model.downloader import DownloadOutcome

logger = logging.getLogger("music-dl.gui")
Settings: Any = None
Tidal: Any = None
Download: Any = None
register_downloaded_track: Any = None
_ACTIVE_JOB_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.RUNNING,
    JobStatus.INDEXING,
    JobStatus.RETRYING,
    JobStatus.PAUSED,
}


def _download_dependencies() -> tuple[Any, Any, Any]:
    global Settings, Tidal, Download
    if Settings is None or Tidal is None:
        from tidal_dl.config import Settings as _Settings
        from tidal_dl.config import Tidal as _Tidal

        Settings = Settings or _Settings
        Tidal = Tidal or _Tidal
    if Download is None:
        from tidal_dl.download import Download as _Download

        Download = _Download
    return Settings, Tidal, Download


def _upgrade_dependencies() -> tuple[Any, Any, Any, Any, Any]:
    global register_downloaded_track
    settings_cls, tidal_cls, download_cls = _download_dependencies()
    if register_downloaded_track is None:
        from tidal_dl.download import register_downloaded_track as _register_downloaded_track

        register_downloaded_track = _register_downloaded_track
    return settings_cls, tidal_cls, download_cls, DownloadOutcome, register_downloaded_track


def _iter_download_files(root: Path, extensions: set[str]) -> Iterable[Path]:
    from tidal_dl.helper.library_scanner import is_skipped_scan_dir, path_has_skipped_scan_dir

    if not root.is_dir():
        return
    for walk_root, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if not is_skipped_scan_dir(name)]
        for fname in files:
            file_path = Path(walk_root) / fname
            if path_has_skipped_scan_dir(file_path):
                continue
            if file_path.suffix.lower() not in extensions:
                continue
            yield file_path


def _prepare_downloaded_file(file_path: Path, roots: list[Path], known: set[str]) -> dict | None:
    from tidal_dl.gui.api.library import _AUDIO_EXTENSIONS, _read_metadata
    from tidal_dl.helper.library_scanner import path_has_skipped_scan_dir

    if path_has_skipped_scan_dir(file_path):
        return None
    if file_path.suffix.lower() not in _AUDIO_EXTENSIONS:
        return None
    from tidal_dl.helper.library_db.utils import canonical_library_path

    path_str = canonical_library_path(str(file_path))
    if path_str in known:
        return None
    meta = _read_metadata(file_path, roots)
    if meta:
        record = {
            "path": path_str,
            "status": "tagged" if meta["isrc"] else "needs_isrc",
            "isrc": meta["isrc"] or None,
            "artist": meta["artist"],
            "title": meta["name"],
            "album": meta["album"],
            "album_artist": meta.get("album_artist"),
            "release_date": meta.get("release_date"),
            "track_number": meta.get("track_number"),
            "track_total": meta.get("track_total"),
            "disc_number": meta.get("disc_number"),
            "disc_total": meta.get("disc_total"),
            "musicbrainz_release_id": meta.get("musicbrainz_release_id"),
            "musicbrainz_release_group_id": meta.get("musicbrainz_release_group_id"),
            "provider_namespace": meta.get("provider_namespace"),
            "provider_album_id": meta.get("provider_album_id"),
            "barcode": meta.get("barcode"),
            "duration": meta["duration"],
            "genre": meta.get("genre"),
            "quality": meta["quality"],
            "fmt": meta["format"],
            "codec": meta["codec"],
            "metadata_complete": True,
        }
    else:
        record = {
            "path": path_str,
            "status": "unreadable",
            "codec": "unknown",
            "metadata_complete": True,
        }
    known.add(path_str)
    return record


def scan_new_downloads(db, settings, paths: Iterable[Path] | None = None) -> None:
    from tidal_dl.gui.api.library import _AUDIO_EXTENSIONS, _flush_record_batch

    dl_path = Path(settings.data.download_base_path).expanduser()
    roots = [dl_path]
    from tidal_dl.helper.library_db.utils import canonical_library_path

    known = {canonical_library_path(path) for path in db.known_paths()}
    pending: list[dict] = []

    if paths is not None:
        candidates = (Path(path) for path in paths)
    else:
        candidates = _iter_download_files(dl_path, _AUDIO_EXTENSIONS)

    for file_path in candidates:
        if not file_path.is_file():
            continue
        record = _prepare_downloaded_file(file_path, roots, known)
        if record is None:
            continue
        pending.append(record)
        if len(pending) >= 50:
            _flush_record_batch(db, pending)
            pending.clear()

    _flush_record_batch(db, pending)

    import tidal_dl.gui.api.library as lib_mod

    lib_mod._invalidate_db_cache()


class DownloadJobService:
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        autostart: bool = True,
        dependency_provider: Callable[[], tuple[Any, Any, Any]] | None = None,
    ) -> None:
        self._db_path = db_path or Path(path_config_base()) / "library.db"
        self._download_dependency_provider = dependency_provider or _download_dependencies
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

        self.events.broadcast(self._queue_event("batch_queued"))
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
            self.events.broadcast(self._queue_event("batch_queued"))
        return {"status": "queued", "count": queued, "skipped": skipped}

    def pause(self) -> dict:
        self._running.clear()
        self.events.broadcast(self._queue_event("queue_paused"))
        return {"status": "paused"}

    def resume(self) -> dict:
        self._running.set()
        self.events.broadcast(self._queue_event("queue_resumed"))
        return {"status": "running"}

    def cancel(self, track_ids: list[int] | None = None) -> dict:
        db = self._open_db()
        try:
            if track_ids:
                count = db.cancel_queued_download_jobs(track_ids)
            else:
                self._cancel_all = True
                count = db.cancel_all_queued_download_jobs()
            active_count = db.active_download_job_count()
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
            return {"status": "cancelled", "count": count, "active_count": active_count}

        self._running.set()
        self.events.broadcast(self._queue_event("queue_cancelled", cancelled_count=count))
        return {"status": "cancelled", "count": count, "active_count": active_count}

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
            data = db.download_jobs_snapshot()
        finally:
            db.close()
        data["paused"] = not self._running.is_set()
        data["active_count"] = data["queued_count"] + len(data["active"])
        return data

    def _queue_event(self, event_type: str, **extra) -> dict:
        snapshot = self.snapshot()
        event = {
            "type": event_type,
            "count": snapshot["queued_count"],
            "queued_count": snapshot["queued_count"],
            "active_count": snapshot["active_count"],
            "paused": snapshot["paused"],
        }
        event.update(extra)
        return event

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
            events.append(self._queue_event("batch_queued"))
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

    def job_status_for_track(self, track_id: int) -> dict | None:
        db = self._open_db()
        try:
            assert db._conn
            row = db._conn.execute(
                """SELECT * FROM download_jobs
                   WHERE track_id = ?
                     AND status IN ('queued', 'running', 'indexing', 'retrying', 'paused')
                   ORDER BY created_at DESC, id DESC
                   LIMIT 1""",
                (track_id,),
            ).fetchone()
            if row is not None:
                job = DownloadJob.from_row(dict(row))
                return {
                    "job_id": str(track_id),
                    "status": job.status.value,
                    "progress": job.progress,
                    "title": job.name,
                    "artist": job.artist,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                }

            row = db._conn.execute(
                """SELECT track_id, name, artist, status, error, started_at, finished_at
                   FROM download_history
                   WHERE track_id = ?
                   ORDER BY finished_at DESC
                   LIMIT 1""",
                (track_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "job_id": str(track_id),
                "status": row["status"],
                "progress": 100.0 if row["status"] == "done" else 0.0,
                "title": row["name"],
                "artist": row["artist"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "error": row["error"],
            }
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
                row = db.claim_next_download_job()
            except sqlite3.OperationalError as exc:
                if not is_sqlite_lock_error(exc):
                    raise
                logger.warning("download worker deferred claim; library db locked")
                time.sleep(0.25)
                continue
            finally:
                db.close()
            if row is None:
                time.sleep(0.25)
                continue

            job = DownloadJob.from_row(row)
            try:
                self._execute_job(job)
            except Exception as exc:  # noqa: BLE001
                current = self.get_job_for_test(job.id) or job
                self._mark_job_error(current, exc)
                self._broadcast_error(current, exc)

    def _execute_job(self, job: DownloadJob) -> None:
        if self._is_cancel_requested(job):
            self._mark_cancelled(job)
            return
        if job.kind is JobKind.DOWNLOAD:
            self._execute_download_job(job)
            return
        if job.kind is JobKind.UPGRADE:
            self._execute_upgrade_job(job)
            return
        raise ValueError(f"Unsupported job kind: {job.kind.value}")

    def _execute_download_job(self, job: DownloadJob) -> None:
        settings_cls, tidal_cls, download_cls = self._download_dependency_provider()
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

        if self._is_cancel_requested(job):
            self._mark_cancelled(job)
            return
        if not self._update_job(
            job,
            name=name,
            artist=artist,
            album=album,
            cover_url=cover_url,
            quality=quality,
            status=JobStatus.RUNNING.value,
            progress=0,
        ):
            self._mark_cancelled(job)
            return
        current = self.get_job_for_test(job.id) or job
        self.events.broadcast(
            self._queue_event(
                "progress",
                job_id=job.id,
                kind=job.kind.value,
                track_id=job.track_id,
                name=name,
                artist=artist,
                album=album,
                cover_url=cover_url,
                quality=quality,
                status="downloading",
                progress=0,
            )
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
                download_outcome, output_path = dl.item(
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
                    if self._is_cancel_requested(current):
                        self._mark_cancelled(current)
                        return
                    if not self._mark_retrying(current, attempt + 1, max_retries):
                        return
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
            except retryable as retry_exc:
                if attempt >= max_retries:
                    raise
                last_exc = retry_exc
                if self._is_cancel_requested(current):
                    self._mark_cancelled(current)
                    return
                if not self._mark_retrying(current, attempt + 1, max_retries):
                    return
                time.sleep(2 ** (attempt + 1))

        if last_exc is not None:
            raise last_exc
        if self._is_cancel_requested(current):
            self._mark_cancelled(current)
            return
        if download_outcome == DownloadOutcome.FAILED:
            error = RuntimeError(f"Download failed for track {job.track_id}")
            self._mark_job_error(current, error)
            self._broadcast_error(current, error)
            return

        if not self._update_job(job, status=JobStatus.INDEXING.value, progress=100):
            self._mark_cancelled(job)
            return
        self.events.broadcast(
            self._queue_event(
                "progress",
                job_id=job.id,
                kind=job.kind.value,
                track_id=job.track_id,
                name=name,
                artist=artist,
                album=album,
                cover_url=cover_url,
                quality=quality,
                status="indexing",
                progress=100,
            )
        )

        index_paths = [Path(output_path)] if output_path else None
        db = self._open_db()
        try:
            scan_new_downloads(db, settings, index_paths)
        finally:
            db.close()

        if self._is_cancel_requested(current):
            self._mark_cancelled(current)
            return
        stored = self.get_job_for_test(job.id)
        if stored is not None and stored.status is JobStatus.CANCELLED:
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

    def _execute_upgrade_job(self, job: DownloadJob) -> None:
        settings_cls, tidal_cls, download_cls, outcome_cls, register_func = _upgrade_dependencies()
        settings = settings_cls()
        started_at = job.started_at or time.time()
        old_path = job.old_path or ""
        if not old_path:
            raise ValueError("Upgrade job missing old_path")

        db = self._open_db()
        try:
            row = db.get(old_path)
            if row is None:
                raise ValueError(f"Not in library: {old_path}")

            tidal = tidal_cls()
            track = tidal.session.track(job.track_id)
            name = track.full_name or track.name or job.name
            artist = ", ".join(a.name for a in track.artists if a.name) if track.artists else ""
            album = (track.album.name or "") if track.album else ""
            cover_url = self._cover_url(track)
            quality = job.quality or getattr(
                settings.data, "upgrade_target_quality", "HI_RES_LOSSLESS"
            )
            file_template = settings.data.format_track

            local_album = row.get("album") or ""
            isrc = row.get("isrc") or ""
            if local_album and isrc and hasattr(settings.data, "format_album"):
                tidal_album, album_tracks = resolve_tidal_album(
                    tidal.session,
                    local_album,
                    row.get("artist") or "",
                    [isrc],
                )
                album_track = self._track_by_isrc(album_tracks, isrc)
                if tidal_album and album_track:
                    track = album_track
                    name = track.full_name or track.name or name
                    artist = ", ".join(a.name for a in track.artists if a.name) if track.artists else artist
                    album = (track.album.name or "") if track.album else album
                    cover_url = self._cover_url(track)
                    file_template = format_path_media(
                        settings.data.format_album,
                        tidal_album,
                        delimiter_artist=settings.data.filename_delimiter_artist,
                        delimiter_album_artist=settings.data.filename_delimiter_album_artist,
                        use_primary_album_artist=settings.data.use_primary_album_artist,
                    )

            if self._is_cancel_requested(job):
                self._mark_cancelled(job)
                return
            if not self._update_job(
                job,
                name=name,
                artist=artist,
                album=album,
                cover_url=cover_url,
                quality=quality,
                status=JobStatus.RUNNING.value,
                progress=0,
            ):
                self._mark_cancelled(job)
                return
            self.events.broadcast(
                self._queue_event(
                    "progress",
                    job_id=job.id,
                    kind=job.kind.value,
                    track_id=job.track_id,
                    name=name,
                    artist=artist,
                    album=album,
                    cover_url=cover_url,
                    quality=quality,
                    status="downloading",
                    progress=0,
                )
            )
            self.events.broadcast(
                {
                    "type": "upgrade_progress",
                    "job_id": job.id,
                    "track_id": job.track_id,
                    "name": name,
                    "artist": artist,
                    "status": "upgrading",
                    "old_path": old_path,
                }
            )

            local_artist = norm(row.get("artist", ""))
            tidal_artist = norm(artist)
            if local_artist and tidal_artist and local_artist != tidal_artist:
                raise ValueError(f"Artist mismatch: expected {row.get('artist') or ''}, got {artist}")

            quality_enum = QUALITY_STRING_TO_ENUM.get(quality)
            if quality_enum is None:
                quality_enum = QUALITY_STRING_TO_ENUM.get("HI_RES_LOSSLESS")

            dl = download_cls(
                tidal_obj=tidal,
                path_base=settings.data.download_base_path,
                fn_logger=logger,
                skip_existing=False,
            )
            result = dl.item(
                file_template=file_template,
                media=track,
                quality_audio=quality_enum,
                duplicate_action_override="redownload",
            )
            outcome, new_path = result if isinstance(result, tuple) else (None, result)
            successful = {outcome_cls.DOWNLOADED, outcome_cls.COPIED, None}
            if outcome not in successful:
                raise ValueError(f"Download outcome: {outcome}")

            removed_paths = cleanup_replaced_track_files(
                db,
                old_path=old_path,
                new_path=str(new_path),
            )
            db.commit()
            new_path = self._rename_replacement_if_possible(old_path, new_path, removed_paths, db)
            register_func(new_path)
            db.commit()

            isrc = row.get("isrc")
            if isrc:
                db.delete_probe(isrc)
                db.commit()

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
            self._update_job(
                job,
                status=JobStatus.DONE.value,
                progress=100,
                new_path=str(new_path),
                finished_at=finished_at,
            )
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
            self.events.broadcast(
                {
                    "type": "upgrade_complete",
                    "job_id": job.id,
                    "track_id": job.track_id,
                    "name": name,
                    "artist": artist,
                    "status": "done",
                    "old_path": old_path,
                    "new_path": str(new_path),
                    "removed_paths": removed_paths,
                }
            )
        finally:
            db.close()

    def _track_by_isrc(self, tracks: list, isrc: str):
        target = isrc.upper()
        for track in tracks:
            track_isrc = getattr(track, "isrc", None)
            if track_isrc and track_isrc.upper() == target:
                return track
        return None

    def _rename_replacement_if_possible(
        self,
        old_path: str,
        new_path,
        removed_paths: list[str],
        db: LibraryDB,
    ) -> Path:
        replacement = Path(new_path) if not isinstance(new_path, Path) else new_path
        if not old_path or old_path not in removed_paths or str(replacement) == old_path:
            return replacement

        original = Path(old_path)
        if replacement.parent != original.parent or original.exists():
            return replacement

        try:
            replacement.rename(original)
            db.remove(str(replacement))
            return original
        except OSError:
            return replacement

    def _cover_url(self, track) -> str:
        if not track.album:
            return ""
        for size in (320, 160):
            try:
                url = track.album.image(size)
            except Exception:  # noqa: BLE001, S112
                continue
            if url:
                return url
        return ""

    def _quality_value(self, quality) -> str:
        return quality.value if hasattr(quality, "value") else str(quality or "LOSSLESS")

    def _update_job(self, job: DownloadJob, **fields) -> bool:
        new_status = fields.get("status")
        if new_status is not None:
            new_status = JobStatus(new_status)
        if new_status in _ACTIVE_JOB_STATUSES and self._is_cancel_requested(job):
            return False
        db = self._open_db()
        try:
            if new_status in _ACTIVE_JOB_STATUSES:
                current = db.get_download_job(job.id)
                if current and current.get("status") == JobStatus.CANCELLED.value:
                    return False
            db.update_download_job(job.id, **fields)
        finally:
            db.close()
        return True

    def _record_history(self, **fields) -> None:
        db = self._open_db()
        try:
            with db.write_transaction():
                db.record_download(**fields)
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

    def _mark_retrying(self, job: DownloadJob, attempt: int, max_retries: int) -> bool:
        if self._is_cancel_requested(job):
            self._mark_cancelled(job)
            return False
        if not self._update_job(job, status=JobStatus.RETRYING.value):
            self._mark_cancelled(job)
            return False
        self.events.broadcast(
            self._queue_event(
                "progress",
                job_id=job.id,
                kind=job.kind.value,
                track_id=job.track_id,
                name=job.name,
                artist=job.artist,
                album=job.album,
                cover_url=job.cover_url,
                quality=job.quality,
                status="retrying",
                progress=job.progress,
                retry=attempt,
                max_retries=max_retries,
            )
        )
        return True

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
        logger.error("%s", str(exc))
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
        if job.kind is JobKind.UPGRADE:
            self.events.broadcast(
                {
                    "type": "upgrade_error",
                    "job_id": job.id,
                    "track_id": job.track_id,
                    "name": job.name,
                    "artist": job.artist,
                    "error": str(exc),
                    "old_path": job.old_path,
                }
            )
