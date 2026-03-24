"""library_db.py

SQLite-backed scan ledger for the music library.  Caches full metadata
so the GUI library endpoint never touches mutagen for known files.

Schema:
    scanned(path TEXT PK, isrc TEXT, status TEXT, artist TEXT, title TEXT,
            album TEXT, duration INT, quality TEXT, format TEXT,
            play_count INT DEFAULT 0, last_played INT, genre TEXT,
            scanned_at INT)
    play_events(id INT PK, path TEXT, artist TEXT, genre TEXT,
                duration INT, played_at INT NOT NULL)

Stored at ``~/.config/music-dl/library.db``.
"""

from __future__ import annotations

import pathlib
import sqlite3
import time


class LibraryDB:
    """Thin wrapper around a SQLite scan ledger."""

    _SCHEMA_VERSION = 3

    def __init__(self, db_path: pathlib.Path) -> None:
        self._path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        assert self._conn
        # Check if table exists at all
        exists = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scanned'"
        ).fetchone()

        if not exists:
            self._conn.execute(
                """CREATE TABLE scanned (
                    path       TEXT PRIMARY KEY,
                    isrc       TEXT,
                    status     TEXT NOT NULL,
                    artist     TEXT,
                    title      TEXT,
                    album      TEXT,
                    duration   INTEGER,
                    quality    TEXT,
                    format     TEXT,
                    play_count INTEGER DEFAULT 0,
                    last_played INTEGER,
                    genre      TEXT,
                    scanned_at INTEGER NOT NULL
                )"""
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scanned_status ON scanned(status)"
            )
        else:
            # Migrate v1 → v2: add missing columns
            cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(scanned)")}
            for col, coltype in [("album", "TEXT"), ("duration", "INTEGER"), ("quality", "TEXT"), ("format", "TEXT")]:
                if col not in cols:
                    self._conn.execute(f"ALTER TABLE scanned ADD COLUMN {col} {coltype}")

            # v2 → v3: play tracking + genre
            for col, coltype, default in [
                ("play_count", "INTEGER", "0"),
                ("last_played", "INTEGER", None),
                ("genre", "TEXT", None),
            ]:
                if col not in cols:
                    if default is not None:
                        self._conn.execute(
                            f"ALTER TABLE scanned ADD COLUMN {col} {coltype} DEFAULT {default}"
                        )
                    else:
                        self._conn.execute(
                            f"ALTER TABLE scanned ADD COLUMN {col} {coltype}"
                        )

        # play_events table (time-series for activity charts)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS play_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                path       TEXT,
                artist     TEXT,
                genre      TEXT,
                duration   INTEGER,
                played_at  INTEGER NOT NULL
            )"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_play_events_at ON play_events(played_at)"
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_known(self, path: str) -> bool:
        """Return True if *path* has already been scanned."""
        assert self._conn
        row = self._conn.execute(
            "SELECT 1 FROM scanned WHERE path = ?", (path,)
        ).fetchone()
        return row is not None

    def known_paths(self) -> set[str]:
        """Return the set of all scanned paths (for bulk skip checks)."""
        assert self._conn
        rows = self._conn.execute("SELECT path FROM scanned").fetchall()
        return {r["path"] for r in rows}

    def complete_paths(self) -> set[str]:
        """Return paths that have full metadata (album, duration, quality populated)."""
        assert self._conn
        rows = self._conn.execute(
            "SELECT path FROM scanned WHERE album IS NOT NULL AND duration IS NOT NULL"
        ).fetchall()
        return {r["path"] for r in rows}

    def get(self, path: str) -> dict | None:
        """Return full cached metadata for a single path, or None."""
        assert self._conn
        row = self._conn.execute("SELECT * FROM scanned WHERE path = ?", (path,)).fetchone()
        if not row:
            return None
        return dict(row)

    def all_tracks(self) -> list[dict]:
        """Return all cached tracks with status != 'unreadable'."""
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM scanned WHERE status != 'unreadable'"
        ).fetchall()
        return [dict(r) for r in rows]

    def tracks_page(
        self,
        sort: str = "artist",
        limit: int = 50,
        offset: int = 0,
        query: str = "",
    ) -> tuple[list[dict], int]:
        """Return a page of tracks + total count.  Sorting is done in SQL."""
        assert self._conn
        sort_map = {
            "artist": "artist COLLATE NOCASE ASC",
            "album": "album COLLATE NOCASE ASC",
            "title": "title COLLATE NOCASE ASC",
            "recent": "scanned_at DESC",
            "random": "RANDOM()",
        }
        order = sort_map.get(sort, sort_map["artist"])

        where = "status != 'unreadable'"
        params: list = []
        if query:
            where += " AND (title LIKE ? OR artist LIKE ? OR album LIKE ?)"
            like = f"%{query}%"
            params.extend([like, like, like])

        total = self._conn.execute(
            f"SELECT COUNT(*) FROM scanned WHERE {where}", params
        ).fetchone()[0]

        rows = self._conn.execute(
            f"SELECT * FROM scanned WHERE {where} "
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total

    def untagged(self, *, limit: int = 0) -> list[tuple[str, str, str]]:
        """Return (path, artist, title) for files needing ISRC lookup."""
        assert self._conn
        query = "SELECT path, artist, title FROM scanned WHERE status = 'needs_isrc'"
        if limit > 0:
            query += f" LIMIT {limit}"
        rows = self._conn.execute(query).fetchall()
        return [(r["path"], r["artist"], r["title"]) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        """Return {status: count} summary."""
        assert self._conn
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM scanned GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def record(
        self,
        path: str,
        *,
        status: str,
        isrc: str | None = None,
        artist: str | None = None,
        title: str | None = None,
        album: str | None = None,
        duration: int | None = None,
        quality: str | None = None,
        fmt: str | None = None,
        genre: str | None = None,
    ) -> None:
        """Insert or update a scan result."""
        assert self._conn
        now = int(time.time())
        self._conn.execute(
            """INSERT INTO scanned (path, isrc, status, artist, title, album,
                                    duration, quality, format, genre, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                   isrc = excluded.isrc,
                   status = excluded.status,
                   artist = excluded.artist,
                   title = excluded.title,
                   album = excluded.album,
                   duration = excluded.duration,
                   quality = excluded.quality,
                   format = excluded.format,
                   genre = excluded.genre,
                   scanned_at = excluded.scanned_at""",
            (path, isrc, status, artist, title, album, duration, quality, fmt, genre, now),
        )

    def remove(self, path: str) -> None:
        """Remove a path from the ledger (e.g. file deleted)."""
        assert self._conn
        self._conn.execute("DELETE FROM scanned WHERE path = ?", (path,))

    def commit(self) -> None:
        assert self._conn
        self._conn.commit()
