"""Cached TypeSafe/Jev edition-advice pairs."""

from __future__ import annotations

import json

from tidal_dl.helper.library_db._common import *


def _row_to_advice(row) -> dict:
    data = dict(row)
    raw_probs = data.pop("probabilities_json", None)
    raw_usage = data.pop("usage_json", None)
    try:
        data["probabilities"] = json.loads(raw_probs) if raw_probs else None
    except json.JSONDecodeError:
        data["probabilities"] = None
    try:
        data["usage"] = json.loads(raw_usage) if raw_usage else None
    except json.JSONDecodeError:
        data["usage"] = None
    data["same_isrc_misleading"] = bool(data.get("same_isrc_misleading"))
    return data


class EditionAdviceMixin:
    def get_edition_advice(
        self,
        path_a: str,
        path_b: str,
        *,
        fingerprint_a: str | None = None,
        fingerprint_b: str | None = None,
    ) -> dict | None:
        """Return a cached pair, or None if missing or fingerprints mismatch."""
        assert self._conn
        row = self._conn.execute(
            "SELECT * FROM edition_advice WHERE path_a = ? AND path_b = ?",
            (path_a, path_b),
        ).fetchone()
        if not row:
            return None
        if fingerprint_a is not None and row["fingerprint_a"] != fingerprint_a:
            return None
        if fingerprint_b is not None and row["fingerprint_b"] != fingerprint_b:
            return None
        return _row_to_advice(row)

    def upsert_edition_advice(
        self,
        *,
        path_a: str,
        path_b: str,
        fingerprint_a: str,
        fingerprint_b: str,
        relation: str | None = None,
        confidence: float | None = None,
        probabilities: dict | None = None,
        same_isrc_misleading: bool | None = None,
        model: str | None = None,
        usage: dict | None = None,
        error: str | None = None,
        group_id: str | None = None,
        scored_at: float | None = None,
    ) -> None:
        assert self._conn
        now = time.time() if scored_at is None else scored_at
        misleading = None if same_isrc_misleading is None else int(bool(same_isrc_misleading))
        self._conn.execute(
            """INSERT INTO edition_advice (
                   path_a, path_b, fingerprint_a, fingerprint_b, relation, confidence,
                   probabilities_json, same_isrc_misleading, model, usage_json,
                   scored_at, error, group_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(path_a, path_b) DO UPDATE SET
                   fingerprint_a = excluded.fingerprint_a,
                   fingerprint_b = excluded.fingerprint_b,
                   relation = excluded.relation,
                   confidence = excluded.confidence,
                   probabilities_json = excluded.probabilities_json,
                   same_isrc_misleading = excluded.same_isrc_misleading,
                   model = excluded.model,
                   usage_json = excluded.usage_json,
                   scored_at = excluded.scored_at,
                   error = excluded.error,
                   group_id = excluded.group_id""",
            (
                path_a,
                path_b,
                fingerprint_a,
                fingerprint_b,
                relation,
                confidence,
                json.dumps(probabilities) if probabilities is not None else None,
                misleading,
                model,
                json.dumps(usage) if usage is not None else None,
                now,
                error,
                group_id,
            ),
        )
        self._conn.commit()

    def invalidate_stale_edition_advice(self, path: str, fingerprint: str) -> int:
        """Delete cached rows for ``path`` whose stored fingerprint differs."""
        assert self._conn
        cur = self._conn.execute(
            """DELETE FROM edition_advice
               WHERE (path_a = ? AND fingerprint_a != ?)
                  OR (path_b = ? AND fingerprint_b != ?)""",
            (path, fingerprint, path, fingerprint),
        )
        self._conn.commit()
        return cur.rowcount

    def list_edition_advice_for_group(self, group_id: str) -> list[dict]:
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM edition_advice WHERE group_id = ?",
            (group_id,),
        ).fetchall()
        return [_row_to_advice(r) for r in rows]
