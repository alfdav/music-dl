"""SQLite ledger for playlist sync. Not library.db. Writes stay short."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tidal_dl.playlist_sync.models import Track

_TRACK_STATUSES = (
    "seen",
    "matched_local",
    "queued",
    "downloaded",
    "added",
    "unmatched",
    "unobtainable",
    "failed",
    "needs_review",
    "download_mismatch",
)


def default_ledger_path() -> Path:
    from tidal_dl.helper.path import path_config_base

    return Path(path_config_base()) / "playlist_sync.db"


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create()

    def close(self) -> None:
        self._conn.close()

    def _create(self) -> None:
        status_list = ", ".join(f"'{status}'" for status in _TRACK_STATUSES)

        def statements() -> None:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS playlists (
                    source TEXT NOT NULL,
                    source_playlist_id TEXT NOT NULL,
                    name_norm TEXT NOT NULL,
                    last_updated_seen TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (source, source_playlist_id)
                )"""
            )
            self._conn.execute(
                f"""CREATE TABLE IF NOT EXISTS tracks (
                    source TEXT NOT NULL,
                    source_track_id TEXT NOT NULL,
                    name_norm TEXT NOT NULL,
                    isrc TEXT,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    duration REAL,
                    first_seen_at TEXT,
                    status TEXT NOT NULL CHECK (status IN ({status_list})),
                    last_failure_day TEXT,
                    plex_rating_key TEXT,
                    available INTEGER NOT NULL DEFAULT 1,
                    version TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (source, source_track_id, name_norm)
                )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS daily_downloads (
                    day TEXT PRIMARY KEY,
                    count INTEGER NOT NULL
                )"""
            )

        self._write(statements)

    def _write(self, fn: Callable[[], None]) -> None:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            fn()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get_playlist(self, source: str, source_playlist_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """SELECT source, source_playlist_id, name_norm, last_updated_seen
               FROM playlists WHERE source = ? AND source_playlist_id = ?""",
            (source, source_playlist_id),
        ).fetchone()
        return dict(row) if row else None

    def upsert_playlist(self, source: str, source_playlist_id: str, name_norm: str, last_updated: str) -> None:
        def run() -> None:
            self._conn.execute(
                """INSERT INTO playlists (source, source_playlist_id, name_norm, last_updated_seen)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(source, source_playlist_id) DO UPDATE SET
                     name_norm = excluded.name_norm,
                     last_updated_seen = excluded.last_updated_seen""",
                (source, source_playlist_id, name_norm, last_updated),
            )

        self._write(run)

    def get_track(self, source: str, source_track_id: str, name_norm: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """SELECT * FROM tracks
               WHERE source = ? AND source_track_id = ? AND name_norm = ?""",
            (source, source_track_id, name_norm),
        ).fetchone()
        return dict(row) if row else None

    def tracks_for(self, source: str, name_norm: str) -> list[Track]:
        rows = self._conn.execute(
            """SELECT * FROM tracks WHERE source = ? AND name_norm = ?
               ORDER BY first_seen_at, source_track_id""",
            (source, name_norm),
        ).fetchall()
        return [_track_from_row(row) for row in rows]

    def remember_track(self, track: Track, name_norm: str, *, seen_at: str) -> None:
        """Insert a first sighting or refresh metadata without dropping status."""

        def run() -> None:
            current = self._conn.execute(
                """SELECT first_seen_at, status, last_failure_day, plex_rating_key
                   FROM tracks
                   WHERE source = ? AND source_track_id = ? AND name_norm = ?""",
                (track.source, track.source_track_id, name_norm),
            ).fetchone()
            if current is None:
                self._conn.execute(
                    """INSERT INTO tracks (
                        source, source_track_id, name_norm, isrc, title, artist, album,
                        duration, first_seen_at, status, last_failure_day, plex_rating_key,
                        available, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'seen', NULL, NULL, ?, ?)""",
                    _track_values(track, name_norm, seen_at),
                )
                return
            self._conn.execute(
                """UPDATE tracks
                   SET isrc = ?, title = ?, artist = ?, album = ?, duration = ?,
                       available = ?, version = ?
                   WHERE source = ? AND source_track_id = ? AND name_norm = ?""",
                (
                    track.isrc,
                    track.title,
                    track.artist,
                    track.album,
                    track.duration,
                    1 if track.available else 0,
                    track.version,
                    track.source,
                    track.source_track_id,
                    name_norm,
                ),
            )

        self._write(run)

    def set_status(
        self,
        track: Track,
        name_norm: str,
        status: str,
        *,
        seen_at: str,
        last_failure_day: str | None = None,
        plex_rating_key: str | None = None,
    ) -> None:
        if status not in _TRACK_STATUSES:
            raise ValueError(f"unknown playlist sync status: {status}")

        def run() -> None:
            current = self._conn.execute(
                """SELECT first_seen_at, last_failure_day, plex_rating_key
                   FROM tracks
                   WHERE source = ? AND source_track_id = ? AND name_norm = ?""",
                (track.source, track.source_track_id, name_norm),
            ).fetchone()
            first_seen = seen_at if current is None else current["first_seen_at"]
            failure_day = last_failure_day
            if failure_day is None and current is not None:
                failure_day = current["last_failure_day"]
            rating_key = plex_rating_key
            if rating_key is None and current is not None:
                rating_key = current["plex_rating_key"]
            self._conn.execute(
                """INSERT INTO tracks (
                    source, source_track_id, name_norm, isrc, title, artist, album,
                    duration, first_seen_at, status, last_failure_day, plex_rating_key,
                    available, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_track_id, name_norm) DO UPDATE SET
                    isrc = excluded.isrc,
                    title = excluded.title,
                    artist = excluded.artist,
                    album = excluded.album,
                    duration = excluded.duration,
                    status = excluded.status,
                    last_failure_day = excluded.last_failure_day,
                    plex_rating_key = excluded.plex_rating_key,
                    available = excluded.available,
                    version = excluded.version""",
                (
                    track.source,
                    track.source_track_id,
                    name_norm,
                    track.isrc,
                    track.title,
                    track.artist,
                    track.album,
                    track.duration,
                    first_seen,
                    status,
                    failure_day,
                    rating_key,
                    1 if track.available else 0,
                    track.version,
                ),
            )

        self._write(run)

    def downloads_on(self, day: str) -> int:
        row = self._conn.execute(
            "SELECT count FROM daily_downloads WHERE day = ?",
            (day,),
        ).fetchone()
        return int(row["count"]) if row else 0

    def increment_downloads(self, day: str) -> int:
        new_count = 0

        def run() -> None:
            nonlocal new_count
            self._conn.execute(
                """INSERT INTO daily_downloads (day, count) VALUES (?, 1)
                   ON CONFLICT(day) DO UPDATE SET count = count + 1""",
                (day,),
            )
            row = self._conn.execute(
                "SELECT count FROM daily_downloads WHERE day = ?",
                (day,),
            ).fetchone()
            new_count = int(row["count"])

        self._write(run)
        return new_count


def _track_values(track: Track, name_norm: str, seen_at: str) -> tuple[Any, ...]:
    return (
        track.source,
        track.source_track_id,
        name_norm,
        track.isrc,
        track.title,
        track.artist,
        track.album,
        track.duration,
        seen_at,
        1 if track.available else 0,
        track.version,
    )


def _track_from_row(row: sqlite3.Row) -> Track:
    isrc = row["isrc"]
    return Track(
        source=row["source"],
        source_track_id=row["source_track_id"],
        title=row["title"] or "",
        artist=row["artist"] or "",
        album=row["album"] or "",
        duration=row["duration"],
        isrc=(str(isrc).strip() or None) if isrc else None,
        available=bool(row["available"]),
        version=row["version"] or "",
        playlist_name=row["name_norm"],
    )
