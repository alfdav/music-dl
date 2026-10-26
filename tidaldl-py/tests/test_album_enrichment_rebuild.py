"""Enrichment must not rebuild the whole album gallery after every catalog lookup."""

import time

import pytest

FIXED_NOW = 1_700_000_000.0


class _FakeTidal:
    def __init__(self, *args, **kwargs):
        self.session = object()


def _patch_catalogs(monkeypatch):
    import tidal_dl.gui.api.library as library_api
    from tidal_dl import config
    from tidal_dl.gui.api import settings

    monkeypatch.setattr(time, "time", lambda: FIXED_NOW)
    monkeypatch.setattr(config, "Tidal", _FakeTidal)
    monkeypatch.setattr(settings, "_local_auth_status", lambda _tidal: {"logged_in": True})

    def tidal_lookup(left, _right, _session):
        artist = left.album_artist or ""
        if "nomatch" in artist:
            return {"status": "no_match", "same_release": False}
        if "failtidal" in artist:
            raise TimeoutError("offline")
        return {
            "status": "matched",
            "same_release": True,
            "release_id": "tidal-" + artist,
            "title": left.title,
        }

    def mb_lookup(left, _right):
        artist = left.album_artist or ""
        if "failmb" in artist:
            raise TimeoutError("offline")
        return {
            "status": "matched",
            "same_release": True,
            "release_id": "mb-" + artist,
            "title": left.title,
        }

    monkeypatch.setattr(library_api, "_tidal_catalog_lookup", tidal_lookup)
    monkeypatch.setattr(library_api, "_musicbrainz_catalog_lookup", mb_lookup)


def _album(db, *, artist, album, prefix, isrc_prefix, **fields):
    for track in range(1, 5):
        db.record(
            f"/music/{prefix}/{track}.flac",
            status="tagged",
            artist=artist,
            album_artist=artist,
            title=f"Song {track}",
            album=album,
            duration=180 + track,
            isrc=f"{isrc_prefix}{track:05d}",
            track_number=track,
            track_total=fields.get("track_total", 10),
            disc_number=1,
            disc_total=1,
            provider_namespace=fields.get("provider_namespace"),
            provider_album_id=fields.get("provider_album_id"),
            musicbrainz_release_id=fields.get("musicbrainz_release_id"),
            art_available=False,
        )


def _seed_lookup_pairs(db, pairs: int) -> None:
    for index in range(pairs):
        isrc_prefix = f"US{index:03d}01"
        artist = f"Artist {index}"
        _album(db, artist=artist, album=f"Album {index}", prefix=f"p{index}a", isrc_prefix=isrc_prefix)
        _album(
            db, artist=artist, album=f"Album {index} (Live)", prefix=f"p{index}b", isrc_prefix=isrc_prefix,
        )
    db.commit()


