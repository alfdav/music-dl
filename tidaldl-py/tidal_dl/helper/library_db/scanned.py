"""Scanned-track ledger CRUD, ISRC helpers, and album assessments."""

import hashlib
import json
import os

from tidal_dl.helper.library_db._common import *

_IDENTITY_FIELDS = (
    "file_size",
    "file_mtime",
    "file_inode",
    "file_device",
    "duration",
    "codec",
    "title",
    "artist",
    "album",
)


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
        keys = library_path_lookup_keys(path)
        placeholders = ", ".join("?" * len(keys))
        row = self._conn.execute(
            f"SELECT 1 FROM scanned WHERE path IN ({placeholders}) LIMIT 1",
            keys,
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
        """Return full cached metadata for a single path, or None.

        The exact string is tried first, then the NFC and NFD spellings.
        """
        assert self._conn
        for key in library_path_lookup_keys(path):
            row = self._conn.execute("SELECT * FROM scanned WHERE path = ?", (key,)).fetchone()
            if row:
                return dict(row)
        return None

    def tracks_by_isrc(self, isrc: str, *, include_missing: bool = False) -> list[dict]:
        """Return all scanned rows for one ISRC."""
        assert self._conn
        from tidal_dl.helper.library_scanner import visible_scanned_path_sql

        missing_sql = "" if include_missing else "AND missing_since IS NULL"
        rows = self._conn.execute(
            f"""SELECT * FROM scanned
                WHERE isrc = ? AND status != 'unreadable'
                  {missing_sql}
                  AND {visible_scanned_path_sql()}
                ORDER BY path ASC""",
            (isrc,),
        ).fetchall()
        return [dict(r) for r in rows]

    def primary_live_path_for_isrc(self, isrc: str) -> str | None:
        """Return a library-playable path for *isrc*, or None.

        Same-folder tag-scan recovery is not enough: search / playlist
        lookup only resolve indexed live ``tracks_by_isrc`` files. A
        recovered sibling counts as live only when that same check
        would accept it.
        """
        from tidal_dl.helper.recording_identity import playable_library_row_for_isrc

        row = playable_library_row_for_isrc(self, isrc)
        return row["path"] if row else None

    def has_live_isrc(self, isrc: str) -> bool:
        return self.primary_live_path_for_isrc(isrc) is not None

    def primary_path_for_isrc(self, isrc: str) -> str | None:
        if not isrc:
            return None
        live = self.primary_live_path_for_isrc(isrc)
        if live:
            return live
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
            where += (
                " AND fold_search("
                "coalesce(title, '') || ' ' || coalesce(artist, '') || ' ' || coalesce(album, '')"
                ") LIKE ?"
            )
            params.append(f"%{fold_search_text(query)}%")

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
        file_inode = sqlite_int64(file_inode)
        file_device = sqlite_int64(file_device)
        path = self._adopt_stored_path(path)
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
        keys = library_path_lookup_keys(path)
        placeholders = ", ".join("?" * len(keys))
        self._conn.execute(f"DELETE FROM scanned WHERE path IN ({placeholders})", keys)

    def collapse_unicode_path_twins(self) -> int:
        """Collapse genuine twin rows. A single stored spelling is left alone.

        When exactly one twin is on disk, that spelling is kept. When both
        exist, or neither does, the NFC spelling is kept if it is one of the
        stored paths. This does not rename files.
        """
        assert self._conn
        paths = [row["path"] for row in self._conn.execute("SELECT path FROM scanned")]
        groups: dict[str, list[str]] = {}
        for path in paths:
            groups.setdefault(canonical_library_path(path), []).append(path)

        removed = 0
        for nfc, members in groups.items():
            unique = list(dict.fromkeys(members))
            if len(unique) == 1:
                continue
            keeper = self._twin_keeper(unique, nfc)
            for other in unique:
                if other == keeper:
                    continue
                self._merge_library_path(other, keeper)
                removed += 1
        return removed

    def _twin_keeper(self, unique: list[str], nfc: str) -> str:
        present = [path for path in unique if os.path.isfile(path)]
        if len(present) == 1:
            return present[0]
        if nfc in unique:
            return nfc
        return unique[0]

    def _adopt_stored_path(self, path: str) -> str:
        """Fold any other spelling onto the path the caller gave."""
        nfc, nfd = library_path_forms(path)
        for other in (nfc, nfd):
            if other == path:
                continue
            other_row = self._conn.execute(
                "SELECT 1 FROM scanned WHERE path = ?", (other,)
            ).fetchone()
            if not other_row:
                continue
            occupant = self._conn.execute(
                "SELECT 1 FROM scanned WHERE path = ?", (path,)
            ).fetchone()
            if occupant:
                self._merge_library_path(other, path)
            else:
                self._rekey_library_path(other, path)
        return path

    def _rekey_library_path(self, old: str, new: str) -> None:
        if old == new:
            return
        self._conn.execute("UPDATE scanned SET path = ? WHERE path = ?", (new, old))
        self._conn.execute("UPDATE play_events SET path = ? WHERE path = ?", (new, old))
        self._rewrite_favorite_path(old, new)

    def _merge_library_path(self, drop: str, keep: str) -> None:
        if drop == keep:
            return
        drop_row = self._conn.execute(
            "SELECT play_count, last_played FROM scanned WHERE path = ?", (drop,)
        ).fetchone()
        keep_row = self._conn.execute(
            "SELECT play_count, last_played FROM scanned WHERE path = ?", (keep,)
        ).fetchone()
        if drop_row and keep_row:
            plays = int(keep_row["play_count"] or 0) + int(drop_row["play_count"] or 0)
            last_values = [value for value in (keep_row["last_played"], drop_row["last_played"]) if value]
            last = max(last_values) if last_values else None
            self._conn.execute(
                "UPDATE scanned SET play_count = ?, last_played = ? WHERE path = ?",
                (plays, last, keep),
            )
        self._conn.execute("UPDATE play_events SET path = ? WHERE path = ?", (keep, drop))
        self._rewrite_favorite_path(drop, keep)
        self._conn.execute("DELETE FROM scanned WHERE path = ?", (drop,))

    def _rewrite_favorite_path(self, old: str, new: str) -> None:
        keep_fav = self._conn.execute(
            "SELECT id FROM favorites WHERE path = ?", (new,)
        ).fetchone()
        if keep_fav:
            self._conn.execute("DELETE FROM favorites WHERE path = ?", (old,))
            return
        self._conn.execute("UPDATE favorites SET path = ? WHERE path = ?", (new, old))

    def _apply_identity(
        self,
        path: str,
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
    ) -> None:
        self._conn.execute(
            """UPDATE scanned SET
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
                file_size, file_mtime, file_inode, file_device,
                duration, codec, title, artist, album, path,
            ),
        )

    def _identity_supplied(self, fields: dict) -> bool:
        return any(fields.get(name) is not None for name in _IDENTITY_FIELDS)

    def _retarget_same_key(self, old_stored: str, target: str, **fields) -> bool:
        """Rewrite one canonical row onto *target* without treating it as a move."""
        if old_stored == target and not self._identity_supplied(fields):
            return True
        occupant = self._conn.execute(
            "SELECT path FROM scanned WHERE path = ?", (target,)
        ).fetchone()
        if occupant is not None and occupant["path"] != old_stored:
            self._merge_library_path(old_stored, target)
        elif old_stored != target:
            self._rekey_library_path(old_stored, target)
        self._apply_identity(target, **fields)
        return True

    def align_stored_paths(self, on_disk_by_key: dict[str, str], identities: dict[str, dict], key_of) -> int:
        """Point stored rows at the listed on-disk spelling and fill empty identity.

        *on_disk_by_key* maps the caller's comparison key to a path the walk
        returned. Filesystem reads stay with the caller; this method only
        writes rows.
        """
        assert self._conn
        rows = list(self._conn.execute("SELECT path, file_size, file_inode FROM scanned"))
        changed = 0
        with self.write_transaction():
            for row in rows:
                actual = on_disk_by_key.get(key_of(row["path"]))
                if not actual:
                    continue
                needs_path = row["path"] != actual
                needs_identity = row["file_size"] is None or row["file_inode"] is None
                if not needs_path and not needs_identity:
                    continue
                fields = {name: (identities.get(actual) or {}).get(name) for name in _IDENTITY_FIELDS}
                if self.migrate_path(row["path"], actual, **fields):
                    changed += 1
        return changed

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
        merge: bool = False,
    ) -> bool:
        """Move a scanned row and its path-keyed user data to the exact *new_path*.

        Same-canonical spelling changes stay on this row. An unchanged path
        with no identity fields does not write. Distinct paths still refuse a
        favorite collision unless *merge* is set.
        """
        assert self._conn
        file_inode = sqlite_int64(file_inode)
        file_device = sqlite_int64(file_device)
        target = new_path
        fields = {
            "file_size": file_size,
            "file_mtime": file_mtime,
            "file_inode": file_inode,
            "file_device": file_device,
            "duration": duration,
            "codec": codec,
            "title": title,
            "artist": artist,
            "album": album,
        }
        old_nfc, old_nfd = library_path_forms(old_path)
        new_nfc, new_nfd = library_path_forms(new_path)
        old_row = self.get(old_path)
        if old_row is None:
            return False
        old_stored = old_row["path"]
        if old_nfc == new_nfc:
            return self._retarget_same_key(old_stored, target, **fields)
        existing_new = self.get(target)
        if existing_new is not None and existing_new["path"] != old_stored:
            if not merge:
                return False
            keep = existing_new["path"]
            self._merge_library_path(old_stored, keep)
            if keep != target:
                self._rekey_library_path(keep, target)
                keep = target
            self._apply_identity(keep, **fields)
            return True
        dest_keys = tuple(dict.fromkeys((target, new_nfc, new_nfd)))
        placeholders = ", ".join("?" * len(dest_keys))
        favorite_collision = self._conn.execute(
            f"SELECT 1 FROM favorites WHERE path IN ({placeholders})",
            dest_keys,
        ).fetchone()
        if favorite_collision and not merge:
            return False
        if favorite_collision and merge:
            self._rewrite_favorite_path(old_stored, target)
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
                target, file_size, file_mtime, file_inode, file_device,
                duration, codec, title, artist, album, old_stored,
            ),
        )
        if cursor.rowcount != 1:
            return False
        old_keys = tuple(dict.fromkeys((old_stored, old_nfc, old_nfd)))
        old_placeholders = ", ".join("?" * len(old_keys))
        self._conn.execute(
            f"UPDATE favorites SET path = ? WHERE path IN ({old_placeholders})",
            (target, *old_keys),
        )
        self._conn.execute(
            f"UPDATE play_events SET path = ? WHERE path IN ({old_placeholders})",
            (target, *old_keys),
        )
        return True

    def backfill_file_identity(self, updates: list[tuple]) -> int:
        """Fill NULL file identity in batches. Inode and device are signed int64."""
        assert self._conn
        if not updates:
            return 0
        converted = [
            (size, mtime, sqlite_int64(inode), sqlite_int64(device), path)
            for size, mtime, inode, device, path in updates
        ]
        for offset in range(0, len(converted), 200):
            with self.write_transaction():
                self._conn.executemany(
                    """UPDATE scanned SET file_size = ?, file_mtime = ?,
                           file_inode = ?, file_device = ?
                       WHERE path = ? AND file_size IS NULL""",
                    converted[offset:offset + 200],
                )
        return len(converted)

    def mark_missing(self, path: str, *, since: int | None = None) -> None:
        assert self._conn
        ts = int(since if since is not None else time.time())
        keys = library_path_lookup_keys(path)
        placeholders = ", ".join("?" * len(keys))
        self._conn.execute(
            f"UPDATE scanned SET missing_since = ? WHERE path IN ({placeholders}) AND missing_since IS NULL",
            (ts, *keys),
        )

    def clear_missing(self, path: str) -> None:
        assert self._conn
        keys = library_path_lookup_keys(path)
        placeholders = ", ".join("?" * len(keys))
        self._conn.execute(
            f"UPDATE scanned SET missing_since = NULL WHERE path IN ({placeholders})",
            keys,
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
