"""score_group adapter: cache hits, scorer calls, no grouping writes."""

import pytest

from tidal_dl.gui.services.edition_advice_adapter import (
    preview_chip_from_cache,
    score_group,
)
from tidal_dl.gui.services.edition_advice_policy import fingerprint
from tidal_dl.helper.library_db import LibraryDB


@pytest.fixture
def db(tmp_path):
    d = LibraryDB(tmp_path / "test.db")
    d.open()
    yield d
    d.close()


def _seed(db):
    keeper = "/music/Artist - Album/01.flac"
    extra_a = "/music/Artist/Album/01.flac"
    extra_b = "/music/Artist/Album (Copy)/01.flac"
    for path, size, mtime in (
        (keeper, 100, 1),
        (extra_a, 200, 2),
        (extra_b, 300, 3),
    ):
        db.record(
            path,
            status="tagged",
            isrc="US123",
            artist="Artist",
            title="Song",
            album="Album",
            album_artist="Artist",
            duration=200,
            quality="44100Hz/16bit",
            fmt="FLAC",
            codec="flac",
            file_size=size,
            file_mtime=mtime,
        )
    db.commit()
    group = {
        "key": "isrc:US123|Album",
        "status": "auto",
        "keeper": {"path": keeper},
        "duplicates": [{"path": extra_a}, {"path": extra_b}],
    }
    return group, keeper, extra_a, extra_b


def test_cache_hit_skips_scorer_and_scores_miss(db, monkeypatch):
    group, keeper, extra_a, extra_b = _seed(db)
    db.upsert_edition_advice(
        path_a=keeper,
        path_b=extra_a,
        fingerprint_a=fingerprint(keeper, 100, 1),
        fingerprint_b=fingerprint(extra_a, 200, 2),
        relation="layout_twin_extra",
        confidence=0.98,
        probabilities={"layout_twin_extra": 0.98},
        group_id=group["key"],
    )
    calls = []

    def fake_score(item_a, item_b, *, timeout_s=60):
        calls.append((item_a["path"], item_b["path"]))
        return {
            "relation": "keep_both_editions",
            "confidence": 0.99,
            "probabilities": {"keep_both_editions": 0.99},
            "same_isrc_misleading": True,
            "clarity": "high",
            "model": "jev-test",
            "usage": {},
        }

    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_advice_adapter.score_pair", fake_score
    )
    result = score_group(db, group)
    assert [c[1] for c in calls] == [extra_b]
    assert result["group_id"] == group["key"]
    assert result["aggregate"]["relation"] == "keep_both_editions"
    assert "Keep both" in result["aggregate"]["chip"]
    assert len(result["pairs"]) == 2
    by_b = {p["path_b"]: p for p in result["pairs"]}
    assert by_b[extra_a]["cached"] is True
    assert by_b[extra_b]["cached"] is False
    assert by_b[extra_b]["relation"] == "keep_both_editions"
    persisted = db.get_edition_advice(keeper, extra_b)
    assert persisted is not None
    assert persisted["relation"] == "keep_both_editions"


def test_does_not_write_album_grouping_assessments(db, monkeypatch):
    group, *_ = _seed(db)
    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_advice_adapter.score_pair",
        lambda *a, **k: {
            "relation": "true_duplicate_candidate",
            "confidence": 0.96,
            "probabilities": {},
            "same_isrc_misleading": False,
            "clarity": None,
            "model": "jev",
            "usage": {},
        },
    )
    before = db._conn.execute(
        "SELECT COUNT(*) FROM album_grouping_assessments"
    ).fetchone()[0]
    score_group(db, group)
    after = db._conn.execute(
        "SELECT COUNT(*) FROM album_grouping_assessments"
    ).fetchone()[0]
    assert before == 0
    assert after == 0


def test_scorer_error_records_pair_and_continues(db, monkeypatch):
    from tidal_dl.gui.services.edition_scorer import EditionScorerUnavailable

    group, _keeper, extra_a, extra_b = _seed(db)
    seen = []

    def fake_score(item_a, item_b, *, timeout_s=60):
        seen.append(item_b["path"])
        if item_b["path"] == extra_a:
            raise EditionScorerUnavailable("missing")
        return {
            "relation": "layout_twin_extra",
            "confidence": 0.97,
            "probabilities": {},
            "same_isrc_misleading": False,
            "clarity": None,
            "model": "jev",
            "usage": {},
        }

    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_advice_adapter.score_pair", fake_score
    )
    result = score_group(db, group)
    assert set(seen) == {extra_a, extra_b}
    by_b = {p["path_b"]: p for p in result["pairs"]}
    assert by_b[extra_a]["error"]
    assert by_b[extra_b]["relation"] == "layout_twin_extra"
    assert result["aggregate"]["relation"] == "layout_twin_extra"


def test_preview_chip_partial_cache_is_not_ready(db):
    group, keeper, extra_a, _extra_b = _seed(db)
    db.upsert_edition_advice(
        path_a=keeper,
        path_b=extra_a,
        fingerprint_a=fingerprint(keeper, 100, 1),
        fingerprint_b=fingerprint(extra_a, 200, 2),
        relation="layout_twin_extra",
        confidence=0.98,
        group_id=group["key"],
    )
    chip = preview_chip_from_cache(db, group)
    assert chip["state"] != "ready"
    assert chip.get("complete") is False
    assert extra_a in str(chip.get("label") or "") or chip.get("relation") == "layout_twin_extra"


def test_preview_chip_full_cache_is_ready(db):
    group, keeper, extra_a, extra_b = _seed(db)
    for extra, size, mtime, relation in (
        (extra_a, 200, 2, "layout_twin_extra"),
        (extra_b, 300, 3, "keep_both_editions"),
    ):
        db.upsert_edition_advice(
            path_a=keeper,
            path_b=extra,
            fingerprint_a=fingerprint(keeper, 100, 1),
            fingerprint_b=fingerprint(extra, size, mtime),
            relation=relation,
            confidence=0.99,
            group_id=group["key"],
        )
    chip = preview_chip_from_cache(db, group)
    assert chip["state"] == "ready"
    assert chip.get("complete") is True
    assert chip["relation"] == "keep_both_editions"
