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

import datetime
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

        # download_history table
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS download_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id    INTEGER,
                name        TEXT,
                artist      TEXT,
                album       TEXT,
                status      TEXT NOT NULL,
                error       TEXT,
                started_at  REAL,
                finished_at REAL
            )"""
        )

        # favorites table
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS favorites (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                path        TEXT,
                tidal_id    INTEGER,
                artist      TEXT,
                title       TEXT,
                album       TEXT,
                isrc        TEXT,
                cover_url   TEXT,
                favorited_at INTEGER NOT NULL,
                UNIQUE(path),
                UNIQUE(tidal_id)
            )"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_favorites_at ON favorites(favorited_at)"
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

    def all_albums(self, query: str = "") -> list[dict]:
        """Return all albums grouped by album name. Multi-artist albums show 'Various Artists'."""
        assert self._conn
        where = "album IS NOT NULL AND status != 'unreadable'"
        params: list = []
        if query:
            where += " AND (album LIKE ? OR artist LIKE ?)"
            like = f"%{query}%"
            params.extend([like, like])
        rows = self._conn.execute(
            f"""SELECT album, COUNT(*) as track_count, MIN(path) as cover_path,
                       MAX(quality) as best_quality,
                       COUNT(DISTINCT artist) as artist_count,
                       MIN(artist) as first_artist
                FROM scanned
                WHERE {where}
                GROUP BY album
                ORDER BY album COLLATE NOCASE ASC""",
            params,
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["artist"] = d["first_artist"] if d["artist_count"] == 1 else "Various Artists"
            result.append(d)
        return result

    def albums_by_artist(self, artist: str) -> list[dict]:
        """Return albums for an artist with track count and a representative path for art."""
        assert self._conn
        rows = self._conn.execute(
            """SELECT album, COUNT(*) as track_count, MIN(path) as cover_path,
                      GROUP_CONCAT(DISTINCT genre) as genres,
                      MAX(quality) as best_quality
               FROM scanned
               WHERE artist = ? AND album IS NOT NULL AND status != 'unreadable'
               GROUP BY album ORDER BY album COLLATE NOCASE ASC""",
            (artist,),
        ).fetchall()
        return [dict(r) for r in rows]

    def album_tracks(self, artist: str, album: str) -> list[dict]:
        """Return all tracks for an album. If artist is 'Various Artists', return all artists."""
        assert self._conn
        if artist == "Various Artists":
            rows = self._conn.execute(
                """SELECT * FROM scanned
                   WHERE album = ? AND status != 'unreadable'
                   ORDER BY path ASC""",
                (album,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM scanned
                   WHERE artist = ? AND album = ? AND status != 'unreadable'
                   ORDER BY path ASC""",
                (artist, album),
            ).fetchall()
        return [dict(r) for r in rows]

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

    # ------------------------------------------------------------------
    # Play tracking
    # ------------------------------------------------------------------

    def increment_play(self, path: str) -> None:
        """Bump play_count and set last_played for a scanned track."""
        assert self._conn
        now = int(time.time())
        self._conn.execute(
            "UPDATE scanned SET play_count = play_count + 1, last_played = ? WHERE path = ?",
            (now, path),
        )

    def log_play_event(
        self,
        *,
        path: str | None,
        artist: str | None,
        genre: str | None,
        duration: int | None,
    ) -> None:
        """Insert a play event for activity charts."""
        assert self._conn
        now = int(time.time())
        self._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?, ?, ?, ?, ?)",
            (path, artist, genre, duration, now),
        )

    def home_stats(self) -> dict:
        """Aggregate all data needed for the Home view in one call."""
        assert self._conn
        c = self._conn

        # Total plays (sum of play_count on scanned)
        total_plays = c.execute(
            "SELECT COALESCE(SUM(play_count), 0) FROM scanned"
        ).fetchone()[0]

        # Top artist (by sum of play_count)
        top_artists_rows = c.execute(
            """SELECT artist, SUM(play_count) as total, path
               FROM scanned WHERE play_count > 0 AND artist IS NOT NULL
               GROUP BY artist ORDER BY total DESC LIMIT 5"""
        ).fetchall()

        top_artist = None
        top_artists = []
        for r in top_artists_rows:
            # Best cover: most-played track by this artist
            best = c.execute(
                "SELECT path FROM scanned WHERE artist = ? ORDER BY play_count DESC LIMIT 1",
                (r["artist"],),
            ).fetchone()
            # Per-artist stats: track count, album count, top genre
            artist_tracks = c.execute(
                "SELECT COUNT(*) FROM scanned WHERE artist = ?", (r["artist"],)
            ).fetchone()[0]
            artist_albums = c.execute(
                "SELECT COUNT(DISTINCT album) FROM scanned WHERE artist = ?", (r["artist"],)
            ).fetchone()[0]
            artist_genre_row = c.execute(
                "SELECT genre FROM scanned WHERE artist = ? AND genre IS NOT NULL AND genre != '' GROUP BY genre ORDER BY COUNT(*) DESC LIMIT 1",
                (r["artist"],),
            ).fetchone()
            entry = {
                "name": r["artist"],
                "play_count": r["total"],
                "cover_path": best["path"] if best else None,
                "track_count": artist_tracks,
                "album_count": artist_albums,
                "genre": artist_genre_row["genre"] if artist_genre_row else None,
            }
            top_artists.append(entry)
            if top_artist is None:
                top_artist = entry

        # Most replayed track
        most_replayed = None
        mr = c.execute(
            """SELECT path, title, artist, album, play_count
               FROM scanned WHERE play_count > 0
               ORDER BY play_count DESC LIMIT 1"""
        ).fetchone()
        if mr:
            most_replayed = {
                "name": mr["title"],
                "artist": mr["artist"],
                "album": mr["album"],
                "play_count": mr["play_count"],
                "cover_path": mr["path"],
                "path": mr["path"],
            }

        # Genre breakdown (from play_events — reflects listening behavior)
        genre_breakdown = [
            {"genre": r["genre"], "count": r["cnt"]}
            for r in c.execute(
                """SELECT genre, COUNT(*) as cnt FROM play_events
                   WHERE genre IS NOT NULL GROUP BY genre ORDER BY cnt DESC LIMIT 8"""
            ).fetchall()
        ]

        top_genre = genre_breakdown[0]["genre"] if genre_breakdown else None

        # Listening time (from play_events — actual plays)
        total_seconds = c.execute(
            "SELECT COALESCE(SUM(duration), 0) FROM play_events"
        ).fetchone()[0]
        listening_time_hours = round(total_seconds / 3600, 1)

        # Weekly activity — hours per day for current calendar week (Mon=0..Sun=6)
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        week_start = int(datetime.datetime.combine(monday, datetime.time.min).timestamp())
        week_end = week_start + 7 * 86400

        weekly_raw = c.execute(
            """SELECT played_at, duration FROM play_events
               WHERE played_at >= ? AND played_at < ?""",
            (week_start, week_end),
        ).fetchall()

        weekly_activity = [0.0] * 7
        for row in weekly_raw:
            day_idx = (row["played_at"] - week_start) // 86400
            if 0 <= day_idx < 7:
                weekly_activity[day_idx] += (row["duration"] or 0) / 3600

        weekly_activity = [round(h, 1) for h in weekly_activity]

        # Track count + genre breakdown by track count
        track_count = c.execute(
            "SELECT COUNT(*) FROM scanned WHERE status != 'unreadable'"
        ).fetchone()[0]

        track_genres = [
            {"genre": r["genre"], "count": r["cnt"]}
            for r in c.execute(
                """SELECT genre, COUNT(*) as cnt FROM scanned
                   WHERE genre IS NOT NULL AND status != 'unreadable'
                   GROUP BY genre ORDER BY cnt DESC LIMIT 4"""
            ).fetchall()
        ]

        # Album count + top artists by album count
        album_count = c.execute(
            "SELECT COUNT(DISTINCT album) FROM scanned WHERE album IS NOT NULL AND status != 'unreadable'"
        ).fetchone()[0]

        album_artists = [
            {"artist": r["artist"], "count": r["cnt"]}
            for r in c.execute(
                """SELECT artist, COUNT(DISTINCT album) as cnt FROM scanned
                   WHERE artist IS NOT NULL AND album IS NOT NULL AND status != 'unreadable'
                   GROUP BY artist ORDER BY cnt DESC LIMIT 4"""
            ).fetchall()
        ]

        return {
            "top_artist": top_artist,
            "top_artists": top_artists,
            "most_replayed": most_replayed,
            "top_genre": top_genre,
            "genre_breakdown": genre_breakdown,
            "listening_time_hours": listening_time_hours,
            "weekly_activity": weekly_activity,
            "track_count": track_count,
            "track_genres": track_genres,
            "album_count": album_count,
            "album_artists": album_artists,
            "total_plays": total_plays,
        }

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------

    def add_favorite(
        self,
        *,
        path: str | None = None,
        tidal_id: int | None = None,
        artist: str | None = None,
        title: str | None = None,
        album: str | None = None,
        isrc: str | None = None,
        cover_url: str | None = None,
    ) -> None:
        """Add a track to favorites. Skip if already exists."""
        assert self._conn
        now = int(time.time())
        if path:
            existing = self._conn.execute(
                "SELECT id FROM favorites WHERE path = ?", (path,)
            ).fetchone()
            if existing:
                return
        if tidal_id:
            existing = self._conn.execute(
                "SELECT id FROM favorites WHERE tidal_id = ?", (tidal_id,)
            ).fetchone()
            if existing:
                return
        self._conn.execute(
            """INSERT INTO favorites (path, tidal_id, artist, title, album, isrc, cover_url, favorited_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (path, tidal_id, artist, title, album, isrc, cover_url, now),
        )

    def remove_favorite(self, *, path: str | None = None, tidal_id: int | None = None) -> None:
        """Remove a favorite by path or tidal_id."""
        assert self._conn
        if path:
            self._conn.execute("DELETE FROM favorites WHERE path = ?", (path,))
        elif tidal_id:
            self._conn.execute("DELETE FROM favorites WHERE tidal_id = ?", (tidal_id,))

    def is_favorite(self, *, path: str | None = None, tidal_id: int | None = None) -> bool:
        """Check if a track is favorited."""
        assert self._conn
        if path:
            return self._conn.execute(
                "SELECT 1 FROM favorites WHERE path = ?", (path,)
            ).fetchone() is not None
        if tidal_id:
            return self._conn.execute(
                "SELECT 1 FROM favorites WHERE tidal_id = ?", (tidal_id,)
            ).fetchone() is not None
        return False

    def all_favorites(self) -> list[dict]:
        """Return all favorites ordered by most recent first."""
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM favorites ORDER BY favorited_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def favorite_paths(self) -> set[str]:
        """Return set of favorited local paths for quick lookup."""
        assert self._conn
        rows = self._conn.execute(
            "SELECT path FROM favorites WHERE path IS NOT NULL"
        ).fetchall()
        return {r["path"] for r in rows}

    def favorite_tidal_ids(self) -> set[int]:
        """Return set of favorited tidal IDs for quick lookup."""
        assert self._conn
        rows = self._conn.execute(
            "SELECT tidal_id FROM favorites WHERE tidal_id IS NOT NULL"
        ).fetchall()
        return {r["tidal_id"] for r in rows}

    def pending_favorites(self) -> list[dict]:
        """Return favorites with tidal_id but no local path (auto-download candidates)."""
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM favorites WHERE tidal_id IS NOT NULL AND path IS NULL ORDER BY favorited_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Download history
    # ------------------------------------------------------------------

    def record_download(
        self,
        *,
        track_id: int,
        name: str,
        artist: str | None = None,
        album: str | None = None,
        status: str,
        error: str | None = None,
        started_at: float | None = None,
        finished_at: float | None = None,
    ) -> None:
        """Record a download completion (success or failure)."""
        assert self._conn
        self._conn.execute(
            """INSERT INTO download_history (track_id, name, artist, album, status, error, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (track_id, name, artist, album, status, error, started_at, finished_at),
        )

    def download_history(self, limit: int = 50) -> list[dict]:
        """Return recent download history."""
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM download_history ORDER BY finished_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
