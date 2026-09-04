"""Play events and home dashboard stats."""

from tidal_dl.helper.library_db._common import *
from tidal_dl.helper.library_scanner import visible_scanned_path_sql


class PlaybackMixin:
    def increment_play(self, path: str) -> None:
        """Bump play_count and set last_played for a scanned track."""
        assert self._conn
        now = int(time.time())
        nfc, nfd = library_path_forms(path)
        self._conn.execute(
            "UPDATE scanned SET play_count = play_count + 1, last_played = ? WHERE path IN (?, ?)",
            (now, nfc, nfd),
        )

    def log_play_event(
        self,
        path: str | None = None,
        *,
        artist: str | None = None,
        genre: str | None = None,
        duration: int | None = None,
        played_at: int | None = None,
        ) -> None:
        """Insert a play event for activity charts."""
        assert self._conn
        ts = played_at if played_at is not None else int(time.time())
        event_path = canonical_library_path(path) if path else path
        self._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?, ?, ?, ?, ?)",
            (event_path, artist, genre, duration, ts),
        )

    def recent_plays(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return latest unique local tracks from persisted play_events."""
        assert self._conn
        safe_limit = max(1, min(int(limit), 100))
        safe_offset = max(0, int(offset))
        rows = self._conn.execute(
            f"""SELECT s.path, s.isrc, s.artist, s.title, s.album, s.duration,
                      s.quality, s.format, s.codec, s.genre, s.play_count, s.last_played,
                      s.art_available,
                      latest.played_at
               FROM (
                   SELECT path, MAX(played_at) AS played_at
                   FROM play_events
                   WHERE path IS NOT NULL AND path != ''
                   GROUP BY path
               ) latest
               JOIN scanned s ON s.path = latest.path
               WHERE s.status != 'unreadable' AND s.missing_since IS NULL
                 AND {visible_scanned_path_sql("s.path")}
               ORDER BY latest.played_at DESC
               LIMIT ? OFFSET ?""",
            (safe_limit, safe_offset),
        ).fetchall()

        tracks: list[dict] = []
        for row in rows:
            d = dict(row)
            path = d["path"]
            d["name"] = d.pop("title") or pathlib.Path(path).stem
            d["local_path"] = path
            d["is_local"] = True
            tracks.append(d)
        return tracks

    def _windowed_stats(self, since: int) -> dict:
        """Return play stats for play_events with played_at >= since."""
        assert self._conn
        c = self._conn

        total_plays = c.execute(
            "SELECT COUNT(*) FROM play_events WHERE played_at >= ?", (since,)
        ).fetchone()[0]

        top_artists_rows = c.execute(
            """SELECT pe.artist, COUNT(*) as total
               FROM play_events pe
               JOIN scanned s ON s.path = pe.path AND s.missing_since IS NULL
               WHERE pe.artist IS NOT NULL AND pe.played_at >= ?
               GROUP BY pe.artist ORDER BY total DESC LIMIT 5""",
            (since,),
        ).fetchall()

        top_artist = None
        top_artists = []
        for r in top_artists_rows:
            best_path = c.execute(
                """SELECT path FROM play_events
                   WHERE artist = ? AND path IS NOT NULL AND played_at >= ?
                   GROUP BY path ORDER BY COUNT(*) DESC LIMIT 1""",
                (r["artist"], since),
            ).fetchone()
            if not best_path:
                best_path = c.execute(
                    "SELECT path FROM scanned WHERE artist = ? AND missing_since IS NULL LIMIT 1",
                    (r["artist"],),
                ).fetchone()
            artist_tracks = c.execute(
                "SELECT COUNT(*) FROM scanned WHERE artist = ? AND missing_since IS NULL",
                (r["artist"],),
            ).fetchone()[0]
            artist_albums = c.execute(
                "SELECT COUNT(DISTINCT album) FROM scanned WHERE artist = ? AND missing_since IS NULL",
                (r["artist"],),
            ).fetchone()[0]
            artist_genre_row = c.execute(
                "SELECT genre FROM scanned WHERE artist = ? AND missing_since IS NULL "
                "AND genre IS NOT NULL AND genre != '' GROUP BY genre ORDER BY COUNT(*) DESC LIMIT 1",
                (r["artist"],),
            ).fetchone()
            entry = {
                "name": r["artist"],
                "play_count": r["total"],
                "cover_path": best_path["path"] if best_path else None,
                "track_count": artist_tracks,
                "album_count": artist_albums,
                "genre": artist_genre_row["genre"] if artist_genre_row else None,
            }
            top_artists.append(entry)
            if top_artist is None:
                top_artist = entry

        most_replayed = None
        mr = c.execute(
            """SELECT pe.path, s.title, pe.artist, s.album, COUNT(*) as play_count
               FROM play_events pe
               JOIN scanned s ON s.path = pe.path AND s.missing_since IS NULL
               WHERE pe.path IS NOT NULL AND pe.played_at >= ?
               GROUP BY pe.path ORDER BY play_count DESC LIMIT 1""",
            (since,),
        ).fetchone()
        if mr:
            most_replayed = {
                "name": mr["title"] or pathlib.Path(mr["path"]).stem if mr["path"] else "Unknown",
                "artist": mr["artist"],
                "album": mr["album"],
                "play_count": mr["play_count"],
                "cover_path": mr["path"],
                "path": mr["path"],
            }

        genre_breakdown = [
            {"genre": r["genre"], "count": r["cnt"]}
            for r in c.execute(
                """SELECT genre, COUNT(*) as cnt FROM play_events
                   WHERE genre IS NOT NULL AND played_at >= ?
                   GROUP BY genre ORDER BY cnt DESC LIMIT 8""",
                (since,),
            ).fetchall()
        ]

        return {
            "total_plays": total_plays,
            "top_artist": top_artist,
            "top_artists": top_artists,
            "most_replayed": most_replayed,
            "genre_breakdown": genre_breakdown,
        }

    def home_stats(self, *, extras: bool = True) -> dict:
        """Aggregate data for the Home view.

        First-paint tiles use extras=False so /api/home stays off NAS probes and
        unused completionist / peak-hour / streak / format work.
        """
        assert self._conn
        c = self._conn

        # Total plays (from play_events — authoritative source, survives cache prune)
        total_plays = c.execute(
            "SELECT COUNT(*) FROM play_events"
        ).fetchone()[0]

        # Top artist (from play_events — authoritative play counts)
        top_artists_rows = c.execute(
            """SELECT pe.artist, COUNT(*) as total
               FROM play_events pe
               JOIN scanned s ON s.path = pe.path AND s.missing_since IS NULL
               WHERE pe.artist IS NOT NULL
               GROUP BY pe.artist ORDER BY total DESC LIMIT 5"""
        ).fetchall()

        top_artist = None
        top_artists = []
        for r in top_artists_rows:
            # Best cover: most-played track path from play_events, then look up in scanned
            best_path = c.execute(
                """SELECT path FROM play_events
                   WHERE artist = ? AND path IS NOT NULL
                   GROUP BY path ORDER BY COUNT(*) DESC LIMIT 1""",
                (r["artist"],),
            ).fetchone()
            best = None
            if best_path:
                best = best_path
            else:
                # Fallback: any track by this artist in scanned
                best = c.execute(
                    "SELECT path FROM scanned WHERE artist = ? AND missing_since IS NULL LIMIT 1",
                    (r["artist"],),
                ).fetchone()
            # Per-artist stats: track count, album count, top genre
            artist_tracks = c.execute(
                "SELECT COUNT(*) FROM scanned WHERE artist = ? AND missing_since IS NULL",
                (r["artist"],),
            ).fetchone()[0]
            artist_albums = c.execute(
                "SELECT COUNT(DISTINCT album) FROM scanned WHERE artist = ? AND missing_since IS NULL",
                (r["artist"],),
            ).fetchone()[0]
            artist_genre_row = c.execute(
                "SELECT genre FROM scanned WHERE artist = ? AND missing_since IS NULL "
                "AND genre IS NOT NULL AND genre != '' GROUP BY genre ORDER BY COUNT(*) DESC LIMIT 1",
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

        # Most replayed track (from play_events — authoritative)
        most_replayed = None
        mr = c.execute(
            """SELECT pe.path, s.title, pe.artist, s.album, COUNT(*) as play_count
               FROM play_events pe
               JOIN scanned s ON s.path = pe.path AND s.missing_since IS NULL
               WHERE pe.path IS NOT NULL
               GROUP BY pe.path ORDER BY play_count DESC LIMIT 1"""
        ).fetchone()
        if mr:
            most_replayed = {
                "name": mr["title"] or pathlib.Path(mr["path"]).stem if mr["path"] else "Unknown",
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
            "SELECT COUNT(*) FROM scanned WHERE status != 'unreadable' AND missing_since IS NULL"
        ).fetchone()[0]

        track_genres = [
            {"genre": r["genre"], "count": r["cnt"]}
            for r in c.execute(
                """SELECT genre, COUNT(*) as cnt FROM scanned
                   WHERE genre IS NOT NULL AND status != 'unreadable' AND missing_since IS NULL
                   GROUP BY genre ORDER BY cnt DESC LIMIT 4"""
            ).fetchall()
        ]

        # Album count + top artists by album count
        album_count = c.execute(
            "SELECT COUNT(DISTINCT album) FROM scanned WHERE album IS NOT NULL "
            "AND status != 'unreadable' AND missing_since IS NULL"
        ).fetchone()[0]

        album_artists = [
            {"artist": r["artist"], "count": r["cnt"]}
            for r in c.execute(
                """SELECT artist, COUNT(DISTINCT album) as cnt FROM scanned
                   WHERE artist IS NOT NULL AND album IS NOT NULL
                     AND status != 'unreadable' AND missing_since IS NULL
                   GROUP BY artist ORDER BY cnt DESC LIMIT 4"""
            ).fetchall()
        ]

        # Listening streak — consecutive days ending today with at least one play
        streak_rows = c.execute(
            """SELECT DISTINCT date(played_at, 'unixepoch', 'localtime') as d
               FROM play_events ORDER BY d DESC"""
        ).fetchall()
        streak = 0
        if streak_rows:
            check = datetime.date.today()
            for row in streak_rows:
                d = datetime.date.fromisoformat(row["d"])
                if d == check:
                    streak += 1
                    check -= datetime.timedelta(days=1)
                elif d < check:
                    break

        peak_hours = [0] * 24
        peak_hour = None
        this_week_plays = 0
        last_week_plays = 0
        unplayed_count = 0
        format_breakdown: list[dict] = []
        if extras:
            # Peak hours — 24-element list, play count per hour of day
            for row in c.execute("SELECT played_at FROM play_events").fetchall():
                hour = datetime.datetime.fromtimestamp(row["played_at"]).hour
                peak_hours[hour] += 1

            peak_hour = peak_hours.index(max(peak_hours)) if any(h > 0 for h in peak_hours) else None

            # This week vs last week play counts
            this_week_plays = c.execute(
                "SELECT COUNT(*) FROM play_events WHERE played_at >= ?",
                (week_start,),
            ).fetchone()[0]

            last_week_start = week_start - 7 * 86400
            last_week_plays = c.execute(
                "SELECT COUNT(*) FROM play_events WHERE played_at >= ? AND played_at < ?",
                (last_week_start, week_start),
            ).fetchone()[0]

            # Tracks never played
            unplayed_count = c.execute(
                "SELECT COUNT(*) FROM scanned WHERE (play_count = 0 OR play_count IS NULL) "
                "AND status != 'unreadable' AND missing_since IS NULL"
            ).fetchone()[0]

            # Track count by audio format
            format_breakdown = [
                {"format": r["format"], "count": r["cnt"]}
                for r in c.execute(
                    """SELECT format, COUNT(*) as cnt FROM scanned
                       WHERE format IS NOT NULL AND status != 'unreadable' AND missing_since IS NULL
                       GROUP BY format ORDER BY cnt DESC"""
                ).fetchall()
            ]

        # Album with most combined plays (from play_events — authoritative source)
        top_album = None
        ta = c.execute(
            """SELECT s.album, pe.artist, COUNT(*) as total, MIN(pe.path) as cover_path
               FROM play_events pe
               JOIN scanned s ON s.path = pe.path AND s.missing_since IS NULL
               WHERE pe.path IS NOT NULL AND s.album IS NOT NULL
               GROUP BY s.album, pe.artist
               ORDER BY total DESC LIMIT 1"""
        ).fetchone()
        if ta and ta["album"]:
            top_album = {
                "album": ta["album"],
                "artist": ta["artist"],
                "play_count": ta["total"],
                "cover_path": ta["cover_path"],
            }

        # Rolling 7-day windowed stats
        seven_days_ago = int(time.time()) - 7 * 86400
        this_week = self._windowed_stats(seven_days_ago)

        # Tracks added in last 30 days
        thirty_days_ago = int(time.time()) - 30 * 86400
        collection_growth = c.execute(
            "SELECT COUNT(*) FROM scanned WHERE scanned_at >= ? AND status != 'unreadable' "
            "AND missing_since IS NULL",
            (thirty_days_ago,),
        ).fetchone()[0]

        # Total favorites (table may not exist if migration hasn't run)
        try:
            favorites_count = c.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
        except sqlite3.OperationalError:
            favorites_count = 0

        best_streak = 0
        completionist_total = 0
        completionist_complete = 0
        recent_albums: list[dict] = []
        if extras:
            # Best-ever listening streak (longest consecutive-day run)
            streak_days = [
                r[0]
                for r in c.execute(
                    "SELECT DISTINCT date(played_at, 'unixepoch', 'localtime') as d FROM play_events ORDER BY d"
                ).fetchall()
            ]
            if streak_days:
                current_run = 1
                for i in range(1, len(streak_days)):
                    prev = datetime.datetime.strptime(streak_days[i - 1], "%Y-%m-%d")
                    curr = datetime.datetime.strptime(streak_days[i], "%Y-%m-%d")
                    if (curr - prev).days == 1:
                        current_run += 1
                    else:
                        best_streak = max(best_streak, current_run)
                        current_run = 1
                best_streak = max(best_streak, current_run)

            # Completionist albums: albums where every scanned track has been played
            completionist_row = c.execute(
                """SELECT
                     COUNT(*) as total,
                     SUM(CASE WHEN played_count >= track_count THEN 1 ELSE 0 END) as complete
                   FROM (
                     SELECT s.album, s.artist, COUNT(*) as track_count,
                            COUNT(DISTINCT pe.path) as played_count
                     FROM scanned s
                     LEFT JOIN play_events pe ON pe.path = s.path
                     WHERE s.album IS NOT NULL AND s.status != 'unreadable' AND s.missing_since IS NULL
                     GROUP BY s.album, s.artist
                   )"""
            ).fetchone()
            completionist_total = completionist_row["total"] if completionist_row else 0
            completionist_complete = completionist_row["complete"] if completionist_row else 0

            recent_albums = [
                {"album": r["album"], "artist": r["artist"], "cover_path": r["cover_path"]}
                for r in c.execute(
                    """SELECT album, artist, MAX(rowid) as latest, MIN(path) as cover_path
                       FROM scanned
                       WHERE album IS NOT NULL AND status != 'unreadable' AND missing_since IS NULL
                       GROUP BY album, artist
                       ORDER BY latest DESC LIMIT 3"""
                ).fetchall()
            ]

        stats = {
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
            "streak": streak,
            "top_album": top_album,
            "collection_growth": collection_growth,
            "favorites_count": favorites_count,
            "this_week": this_week,
        }
        if extras:
            stats.update(
                {
                    "peak_hours": peak_hours,
                    "peak_hour": peak_hour,
                    "week_vs_last": {"this_week": this_week_plays, "last_week": last_week_plays},
                    "unplayed_count": unplayed_count,
                    "format_breakdown": format_breakdown,
                    "best_streak": best_streak,
                    "completionist_albums": {
                        "complete": completionist_complete,
                        "total": completionist_total,
                    },
                    "recent_albums": recent_albums,
                }
            )
        return stats