def _seed_fixture(path):
    """Library covering merge, chain, skip, failure, and a stale blank-album stamp."""
    from tidal_dl.gui.api.library import _album_cards
    from tidal_dl.helper.library_db import LibraryDB

    db = LibraryDB(path)
    db.open()
    _album(db, artist="Merge Artist", album="Merge", prefix="merge-a", isrc_prefix="USMRG01")
    _album(db, artist="Merge Artist", album="Merge (Deluxe)", prefix="merge-b", isrc_prefix="USMRG01")
    _album(db, artist="Chain Artist", album="Chain", prefix="chain-a", isrc_prefix="USCHN01")
    _album(db, artist="Chain Artist", album="Chain (Deluxe)", prefix="chain-b", isrc_prefix="USCHN01")
    _album(db, artist="Chain Artist", album="Chain (Remaster)", prefix="chain-c", isrc_prefix="USCHN01")
    _album(db, artist="nomatch Artist", album="Partial", prefix="part-a", isrc_prefix="USPRT01")
    _album(db, artist="nomatch Artist", album="Partial (Live)", prefix="part-b", isrc_prefix="USPRT01")
    _album(db, artist="failtidal Artist", album="Flaky", prefix="flaky-a", isrc_prefix="USFLK01")
    _album(db, artist="failtidal Artist", album="Flaky (Live)", prefix="flaky-b", isrc_prefix="USFLK01")
    _album(
        db, artist="Direct Artist", album="Direct", prefix="dir-a", isrc_prefix="USDIR01",
        provider_namespace="tidal", provider_album_id="same-1",
    )
    _album(
        db, artist="Direct Artist", album="Direct (Deluxe)", prefix="dir-b", isrc_prefix="USDIR01",
        provider_namespace="tidal", provider_album_id="same-1",
    )
    _album(db, artist="Chosen Artist", album="Chosen", prefix="ch-a", isrc_prefix="USCHS01")
    _album(db, artist="Chosen Artist", album="Chosen (Live)", prefix="ch-b", isrc_prefix="USCHS01")
    _album(
        db, artist="Veto Artist", album="Veto", prefix="veto-a", isrc_prefix="USVET01",
        track_total=30, musicbrainz_release_id="mb-left",
    )
    _album(
        db, artist="Veto Artist", album="Veto (Live)", prefix="veto-b", isrc_prefix="USVET02",
        track_total=36, musicbrainz_release_id="mb-right",
    )
    _album(db, artist="Solo Artist", album="Solo", prefix="solo", isrc_prefix="USSOL01")
    db.record(
        "/music/blank/1.flac",
        status="tagged",
        artist="Blank Artist",
        album_artist="Blank Artist",
        title="Untitled",
        album="",
        duration=100,
        art_available=False,
    )
    db.commit()
    cards = _album_cards(db)
    chosen = next(card["assessments"][0] for card in cards if card["artist"] == "Chosen Artist")
    assert db.set_grouping_decision(
        chosen["left_signature"], chosen["right_signature"], decision="keep_separate",
    )
    merge = next(card["assessments"][0] for card in cards if card["artist"] == "Merge Artist")
    stored = db.get_grouping_assessment(merge["left_signature"], merge["right_signature"])
    evidence = [
        *stored["evidence"],
        {
            "code": "artwork",
            "family": "weak",
            "points": 3,
            "sources": ["filesystem"],
            "explanation": "Artwork digest sets intersect",
        },
    ]
    with db.write_transaction():
        db.save_grouping_assessment(
            left_signature=stored["left_signature"],
            right_signature=stored["right_signature"],
            score=stored["score"],
            outcome=stored["outcome"],
            evidence=evidence,
            vetoes=stored["vetoes"],
            contradictions=stored["contradictions"],
            catalog=stored["catalog"],
        )
        db._conn.execute(
            "UPDATE scanned SET release_id = ? WHERE path = ?",
            ("stale-blank", "/music/blank/1.flac"),
        )
    return db


def _rebuild_after_every_lookup(db) -> None:
    """Pre-change loop. One full card rebuild after every Tidal or MusicBrainz save."""
    from tidal_dl.config import Tidal
    from tidal_dl.gui.api.library import (
        _album_cards,
        _catalog_source_eligible,
        _musicbrainz_catalog_lookup,
        _safe_catalog_lookup,
        _tidal_catalog_lookup,
    )
    from tidal_dl.gui.api.settings import _local_auth_status
    from tidal_dl.helper.album_grouping import build_local_album_groups, find_candidates

    groups = build_local_album_groups(db.all_tracks())
    for left, right in find_candidates(groups):
        stored = db.get_grouping_assessment(left.signature, right.signature)
        if stored is None:
            continue
        catalog = dict(stored.get("catalog") or {})
        now = time.time()
        same_provider = bool(
            left.values("provider_album_id") & right.values("provider_album_id")
            and left.values("provider_namespace") & right.values("provider_namespace")
        )
        same_musicbrainz = bool(
            left.values("musicbrainz_release_id") & right.values("musicbrainz_release_id")
        )
        sources = []
        tidal = Tidal()
        if _local_auth_status(tidal)["logged_in"] and _catalog_source_eligible(
            stored, "tidal", now=now, direct_identity=same_provider,
        ):
            sources.append((
                "tidal",
                lambda left=left, right=right, session=tidal.session: _tidal_catalog_lookup(left, right, session),
            ))
        if _catalog_source_eligible(stored, "musicbrainz", now=now, direct_identity=same_musicbrainz):
            sources.append((
                "musicbrainz",
                lambda left=left, right=right: _musicbrainz_catalog_lookup(left, right),
            ))
        for source, lookup in sources:
            attempted_at = time.time()
            result = _safe_catalog_lookup(lookup)
            catalog[source] = {**result, "attempted_at": attempted_at}
            with db.write_transaction():
                db.save_grouping_assessment(
                    left_signature=left.signature,
                    right_signature=right.signature,
                    score=stored["score"],
                    outcome=stored["outcome"],
                    evidence=stored["evidence"],
                    vetoes=stored["vetoes"],
                    contradictions=stored["contradictions"],
                    catalog=catalog,
                )
            _album_cards(db)
            stored = db.get_grouping_assessment(left.signature, right.signature) or stored


