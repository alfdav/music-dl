"""Stored walk paths can mix NFC and NFD across segments (Bugbot #212)."""

from __future__ import annotations

import unicodedata

from tidal_dl.helper.library_db import LibraryDB

ROOT_NFC = unicodedata.normalize("NFC", "/lib/Café Tacvba")
ALBUM_NFD = unicodedata.normalize("NFD", "Ré")
FILE_NFD = unicodedata.normalize("NFD", "Éste.flac")
MIXED = f"{ROOT_NFC}/{ALBUM_NFD}/{FILE_NFD}"
NFC = unicodedata.normalize("NFC", MIXED)
NFD = unicodedata.normalize("NFD", MIXED)


def _db(tmp_path):
    db = LibraryDB(tmp_path / "lib.db")
    db.open()
    db.record(MIXED, status="tagged", title="t", artist="a")
    db.commit()
    return db


def test_mixed_spelling_is_neither_pure_form():
    assert MIXED not in (NFC, NFD)


def test_get_and_is_known_find_mixed_row(tmp_path):
    db = _db(tmp_path)
    for probe in (NFC, NFD, MIXED):
        row = db.get(probe)
        assert row is not None and row["path"] == MIXED
        assert db.is_known(probe)


def test_mark_and_clear_missing_hit_mixed_row(tmp_path):
    db = _db(tmp_path)
    db.mark_missing(NFC, since=123)
    assert db.get(MIXED)["missing_since"] == 123
    db.clear_missing(NFD)
    assert db.get(MIXED)["missing_since"] is None


def test_record_does_not_insert_second_row(tmp_path):
    db = _db(tmp_path)
    db.record(NFC, status="tagged", title="t", artist="a")
    db.commit()
    paths = [p for p in db.known_paths() if unicodedata.normalize("NFC", p) == NFC]
    assert paths == [NFC]


def test_remove_deletes_mixed_row(tmp_path):
    db = _db(tmp_path)
    db.remove(NFD)
    assert db.get(MIXED) is None


ACCENT_ROOT = unicodedata.normalize("NFC", "/Músic")


def test_accented_root_lookup_uses_path_key_index(tmp_path):
    db = LibraryDB(tmp_path / "lib.db")
    db.open()
    for n in range(200):
        db.record(f"{ACCENT_ROOT}/a{n}/t.flac", status="tagged", title="t", artist="a")
    db.record(MIXED, status="tagged", title="t", artist="a")
    db.commit()
    plan = " ".join(
        str(tuple(r))
        for r in db._conn.execute(
            "EXPLAIN QUERY PLAN SELECT path FROM scanned WHERE path_key = ? OR path = ?",
            (NFC, NFC),
        )
    )
    assert "idx_scanned_path_key" in plan
    assert "SCAN scanned" not in plan
    probe = unicodedata.normalize("NFD", f"{ACCENT_ROOT}/a7/t.flac")
    assert db.get(probe)["path"] == f"{ACCENT_ROOT}/a7/t.flac"
    assert db.get(NFD)["path"] == MIXED


def test_path_key_follows_rekey(tmp_path):
    db = _db(tmp_path)
    db.record(NFC, status="tagged", title="t", artist="a")
    db.commit()
    row = db._conn.execute("SELECT path, path_key FROM scanned").fetchall()
    assert [tuple(r) for r in row] == [(NFC, NFC)]


def test_favorite_toggle_with_mixed_stored_path(tmp_path):
    db = _db(tmp_path)
    db.add_favorite(path=NFC, title="t", artist="a")
    db.commit()
    stored = db._conn.execute("SELECT path FROM favorites").fetchone()["path"]
    assert stored == MIXED
    for probe in (NFC, NFD, MIXED):
        assert db.is_favorite(path=probe)
    db.add_favorite(path=NFD, title="t", artist="a")
    assert db._conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0] == 1
    db.remove_favorite(path=NFC)
    assert not db.is_favorite(path=MIXED)


def test_v11_database_backfills_path_key(tmp_path):
    db = _db(tmp_path)
    db.add_favorite(path=MIXED, title="t", artist="a")
    db.commit()
    conn = db._conn
    for table in ("scanned", "favorites"):
        conn.execute(f"DROP TRIGGER trg_{table}_path_key_ins")
        conn.execute(f"DROP TRIGGER trg_{table}_path_key_upd")
        conn.execute(f"DROP INDEX idx_{table}_path_key")
        conn.execute(f"UPDATE {table} SET path_key = NULL")
    conn.execute("PRAGMA user_version = 11")
    conn.commit()
    db.close()
    again = LibraryDB(tmp_path / "lib.db")
    again.open()
    assert again.get(NFC)["path"] == MIXED
    assert again.is_favorite(path=NFD)
    again.mark_missing(NFD, since=5)
    assert again.get(MIXED)["missing_since"] == 5
