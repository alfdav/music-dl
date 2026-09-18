"""edition_advice cache table + CRUD."""

import sqlite3

import pytest

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.gui.services.edition_advice_policy import fingerprint


@pytest.fixture
def db(tmp_path):
    d = LibraryDB(tmp_path / "test.db")
    d.open()
    yield d
    d.close()


class TestEditionAdviceSchema:
    def test_table_exists_after_open(self, db):
        names = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "edition_advice" in names

    def test_schema_version_is_11(self, db):
        assert LibraryDB._SCHEMA_VERSION == 11
        assert db._conn.execute("PRAGMA user_version").fetchone()[0] == 11


class TestEditionAdviceCrud:
    def _pair(self, **overrides):
        data = {
            "path_a": "/music/keeper.flac",
            "path_b": "/music/extra.flac",
            "fingerprint_a": fingerprint("/music/keeper.flac", 100, 1.0),
            "fingerprint_b": fingerprint("/music/extra.flac", 200, 2.0),
            "relation": "layout_twin_extra",
            "confidence": 0.97,
            "probabilities": {"layout_twin_extra": 0.97},
            "same_isrc_misleading": False,
            "model": "jev-test",
            "usage": {"tokens": 12},
            "error": None,
            "group_id": "isrc:US123|Album",
        }
        data.update(overrides)
        return data

    def test_upsert_and_get_pair(self, db):
        row = self._pair()
        db.upsert_edition_advice(**row)
        got = db.get_edition_advice(row["path_a"], row["path_b"])
        assert got is not None
        assert got["relation"] == "layout_twin_extra"
        assert got["confidence"] == 0.97
        assert got["group_id"] == "isrc:US123|Album"
        assert got["probabilities"]["layout_twin_extra"] == 0.97

    def test_get_pair_requires_matching_fingerprints(self, db):
        row = self._pair()
        db.upsert_edition_advice(**row)
        stale = db.get_edition_advice(
            row["path_a"],
            row["path_b"],
            fingerprint_a=fingerprint("/music/keeper.flac", 999, 1.0),
            fingerprint_b=row["fingerprint_b"],
        )
        assert stale is None
        fresh = db.get_edition_advice(
            row["path_a"],
            row["path_b"],
            fingerprint_a=row["fingerprint_a"],
            fingerprint_b=row["fingerprint_b"],
        )
        assert fresh is not None

    def test_invalidate_stale_drops_mismatched_fingerprint(self, db):
        row = self._pair()
        db.upsert_edition_advice(**row)
        db.invalidate_stale_edition_advice(
            row["path_b"], fingerprint("/music/extra.flac", 999, 9.0)
        )
        assert db.get_edition_advice(row["path_a"], row["path_b"]) is None

    def test_list_for_group(self, db):
        db.upsert_edition_advice(**self._pair())
        db.upsert_edition_advice(
            **self._pair(
                path_b="/music/other.flac",
                fingerprint_b=fingerprint("/music/other.flac", 50, 3.0),
                relation="keep_both_editions",
                confidence=0.99,
            )
        )
        db.upsert_edition_advice(
            **self._pair(
                path_a="/other/a.flac",
                path_b="/other/b.flac",
                group_id="other-group",
            )
        )
        rows = db.list_edition_advice_for_group("isrc:US123|Album")
        assert len(rows) == 2
        assert {r["path_b"] for r in rows} == {"/music/extra.flac", "/music/other.flac"}

    def test_migrate_from_legacy_user_version(self, tmp_path):
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE scanned (path TEXT PRIMARY KEY, status TEXT NOT NULL)")
        conn.execute("PRAGMA user_version = 10")
        conn.commit()
        conn.close()

        migrated = LibraryDB(db_path)
        migrated.open()
        try:
            names = {
                row[0]
                for row in migrated._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            version = migrated._conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            migrated.close()
        assert "edition_advice" in names
        assert version == 11
