"""Album and artist browsing queries."""

from tidal_dl.helper.library_db._common import *  # noqa: F403
from tidal_dl.helper.library_scanner import visible_scanned_path_sql


class BrowseMixin:
    def artists_page(
        self,
        limit: int = 50,
        offset: int = 0,
        query: str = "",
        ) -> tuple[list[dict], int]:
        """Return paginated artists with track/album counts."""
        assert self._conn
        where = (
            f"status != 'unreadable' AND missing_since IS NULL "
            f"AND artist IS NOT NULL AND {visible_scanned_path_sql()}"
        )
        params: list = []
        if query:
            where += " AND artist LIKE ?"
            params.append(f"%{query}%")

        total = self._conn.execute(
            f"SELECT COUNT(DISTINCT artist) FROM scanned WHERE {where}", params
        ).fetchone()[0]

        rows = self._conn.execute(
            f"""SELECT s.artist, COUNT(*) as track_count,
                       COUNT(DISTINCT album) as album_count,
                       MIN(s.path) as cover_path,
                       (SELECT s2.art_available FROM scanned s2
                        WHERE s2.artist = s.artist AND s2.status != 'unreadable'
                          AND s2.missing_since IS NULL
                          AND {visible_scanned_path_sql("s2.path")}
                        ORDER BY s2.path ASC LIMIT 1) as cover_art_available
                FROM scanned s
                WHERE {where}
                GROUP BY artist
                ORDER BY artist COLLATE NOCASE ASC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total

    def stamped_album_gallery(self) -> list[dict]:
        """Build gallery rows from stamped release ids without loading SELECT *."""
        assert self._conn
        grouped: dict[str, dict] = {}
        for row in self._conn.execute(
            f"""SELECT release_id, album, artist, title, path, art_available, quality
               FROM scanned
               WHERE status != 'unreadable' AND missing_since IS NULL
                 AND album IS NOT NULL
                 AND release_id IS NOT NULL
                 AND {visible_scanned_path_sql()}"""
        ):
            card = grouped.setdefault(row["release_id"], {
                "id": row["release_id"],
                "members": set(),
                "artists": set(),
                "track_keys": set(),
                "cover_path": None,
                "cover_art_available": None,
                "best_quality": "",
            })
            if row["album"]:
                card["members"].add(row["album"])
            if row["artist"]:
                card["artists"].add(row["artist"])
            card["track_keys"].add(_album_track_key({
                "title": row["title"],
                "artist": row["artist"],
            }))
            path = row["path"] or ""
            art = row["art_available"]
            current = (not bool(card["cover_art_available"]), card["cover_path"] or "")
            if card["cover_path"] is None or (not bool(art), path) < current:
                card["cover_path"] = path
                card["cover_art_available"] = art
            quality = str(row["quality"] or "")
            card["best_quality"] = max(card["best_quality"], quality)
        result = []
        for card in grouped.values():
            artists = card["artists"]
            result.append({
                "id": card["id"],
                "members": sorted(card["members"]),
                "artist": next(iter(artists)) if len(artists) == 1 else "Various Artists",
                "track_count": len(card["track_keys"]),
                "cover_path": card["cover_path"],
                "cover_art_available": card["cover_art_available"],
                "best_quality": card["best_quality"],
            })
        return result

    def all_albums(self, query: str = "") -> list[dict]:
        """Return all albums grouped by album name. Multi-artist albums show 'Various Artists'."""
        assert self._conn
        where = (
            f"album IS NOT NULL AND status != 'unreadable' "
            f"AND missing_since IS NULL AND {visible_scanned_path_sql()}"
        )
        params: list = []
        if query:
            where += " AND (album LIKE ? OR artist LIKE ?)"
            like = f"%{query}%"
            params.extend([like, like])
        rows = self._conn.execute(
            f"""SELECT s.album, COUNT(*) as track_count, MIN(s.path) as cover_path,
                       (SELECT s2.art_available FROM scanned s2
                        WHERE s2.album = s.album AND s2.status != 'unreadable'
                          AND s2.missing_since IS NULL
                          AND {visible_scanned_path_sql("s2.path")}
                        ORDER BY s2.path ASC LIMIT 1) as cover_art_available,
                       MAX(quality) as best_quality,
                       COUNT(DISTINCT artist) as artist_count,
                       MIN(artist) as first_artist
                FROM scanned s
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

    def recent_albums_page(self, limit: int = 12, offset: int = 0) -> tuple[list[dict], int]:
        """Return recent local albums, preferring download recency over scan recency.

        Albums are grouped by name only (not by artist) so compilations and
        greatest-hits collections appear as a single entry with the artist
        shown as "Various Artists" when multiple artists are present.
        """
        assert self._conn

        # Cover art is resolved later from the page's tracks. A correlated
        # cover-art subquery here scanned the path PK once per album
        # (~500ms local / ~3s on the NAS-backed Mac library).
        downloaded: dict[str, dict] = {}
        for row in self._conn.execute(
            f"""SELECT dh.album,
                      COUNT(DISTINCT s.path) AS track_count,
                      MAX(dh.finished_at) AS recent_at,
                      COUNT(DISTINCT dh.artist) AS artist_count,
                      MIN(dh.artist) AS first_artist
               FROM download_history dh
               JOIN scanned s
                 ON s.album = dh.album
               WHERE dh.status = 'done'
                 AND dh.finished_at IS NOT NULL
                 AND s.status != 'unreadable' AND s.missing_since IS NULL
                 AND {visible_scanned_path_sql("s.path")}
                 AND dh.album IS NOT NULL
               GROUP BY dh.album"""
        ).fetchall():
            artist = row["first_artist"] if row["artist_count"] == 1 else "Various Artists"
            downloaded[row["album"]] = {
                "album": row["album"],
                "artist": artist,
                "track_count": row["track_count"],
                "recent_at": int(row["recent_at"]),
                "recent_source": "download",
            }

        scanned: dict[str, dict] = {}
        for row in self._conn.execute(
            f"""SELECT album,
                      COUNT(*) AS track_count,
                      MAX(scanned_at) AS recent_at,
                      COUNT(DISTINCT artist) AS artist_count,
                      MIN(artist) AS first_artist
               FROM scanned s
               WHERE album IS NOT NULL
                 AND status != 'unreadable' AND missing_since IS NULL
                 AND {visible_scanned_path_sql()}
               GROUP BY album"""
        ).fetchall():
            artist = row["first_artist"] if row["artist_count"] == 1 else "Various Artists"
            scanned[row["album"]] = {
                "album": row["album"],
                "artist": artist,
                "track_count": row["track_count"],
                "recent_at": int(row["recent_at"]),
                "recent_source": "scan",
            }

        # Download recency wins over scan recency
        merged = dict(scanned)
        merged.update(downloaded)

        rows = sorted(
            merged.values(),
            key=lambda row: (-row["recent_at"], row["artist"].casefold(), row["album"].casefold()),
        )
        total = len(rows)
        return rows[offset:offset + limit], total

    def tracks_for_artist(self, artist: str) -> list[dict]:
        """Return readable rows for one artist without loading the whole library."""
        assert self._conn
        rows = self._conn.execute(
            f"""SELECT * FROM scanned
               WHERE status != 'unreadable' AND missing_since IS NULL
                 AND {visible_scanned_path_sql()}
                 AND artist = ? COLLATE NOCASE""",
            (artist,),
        ).fetchall()
        return [dict(r) for r in rows]

    def tracks_for_release(self, release_id: str) -> list[dict]:
        """Return readable rows already stamped with a grouped release id."""
        assert self._conn
        rows = self._conn.execute(
            f"""SELECT * FROM scanned
               WHERE status != 'unreadable' AND missing_since IS NULL
                 AND {visible_scanned_path_sql()}
                 AND release_id = ?""",
            (release_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def tracks_for_albums(self, albums: list[str]) -> list[dict]:
        """Return readable rows for a small set of album titles."""
        assert self._conn
        titles = [album for album in albums if album]
        if not titles:
            return []
        placeholders = ",".join("?" * len(titles))
        rows = self._conn.execute(
            f"""SELECT * FROM scanned
                WHERE status != 'unreadable' AND missing_since IS NULL
                  AND {visible_scanned_path_sql()}
                  AND album IN ({placeholders})""",
            titles,
        ).fetchall()
        return [dict(r) for r in rows]

    def release_stamps_complete(self) -> bool:
        """True when every readable album row already has a grouped release id."""
        assert self._conn
        row = self._conn.execute(
            f"""SELECT COUNT(*) AS album_rows,
                      SUM(CASE WHEN release_id IS NOT NULL THEN 1 ELSE 0 END) AS stamped
               FROM scanned
               WHERE status != 'unreadable' AND missing_since IS NULL AND album IS NOT NULL
                 AND {visible_scanned_path_sql()}"""
        ).fetchone()
        album_rows = int(row["album_rows"] or 0)
        stamped = int(row["stamped"] or 0)
        return album_rows > 0 and album_rows == stamped

    def albums_by_artist(self, artist: str) -> list[dict]:
        """Return albums for an artist with track count and a representative path for art."""
        assert self._conn
        rows = self._conn.execute(
            f"""SELECT s.album, COUNT(*) as track_count, MIN(s.path) as cover_path,
                      (SELECT s2.art_available FROM scanned s2
                       WHERE s2.artist = s.artist AND s2.album = s.album
                         AND s2.status != 'unreadable' AND s2.missing_since IS NULL
                         AND {visible_scanned_path_sql("s2.path")}
                       ORDER BY s2.path ASC LIMIT 1) as cover_art_available,
                      GROUP_CONCAT(DISTINCT genre) as genres,
                      MAX(quality) as best_quality
               FROM scanned s
               WHERE artist = ? AND album IS NOT NULL AND status != 'unreadable'
                 AND missing_since IS NULL
                 AND {visible_scanned_path_sql()}
               GROUP BY album ORDER BY album COLLATE NOCASE ASC""",
            (artist,),
        ).fetchall()
        return [dict(r) for r in rows]

    def album_tracks(self, artist: str, album: str) -> list[dict]:
        """Return album tracks deduplicated by normalized title+artist.

        Prefers the best-quality row for each song, then a canonical path without
        a uniquify suffix like ``_01``, then the shortest path.
        """
        assert self._conn
        if artist == "Various Artists":
            rows = self._conn.execute(
                f"""SELECT * FROM scanned
                   WHERE album = ? AND status != 'unreadable'
                     AND missing_since IS NULL
                     AND {visible_scanned_path_sql()}""",
                (album,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"""SELECT * FROM scanned
                   WHERE artist = ? AND album = ? AND status != 'unreadable'
                     AND missing_since IS NULL
                     AND {visible_scanned_path_sql()}""",
                (artist, album),
            ).fetchall()

        ordered = sorted((dict(r) for r in rows), key=_album_track_preference)
        seen: set[tuple[str, str]] = set()
        result = []
        for row in ordered:
            key = _album_track_key(row)
            if key in seen:
                continue
            seen.add(key)
            result.append(row)

        result.sort(key=lambda t: t.get("path", ""))
        return result
