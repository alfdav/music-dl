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
