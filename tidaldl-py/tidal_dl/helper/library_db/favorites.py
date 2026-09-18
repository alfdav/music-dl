"""Favorites persistence."""

from tidal_dl.helper.library_db._common import *


class FavoritesMixin:
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
            path = canonical_library_path(path)
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
            self._conn.execute(
                "DELETE FROM favorites WHERE path = ?",
                (canonical_library_path(path),),
            )
        elif tidal_id:
            self._conn.execute("DELETE FROM favorites WHERE tidal_id = ?", (tidal_id,))

    def is_favorite(self, *, path: str | None = None, tidal_id: int | None = None) -> bool:
        """Check if a track is favorited."""
        assert self._conn
        if path:
            return self._conn.execute(
                "SELECT 1 FROM favorites WHERE path = ?",
                (canonical_library_path(path),),
            ).fetchone() is not None
        if tidal_id:
            return self._conn.execute(
                "SELECT 1 FROM favorites WHERE tidal_id = ?", (tidal_id,)
            ).fetchone() is not None
        return False

    def all_favorites(self) -> list[dict]:
        """Return all favorites ordered by most recent first, enriched with scanned metadata."""
        assert self._conn
        rows = self._conn.execute(
            """SELECT f.*,
                      s.quality  AS scanned_quality,
                      s.duration AS scanned_duration,
                      s.format   AS scanned_format,
                      s.codec    AS scanned_codec,
                      s.art_available AS scanned_art_available
               FROM favorites f
               LEFT JOIN scanned s ON s.path = f.path
               ORDER BY f.favorited_at DESC"""
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