def _snapshot(db) -> dict:
    assessments = [dict(row) for row in db.list_grouping_assessments()]
    assessments.sort(key=lambda row: (row["left_signature"], row["right_signature"]))
    release_ids = sorted(
        (row["path"], row["release_id"])
        for row in db._conn.execute("SELECT path, release_id FROM scanned")
    )
    return {"assessments": assessments, "release_ids": release_ids}


def _cards_without_read_release_ids(cards):
    """Drop release ids read at the start of a rebuild.

    `_album_cards` stamps after it has already copied track rows, and enrichment
    discards the returned cards. The persisted `scanned.release_id` is the stamp.
    """
    normalized = []
    for card in cards:
        item = dict(card)
        item["tracks"] = [
            {key: value for key, value in track.items() if key != "release_id"}
            for track in card["tracks"]
        ]
        normalized.append(item)
    return normalized


@pytest.mark.parametrize("pairs", [1, 5, 50])
def test_album_card_rebuilds_stay_constant_as_lookups_grow(tmp_path, monkeypatch, pairs):
    from tidal_dl.gui.api import library as library_api
    from tidal_dl.helper.library_db import LibraryDB

    _patch_catalogs(monkeypatch)
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed_lookup_pairs(db, pairs)
    library_api._album_cards(db)
    calls = []
    real = library_api._album_cards

    def spy(db_arg, rows=None, **kwargs):
        calls.append(rows)
        return real(db_arg, rows, **kwargs)

    monkeypatch.setattr(library_api, "_album_cards", spy)

    library_api._enrich_album_candidates(db)

    assert len(calls) == 1, f"{pairs} pairs rebuilt album cards {len(calls)} times"
    db.close()


def test_rebuild_still_runs_once_when_a_later_pair_raises(tmp_path, monkeypatch):
    from tidal_dl import config
    from tidal_dl.gui.api import library as library_api
    from tidal_dl.helper.library_db import LibraryDB

    _patch_catalogs(monkeypatch)
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    _seed_lookup_pairs(db, 2)
    library_api._album_cards(db)
    calls = []
    real = library_api._album_cards

    def spy(db_arg, rows=None, **kwargs):
        calls.append(rows)
        return real(db_arg, rows, **kwargs)

    monkeypatch.setattr(library_api, "_album_cards", spy)
    created = {"n": 0}

    class FlakyTidal:
        def __init__(self, *args, **kwargs):
            created["n"] += 1
            if created["n"] > 1:
                raise RuntimeError("tidal down")
            self.session = object()

    monkeypatch.setattr(config, "Tidal", FlakyTidal)
    try:
        with pytest.raises(RuntimeError, match="tidal down"):
            library_api._enrich_album_candidates(db)
        assert calls == [None]
    finally:
        db.close()


def test_enrichment_cards_and_assessments_match_per_lookup_rebuild(tmp_path, monkeypatch):
    from tidal_dl.gui.api import library as library_api

    _patch_catalogs(monkeypatch)
    old = _seed_fixture(tmp_path / "old.db")
    new = _seed_fixture(tmp_path / "new.db")
    recorded = []
    real = library_api._album_cards

    def spy(db_arg, rows=None, **kwargs):
        cards = real(db_arg, rows, **kwargs)
        recorded.append(cards)
        return cards

    monkeypatch.setattr(library_api, "_album_cards", spy)
    try:
        _rebuild_after_every_lookup(old)
        old_cards = recorded[-1]
        recorded.clear()
        library_api._enrich_album_candidates(new)
        new_cards = recorded[-1]
        assert _snapshot(new) == _snapshot(old)
        # Track release_id is left out of the card comparison. _album_cards copies
        # track rows before it stamps, and enrichment discards those cards.
        # The DB stamps are compared on the snapshot above.
        assert _cards_without_read_release_ids(new_cards) == _cards_without_read_release_ids(old_cards)
    finally:
        old.close()
        new.close()
