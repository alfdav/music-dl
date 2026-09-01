"""Scanned-track ledger CRUD, ISRC helpers, and album assessments."""

import hashlib
import json

from tidal_dl.helper.library_db._common import *


class ScannedMixin:
    @staticmethod
    def grouping_pair_key(left_signature: str, right_signature: str) -> str:
        payload = json.dumps(
            sorted((left_signature, right_signature)),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def save_grouping_assessment(
        self,
        *,
        left_signature: str,
        right_signature: str,
        score: int,
        outcome: str,
        evidence: list[dict],
        vetoes: list[dict],
        contradictions: list[str],
        catalog: dict | None = None,
    ) -> None:
        assert self._conn
        left_signature, right_signature = sorted((left_signature, right_signature))
        pair_key = self.grouping_pair_key(left_signature, right_signature)
        encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self._conn.execute(
            """INSERT INTO album_grouping_assessments (
                   pair_key, left_signature, right_signature, score, outcome,
                   evidence_json, vetoes_json, contradictions_json, catalog_json,
                   evaluated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(pair_key) DO UPDATE SET
                   left_signature = excluded.left_signature,
                   right_signature = excluded.right_signature,
                   score = excluded.score,
                   outcome = excluded.outcome,
                   evidence_json = excluded.evidence_json,
                   vetoes_json = excluded.vetoes_json,
                   contradictions_json = excluded.contradictions_json,
                   catalog_json = CASE
                       WHEN excluded.catalog_json = '{}' THEN album_grouping_assessments.catalog_json
                       ELSE excluded.catalog_json
                   END,
                   evaluated_at = excluded.evaluated_at""",
            (
                pair_key, left_signature, right_signature, int(score), outcome,
                encode(evidence), encode(vetoes), encode(contradictions),
                encode(catalog or {}), time.time(),
            ),
        )

    def get_grouping_assessment(self, left_signature: str, right_signature: str) -> dict | None:
        assert self._conn
        row = self._conn.execute(
            "SELECT * FROM album_grouping_assessments WHERE pair_key = ?",
            (self.grouping_pair_key(left_signature, right_signature),),
        ).fetchone()
        return self._decode_assessment_row(row)

    def list_grouping_assessments(self) -> list[dict]:
        """Return every stored pair assessment without regrouping."""
        assert self._conn
        rows = self._conn.execute("SELECT * FROM album_grouping_assessments").fetchall()
        return [decoded for row in rows if (decoded := self._decode_assessment_row(row))]

    @staticmethod
    def _decode_assessment_row(row) -> dict | None:
        if not row:
            return None
        result = dict(row)
        for stored, exposed in (
            ("evidence_json", "evidence"),
            ("vetoes_json", "vetoes"),
            ("contradictions_json", "contradictions"),
            ("catalog_json", "catalog"),
        ):
            result[exposed] = json.loads(result.pop(stored))
        return result

    def set_grouping_decision(
        self,
        left_signature: str,
        right_signature: str,
        *,
        decision: str,
        canonical_title: str | None = None,
    ) -> bool:
        if decision not in {"group_together", "keep_separate"}:
            raise ValueError("Invalid grouping decision")
        assert self._conn
        cursor = self._conn.execute(
            """UPDATE album_grouping_assessments
               SET user_decision = ?, canonical_title = ?
               WHERE pair_key = ?""",
            (
                decision,
                canonical_title if decision == "group_together" else None,
                self.grouping_pair_key(left_signature, right_signature),
            ),
        )
        return cursor.rowcount == 1

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

    def identity_rows(self) -> list[dict]:
        """Return identity columns for every scanned row in one query."""
        assert self._conn
        rows = self._conn.execute(
            """SELECT path, file_size, file_mtime, file_inode, file_device,
                      duration, codec, title, artist, album, isrc, missing_since
               FROM scanned"""
        ).fetchall()
        return [dict(row) for row in rows]

    def complete_paths(self) -> set[str]:
        """Return paths that have full metadata (album, duration, quality populated)."""
        assert self._conn
        rows = self._conn.execute(
            "SELECT path FROM scanned WHERE album IS NOT NULL AND duration IS NOT NULL"
        ).fetchall()
        return {r["path"] for r in rows}

    _INCOMPLETE_IDENTITY_SQL = """
        COALESCE(metadata_complete, 0) != 1
        AND (
            NULLIF(TRIM(COALESCE(title, '')), '') IS NULL
            OR NULLIF(TRIM(COALESCE(artist, '')), '') IS NULL
            OR NULLIF(TRIM(COALESCE(album, '')), '') IS NULL
            OR lower(TRIM(artist)) = 'unknown artist'
            OR lower(TRIM(album)) = 'unknown album'
            OR lower(TRIM(title)) LIKE 'track %'
        )
    """

    def stamp_complete_identity_rows(self) -> int:
        """Mark tagged identity as complete without opening audio files."""
        assert self._conn
        with self.write_transaction():
            cursor = self._conn.execute(
                """UPDATE scanned SET metadata_complete = 1
                   WHERE COALESCE(metadata_complete, 0) != 1
                     AND NULLIF(TRIM(title), '') IS NOT NULL
                     AND NULLIF(TRIM(artist), '') IS NOT NULL
                     AND NULLIF(TRIM(album), '') IS NOT NULL
                     AND lower(TRIM(artist)) != 'unknown artist'
                     AND lower(TRIM(album)) != 'unknown album'
                     AND lower(TRIM(title)) NOT LIKE 'track %'"""
            )
            return int(cursor.rowcount or 0)

    def metadata_repair_worklist(self) -> list[dict]:
        """Return cached rows that still have placeholder or missing identity.

        Rows that are already tagged with a real artist/title/album are not
        inspected again, even if a schema migration left ``metadata_complete``
        at 0 or ``codec`` is NULL. Skipped-directory paths stay out of the
        worklist so repair never opens ``#recycle`` files.
        """
        assert self._conn
        from tidal_dl.helper.library_scanner import path_has_skipped_scan_dir

        rows = self._conn.execute(
            f"""SELECT * FROM scanned
               WHERE {self._INCOMPLETE_IDENTITY_SQL}
               ORDER BY path ASC"""
        ).fetchall()
        return [
            dict(row) for row in rows
            if not path_has_skipped_scan_dir(row["path"])
        ]

    def get(self, path: str) -> dict | None:
        """Return full cached metadata for a single path, or None."""
        assert self._conn
        row = self._conn.execute("SELECT * FROM scanned WHERE path = ?", (path,)).fetchone()
        if not row:
            return None
        return dict(row)

    def tracks_by_isrc(self, isrc: str) -> list[dict]:
        """Return all scanned rows for one ISRC."""
        assert self._conn
        from tidal_dl.helper.library_scanner import visible_scanned_path_sql

        rows = self._conn.execute(
            f"""SELECT * FROM scanned
                WHERE isrc = ? AND status != 'unreadable'
                  AND missing_since IS NULL
                  AND {visible_scanned_path_sql()}
                ORDER BY path ASC""",
            (isrc,),
        ).fetchall()
        return [dict(r) for r in rows]

    def has_live_isrc(self, isrc: str) -> bool:
        if not isrc:
            return False
        for row in self.tracks_by_isrc(isrc):
            if pathlib.Path(row["path"]).is_file():
                return True
        return False

    def primary_path_for_isrc(self, isrc: str) -> str | None:
        if not isrc:
            return None
        fallback: str | None = None
        for row in self.tracks_by_isrc(isrc):
            path = row["path"]
            fallback = fallback or path
            if pathlib.Path(path).is_file():
                return path
        return fallback

    def register_isrc_path(self, isrc: str, path: str | pathlib.Path, *, commit: bool = False) -> None:
        if not isrc or not path:
            return
        path_str = str(pathlib.Path(path).resolve())
        self.record(path=path_str, status="downloaded", isrc=isrc)
        if commit:
            self.commit()

    def isrc_entry_count(self) -> int:
        assert self._conn
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT isrc) FROM scanned WHERE isrc IS NOT NULL AND isrc != ''"
        ).fetchone()
        return int(row[0] if row else 0)

    def import_legacy_isrc_index(self, json_path: pathlib.Path) -> int:
        """One-time import from legacy isrc_index.json. Returns rows imported."""
        import json

        if not json_path.is_file():
            return 0
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        if not isinstance(payload, dict):
            return 0
        imported = 0
        for isrc, path_str in payload.items():
            if not isrc or not path_str:
                continue
            if not pathlib.Path(path_str).is_file():
                continue
            self.register_isrc_path(str(isrc), path_str)
            imported += 1
        if imported:
            self.commit()
            try:
                json_path.rename(json_path.with_suffix(".json.migrated"))
            except OSError:
                pass
        return imported

    def all_tracks(self) -> list[dict]:
        """Return all cached tracks with status != 'unreadable'."""
        assert self._conn
        from tidal_dl.helper.library_scanner import visible_scanned_path_sql

        rows = self._conn.execute(
            f"SELECT * FROM scanned WHERE status != 'unreadable' "
            f"AND missing_since IS NULL AND {visible_scanned_path_sql()}"
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
            "plays": "play_count DESC, last_played DESC",
            "random": "RANDOM()",
        }
        order = sort_map.get(sort, sort_map["artist"])

        from tidal_dl.helper.library_scanner import visible_scanned_path_sql

        where = (
            f"status != 'unreadable' AND missing_since IS NULL "
            f"AND {visible_scanned_path_sql()}"
        )
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

    def record(
        self,
        path: str,
        *,
        status: str,
        isrc: str | None = None,
        artist: str | None = None,
        title: str | None = None,
        album: str | None = None,
        album_artist: str | None = None,
        release_date: str | None = None,
        track_number: int | None = None,
        track_total: int | None = None,
        disc_number: int | None = None,
        disc_total: int | None = None,
        musicbrainz_release_id: str | None = None,
        musicbrainz_release_group_id: str | None = None,
        provider_namespace: str | None = None,
        provider_album_id: str | None = None,
        barcode: str | None = None,
        duration: int | None = None,
        quality: str | None = None,
        fmt: str | None = None,
        genre: str | None = None,
        waveform: str | None = None,
        waveform_hires: str | None = None,
        art_available: bool | None = None,
        codec: str | None = None,
        metadata_complete: bool | None = None,
        file_size: int | None = None,
        file_mtime: int | None = None,
        file_inode: int | None = None,
        file_device: int | None = None,
    ) -> None:
        """Insert or update a scan result."""
        assert self._conn
        now = time.time()
        self._conn.execute(
            """INSERT INTO scanned (path, isrc, status, artist, title, album,
                                    album_artist, release_date, track_number,
                                    track_total, disc_number, disc_total,
                                    musicbrainz_release_id,
                                    musicbrainz_release_group_id,
                                    provider_namespace, provider_album_id, barcode,
                                    duration, quality, format, genre, waveform,
                                    waveform_hires, art_available, codec,
                                    metadata_complete, file_size, file_mtime,
                                    file_inode, file_device, missing_since, scanned_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
               ON CONFLICT(path) DO UPDATE SET
                   isrc = excluded.isrc,
                   status = excluded.status,
                   artist = excluded.artist,
                   title = excluded.title,
                   album = excluded.album,
                   album_artist = excluded.album_artist,
                   release_date = excluded.release_date,
                   track_number = excluded.track_number,
                   track_total = excluded.track_total,
                   disc_number = excluded.disc_number,
                   disc_total = excluded.disc_total,
                   musicbrainz_release_id = excluded.musicbrainz_release_id,
                   musicbrainz_release_group_id = excluded.musicbrainz_release_group_id,
                   provider_namespace = excluded.provider_namespace,
                   provider_album_id = excluded.provider_album_id,
                   barcode = excluded.barcode,
                   duration = excluded.duration,
                   quality = excluded.quality,
                   format = excluded.format,
                   genre = excluded.genre,
                   waveform = COALESCE(excluded.waveform, scanned.waveform),
                   waveform_hires = COALESCE(excluded.waveform_hires, scanned.waveform_hires),
                   art_available = COALESCE(excluded.art_available, scanned.art_available),
                   codec = COALESCE(excluded.codec, scanned.codec),
                   metadata_complete = COALESCE(
                       excluded.metadata_complete, scanned.metadata_complete
                   ),
                   file_size = COALESCE(excluded.file_size, scanned.file_size),
                   file_mtime = COALESCE(excluded.file_mtime, scanned.file_mtime),
                   file_inode = COALESCE(excluded.file_inode, scanned.file_inode),
                   file_device = COALESCE(excluded.file_device, scanned.file_device),
                   missing_since = NULL,
                   scanned_at = excluded.scanned_at""",
            (
                path, isrc, status, artist, title, album, album_artist,
                release_date, track_number, track_total, disc_number, disc_total,
                musicbrainz_release_id, musicbrainz_release_group_id,
                provider_namespace, provider_album_id, barcode, duration, quality,
                fmt, genre, waveform, waveform_hires, art_available, codec,
                metadata_complete, file_size, file_mtime, file_inode, file_device,
                now,
            ),
        )

    def clear_release_ids(self) -> None:
        """Drop stamped release ids before a full-library regroup."""
        assert self._conn
        self._conn.execute("UPDATE scanned SET release_id = NULL")

    def stamp_release_ids(self, cards: list[dict]) -> None:
        """Remember which scanned rows belong to each grouped release card."""
        assert self._conn
        updates = [
            (card["id"], row["path"])
            for card in cards
            for row in card.get("tracks") or []
            if row.get("path")
        ]
        if updates:
            self._conn.executemany(
                "UPDATE scanned SET release_id = ? WHERE path = ?",
                updates,
            )

    def remove(self, path: str) -> None:
        """Remove a path from the ledger (e.g. file deleted)."""
        assert self._conn
        self._conn.execute("DELETE FROM scanned WHERE path = ?", (path,))

    def migrate_path(
        self,
        old_path: str,
        new_path: str,
        *,
        file_size: int | None = None,
        file_mtime: int | None = None,
        file_inode: int | None = None,
        file_device: int | None = None,
        duration: int | None = None,
        codec: str | None = None,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
    ) -> bool:
        """Move a scanned row and its path-keyed user data to *new_path*."""
        assert self._conn
        if old_path == new_path:
            return True
        if self.get(new_path) is not None:
            return False
        favorite_collision = self._conn.execute(
            "SELECT 1 FROM favorites WHERE path = ?", (new_path,)
        ).fetchone()
        if favorite_collision:
            return False
        cursor = self._conn.execute(
            """UPDATE scanned SET
                   path = ?,
                   file_size = COALESCE(?, file_size),
                   file_mtime = COALESCE(?, file_mtime),
                   file_inode = COALESCE(?, file_inode),
                   file_device = COALESCE(?, file_device),
                   duration = COALESCE(?, duration),
                   codec = COALESCE(?, codec),
                   title = COALESCE(?, title),
                   artist = COALESCE(?, artist),
                   album = COALESCE(?, album),
                   missing_since = NULL
               WHERE path = ?""",
            (
                new_path, file_size, file_mtime, file_inode, file_device,
                duration, codec, title, artist, album, old_path,
            ),
        )
        if cursor.rowcount != 1:
            return False
        self._conn.execute(
            "UPDATE favorites SET path = ? WHERE path = ?",
            (new_path, old_path),
        )
        self._conn.execute(
            "UPDATE play_events SET path = ? WHERE path = ?",
            (new_path, old_path),
        )
        return True

    def mark_missing(self, path: str, *, since: int | None = None) -> None:
        assert self._conn
        ts = int(since if since is not None else time.time())
        self._conn.execute(
            "UPDATE scanned SET missing_since = ? WHERE path = ? AND missing_since IS NULL",
            (ts, path),
        )

    def clear_missing(self, path: str) -> None:
        assert self._conn
        self._conn.execute(
            "UPDATE scanned SET missing_since = NULL WHERE path = ?",
            (path,),
        )

    def missing_rows(self) -> list[dict]:
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM scanned WHERE missing_since IS NOT NULL ORDER BY path ASC"
        ).fetchall()
        return [dict(row) for row in rows]

    def rows_in_directory(self, directory: str) -> list[dict]:
        """Return rows whose immediate parent directory is *directory*."""
        assert self._conn
        parent = pathlib.Path(directory)
        like = str(parent / "%")
        rows = self._conn.execute(
            "SELECT * FROM scanned WHERE path LIKE ?", (like,)
        ).fetchall()
        return [dict(row) for row in rows if pathlib.Path(row["path"]).parent == parent]

    def rows_under_directory(self, directory: str) -> list[dict]:
        """Return rows stored under *directory*, including nested folders."""
        assert self._conn
        parent = pathlib.Path(directory)
        like = str(parent / "%")
        rows = self._conn.execute(
            "SELECT * FROM scanned WHERE path LIKE ?", (like,)
        ).fetchall()
        result = []
        for row in rows:
            try:
                if pathlib.Path(row["path"]).is_relative_to(parent):
                    result.append(dict(row))
            except (ValueError, OSError):
                continue
        return result

    def dir_signatures(self) -> dict[str, str]:
        assert self._conn
        rows = self._conn.execute("SELECT dir, signature FROM scanned_dirs").fetchall()
        return {row["dir"]: row["signature"] for row in rows}

    def touch_dir_signatures(self, directories: list[str], *, checked_at: int) -> None:
        assert self._conn
        self._conn.executemany(
            "UPDATE scanned_dirs SET checked_at = ? WHERE dir = ?",
            [(checked_at, directory) for directory in directories],
        )

    def replace_dir_signatures(
        self,
        signatures: dict[str, str],
        *,
        checked_at: int,
        keep_dirs: set[str] | None = None,
    ) -> None:
        """Upsert current signatures and drop vanished readable directories."""
        assert self._conn
        keep = set(keep_dirs or ())
        keep.update(signatures)
        stored = {row["dir"] for row in self._conn.execute("SELECT dir FROM scanned_dirs")}
        stale = stored - keep
        if stale:
            self._conn.executemany(
                "DELETE FROM scanned_dirs WHERE dir = ?",
                [(directory,) for directory in stale],
            )
        if signatures:
            self._conn.executemany(
                """INSERT INTO scanned_dirs (dir, signature, checked_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(dir) DO UPDATE SET
                       signature = excluded.signature,
                       checked_at = excluded.checked_at""",
                [(directory, signature, checked_at) for directory, signature in signatures.items()],
            )

    def commit(self) -> None:
        assert self._conn
        self._conn.commit()
