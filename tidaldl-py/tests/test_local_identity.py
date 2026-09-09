"""Product-wide local identity: live files must stamp is_local / local_path.

These cases hold for any library. Fixtures are invented artists so a
normalize miss, ISRC/path mismatch, or stale Artist - Album index after a
layout move cannot be papered over with a one-album cleanup.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tidal_dl.gui.api import albums as albums_api
from tidal_dl.gui.api import search as search_api
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.local_identity import (
    finish_stamp,
    match_local_row,
    recording_title,
    stamp_track,
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"flac")
    return path


def _open_db(tmp_path: Path) -> LibraryDB:
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    return db


def _record(db: LibraryDB, path: Path | str, **fields) -> None:
    db.record(str(path), status="tagged", **fields)


def _tidal_track(
    *,
    track_id: int,
    name: str,
    artist: str,
    album: str,
    isrc: str,
    extra_artists: list[str] | None = None,
):
    names = [artist, *(extra_artists or [])]
    return SimpleNamespace(
        id=track_id,
        name=name,
        full_name=name,
        artists=[SimpleNamespace(name=part) for part in names],
        album=SimpleNamespace(id=track_id + 1000, name=album, image=lambda size: "cover"),
        duration=180,
        audio_quality="LOSSLESS",
        isrc=isrc,
        media_metadata_tags=[],
    )


def _tidal_album(album_id: int, name: str, artist: str, tracks: list):
    return SimpleNamespace(
        id=album_id,
        name=name,
        artist=SimpleNamespace(name=artist),
        num_tracks=len(tracks),
        tracks=lambda: list(tracks),
        image=lambda size: f"cover-{album_id}",
    )


def _patch_search_db(monkeypatch, db: LibraryDB) -> None:
    monkeypatch.setattr(search_api, "_get_library_db", lambda: db)


def _patch_album_lookup(monkeypatch, db: LibraryDB, tidal_album) -> None:
    monkeypatch.setattr(albums_api, "_get_library_db", lambda: db)
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        search=lambda query, models=None, limit=20: {"albums": [tidal_album]},
        album=lambda album_id: tidal_album,
    )
    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))


def test_search_stamps_local_when_isrc_mismatches_live_title_artist_album(tmp_path, monkeypatch):
    """Any library: file on disk, tags match, ISRC does not — still local."""
    live = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        live,
        artist="Juniper Vale",
        title="Static",
        album="Safe Room",
        isrc="USESK0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()
    _patch_search_db(monkeypatch, db)

    result = search_api._serialize_track(
        _tidal_track(
            track_id=11,
            name="Static",
            artist="Juniper Vale",
            album="Safe Room",
            isrc="QZESX1234567",
        )
    )

    assert result["is_local"] is True
    assert result["local_path"] == str(live)
    assert result["path"] == str(live)
    db.close()


def test_search_stamps_local_when_index_path_is_dead_after_layout_move(tmp_path, monkeypatch):
    """Any library: ISRC hits a leftover Artist - Album index after Artist/Album move."""
    stale = tmp_path / "music" / "Maren Ortega - Glass Harbor" / "01 Low Tide.flac"
    live = _touch(tmp_path / "music" / "Maren Ortega" / "Glass Harbor" / "01 Low Tide.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        stale,
        artist="Maren Ortega",
        title="Low Tide",
        album="Glass Harbor",
        isrc="QZMAR0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()
    assert not stale.is_file()
    assert live.is_file()
    _patch_search_db(monkeypatch, db)

    result = search_api._serialize_track(
        _tidal_track(
            track_id=21,
            name="Low Tide",
            artist="Maren Ortega",
            album="Glass Harbor",
            isrc="QZMAR0000001",
        )
    )

    assert result["is_local"] is True
    assert result["local_path"] == str(live)
    assert result["path"] == str(live)
    db.close()


def test_resolve_live_library_path_rewrites_flat_artist_album_dir(tmp_path):
    """Layout-move helper works for any Artist - Album leftover, including disc folders."""
    from tidal_dl.helper.path import resolve_live_library_path

    live = _touch(tmp_path / "library" / "Nia Coltrane" / "Night Letters" / "CD1" / "02 Harbor Light.flac")
    stale = tmp_path / "library" / "Nia Coltrane - Night Letters" / "CD1" / "02 Harbor Light.flac"

    assert resolve_live_library_path(str(stale)) == str(live)
    assert resolve_live_library_path(str(live)) == str(live)


def test_album_lookup_stamps_local_when_album_tag_needs_normalize(tmp_path, monkeypatch):
    """Any library: leftover Artist - Album [FLAC] tag still matches Tidal album title."""
    live = _touch(
        tmp_path / "music" / "Maren Ortega" / "Glass Harbor" / "01 Low Tide.flac"
    )
    db = _open_db(tmp_path)
    _record(
        db,
        live,
        artist="Maren Ortega",
        title="Low Tide",
        album="Maren Ortega - Glass Harbor [FLAC]",
        isrc="QZMAR0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        40,
        "Glass Harbor",
        "Maren Ortega",
        [_tidal_track(track_id=41, name="Low Tide", artist="Maren Ortega", album="Glass Harbor", isrc="QZMAR0000001")],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    result = albums_api.album_lookup("Maren Ortega", "Glass Harbor")

    assert result["tracks"][0]["is_local"] is True
    assert result["tracks"][0]["local_path"] == str(live)
    assert result["tracks"][0]["path"] == str(live)
    assert result["missing_count"] == 0
    db.close()


def test_album_lookup_stamps_local_when_title_has_feat_paren_variant(tmp_path, monkeypatch):
    """Tidal 'Title (feat. X)' must match a live file tagged as 'Title'."""
    live = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        live,
        artist="Juniper Vale",
        title="Static",
        album="Safe Room",
        isrc="",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        50,
        "Safe Room",
        "Juniper Vale",
        [_tidal_track(
            track_id=51,
            name="Static (feat. Icarus)",
            artist="Juniper Vale",
            album="Safe Room",
            isrc="QZJUN0000099",
        )],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    result = albums_api.album_lookup("Juniper Vale", "Safe Room")

    assert result["tracks"][0]["is_local"] is True
    assert result["tracks"][0]["local_path"] == str(live)
    assert result["missing_count"] == 0
    db.close()


def test_tidal_album_tracks_stamp_local_when_file_exists_without_matching_isrc(
    tmp_path, monkeypatch, clear_singletons,
):
    """GET /albums/{id}/tracks is the Tidal album-detail surface — same identity law."""
    live = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "02 Harbor Light.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        live,
        artist="Nia Coltrane",
        title="Harbor Light",
        album="Night Letters",
        isrc="",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal_track = _tidal_track(
        track_id=61,
        name="Harbor Light",
        artist="Nia Coltrane",
        album="Night Letters",
        isrc="QZNIA0000061",
    )
    tidal_album = _tidal_album(60, "Night Letters", "Nia Coltrane", [tidal_track])
    _patch_album_lookup(monkeypatch, db, tidal_album)

    result = albums_api.album_tracks(60)

    assert result["tracks"][0]["is_local"] is True
    assert result["tracks"][0]["local_path"] == str(live)
    db.close()


def test_album_tracks_does_not_mark_same_isrc_from_a_different_album(tmp_path, monkeypatch):
    """GET /albums/{id}/tracks must restamp album-scoped, like album_lookup."""
    other = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    wanted = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "04 Other Song.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        other,
        artist="Juniper Vale",
        title="Static",
        album="Safe Room",
        isrc="SHARED0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    _record(
        db,
        wanted,
        artist="Nia Coltrane",
        title="Other Song",
        album="Night Letters",
        isrc="QZNIA0000004",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    compilation = _tidal_album(
        110,
        "Night Letters",
        "Nia Coltrane",
        [
            _tidal_track(
                track_id=111,
                name="Static",
                artist="Juniper Vale",
                album="Night Letters",
                isrc="SHARED0000001",
            ),
            _tidal_track(
                track_id=112,
                name="Other Song",
                artist="Nia Coltrane",
                album="Night Letters",
                isrc="QZNIA0000004",
            ),
        ],
    )
    _patch_album_lookup(monkeypatch, db, compilation)

    result = albums_api.album_tracks(110)
    by_name = {track["name"]: track for track in result["tracks"]}

    assert by_name["Static"]["is_local"] is False
    assert by_name["Static"].get("local_path") in (None, "")
    assert by_name["Other Song"]["is_local"] is True
    assert by_name["Other Song"]["local_path"] == str(wanted)
    db.close()


def test_album_tracks_does_not_mark_same_title_artist_from_a_different_album(tmp_path, monkeypatch):
    """Catalog-wide title+artist must not hide Download on a different album page."""
    other = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    wanted = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "01 Low Tide.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        other,
        artist="Juniper Vale",
        title="Static",
        album="Safe Room",
        album_artist="Juniper Vale",
        isrc="USESK0000099",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    _record(
        db,
        wanted,
        artist="Nia Coltrane",
        title="Low Tide",
        album="Night Letters",
        album_artist="Nia Coltrane",
        isrc="QZNIA0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    compilation = _tidal_album(
        120,
        "Night Letters",
        "Nia Coltrane",
        [
            _tidal_track(
                track_id=121,
                name="Static",
                artist="Juniper Vale",
                album="Night Letters",
                isrc="QZNIA0000121",
            ),
            _tidal_track(
                track_id=122,
                name="Low Tide",
                artist="Nia Coltrane",
                album="Night Letters",
                isrc="QZNIA0000001",
            ),
        ],
    )
    _patch_album_lookup(monkeypatch, db, compilation)

    result = albums_api.album_tracks(120)
    by_name = {track["name"]: track for track in result["tracks"]}

    assert by_name["Static"]["is_local"] is False
    assert by_name["Static"].get("local_path") in (None, "")
    assert by_name["Low Tide"]["is_local"] is True
    assert by_name["Low Tide"]["local_path"] == str(wanted)
    db.close()


def test_album_lookup_does_not_mark_same_isrc_from_a_different_album(tmp_path, monkeypatch):
    """Album-scoped identity must not steal a live file from another release."""
    other = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    wanted = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "04 Other Song.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        other,
        artist="Juniper Vale",
        title="Static",
        album="Safe Room",
        isrc="SHARED0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    _record(
        db,
        wanted,
        artist="Nia Coltrane",
        title="Other Song",
        album="Night Letters",
        isrc="QZNIA0000004",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    compilation = _tidal_album(
        70,
        "Night Letters",
        "Nia Coltrane",
        [
            _tidal_track(track_id=71, name="Static", artist="Juniper Vale", album="Night Letters", isrc="SHARED0000001"),
            _tidal_track(track_id=72, name="Other Song", artist="Nia Coltrane", album="Night Letters", isrc="QZNIA0000004"),
        ],
    )
    _patch_album_lookup(monkeypatch, db, compilation)

    result = albums_api.album_lookup("Nia Coltrane", "Night Letters")
    by_name = {track["name"]: track for track in result["tracks"]}

    assert by_name["Static"]["is_local"] is False
    assert by_name["Static"].get("local_path") in (None, "")
    assert by_name["Other Song"]["is_local"] is True
    assert by_name["Other Song"]["local_path"] == str(wanted)
    db.close()


def test_match_local_row_compilation_uses_track_artist_not_scope_artist(tmp_path):
    """Album scope_artist must not replace the catalog track artist for title match."""
    live = _touch(tmp_path / "music" / "Juniper Vale" / "Harbor Radio" / "01 Static.flac")
    row = {
        "path": str(live),
        "artist": "Juniper Vale",
        "title": "Static",
        "album": "Harbor Radio",
        "isrc": "USESK0000001",
    }
    track = {
        "name": "Static",
        "artist": "Juniper Vale",
        "album": "Harbor Radio",
        "isrc": "QZVA00000001",
    }

    matched = match_local_row(
        track,
        [row],
        album_scoped=True,
        scope_artist="Various Artists",
        scope_album="Harbor Radio",
    )

    assert matched is not None
    assert matched["path"] == str(live)


def test_match_local_row_guest_credit_matches_track_artist_when_scoped(tmp_path):
    """Guest-credit files match by track artist + title even when the album artist differs."""
    live = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "04 Harbor Light.flac")
    row = {
        "path": str(live),
        "artist": "Juniper Vale",
        "title": "Harbor Light",
        "album": "Night Letters",
        "album_artist": "Nia Coltrane",
        "isrc": "",
    }
    track = {
        "name": "Harbor Light",
        "artist": "Juniper Vale",
        "album": "Night Letters",
        "isrc": "QZNIA0000099",
    }

    matched = match_local_row(
        track,
        [row],
        album_scoped=True,
        scope_artist="Nia Coltrane",
        scope_album="Night Letters",
    )

    assert matched is not None
    assert matched["path"] == str(live)


def test_match_local_row_album_scope_rejects_same_title_on_other_album(tmp_path):
    """Album scoping still blocks a title+artist hit from a different release."""
    other = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    row = {
        "path": str(other),
        "artist": "Juniper Vale",
        "title": "Static",
        "album": "Safe Room",
        "isrc": "",
    }
    track = {
        "name": "Static",
        "artist": "Juniper Vale",
        "album": "Night Letters",
        "isrc": "QZNIA0000071",
    }

    matched = match_local_row(
        track,
        [row],
        album_scoped=True,
        scope_artist="Nia Coltrane",
        scope_album="Night Letters",
    )

    assert matched is None


def test_album_lookup_stamps_compilation_track_when_isrc_mismatches(tmp_path, monkeypatch):
    """Various Artists lookup must restamp from track artist + title, not album artist."""
    live = _touch(tmp_path / "music" / "Juniper Vale" / "Harbor Radio" / "01 Static.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        live,
        artist="Juniper Vale",
        title="Static",
        album="Harbor Radio",
        album_artist="Various Artists",
        isrc="USESK0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        80,
        "Harbor Radio",
        "Various Artists",
        [_tidal_track(
            track_id=81,
            name="Static",
            artist="Juniper Vale",
            album="Harbor Radio",
            isrc="QZVA00000001",
        )],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    result = albums_api.album_lookup("Various Artists", "Harbor Radio")

    assert result["tracks"][0]["is_local"] is True
    assert result["tracks"][0]["local_path"] == str(live)
    assert result["missing_count"] == 0
    db.close()


def test_album_lookup_stamps_guest_credit_when_isrc_mismatches(tmp_path, monkeypatch):
    """Guest credit on a host album still stamps when ISRC does not match the file."""
    live = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "04 Harbor Light.flac")
    host = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "01 Low Tide.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        host,
        artist="Nia Coltrane",
        title="Low Tide",
        album="Night Letters",
        album_artist="Nia Coltrane",
        isrc="QZNIA0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    _record(
        db,
        live,
        artist="Juniper Vale",
        title="Harbor Light",
        album="Night Letters",
        album_artist="Nia Coltrane",
        isrc="USESK0000002",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        90,
        "Night Letters",
        "Nia Coltrane",
        [
            _tidal_track(track_id=91, name="Low Tide", artist="Nia Coltrane", album="Night Letters", isrc="QZNIA0000001"),
            _tidal_track(
                track_id=92,
                name="Harbor Light",
                artist="Juniper Vale",
                album="Night Letters",
                isrc="QZNIA0000092",
            ),
        ],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    result = albums_api.album_lookup("Nia Coltrane", "Night Letters")
    by_name = {track["name"]: track for track in result["tracks"]}

    assert by_name["Low Tide"]["is_local"] is True
    assert by_name["Harbor Light"]["is_local"] is True
    assert by_name["Harbor Light"]["local_path"] == str(live)
    assert result["missing_count"] == 0
    db.close()


def test_album_lookup_title_match_does_not_take_same_title_from_other_album(tmp_path, monkeypatch):
    """Title+track-artist must not restamp a file that lives on a different album."""
    other = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    wanted = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "01 Low Tide.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        other,
        artist="Juniper Vale",
        title="Static",
        album="Safe Room",
        album_artist="Juniper Vale",
        isrc="USESK0000099",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    _record(
        db,
        wanted,
        artist="Nia Coltrane",
        title="Low Tide",
        album="Night Letters",
        album_artist="Nia Coltrane",
        isrc="QZNIA0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        100,
        "Night Letters",
        "Nia Coltrane",
        [
            _tidal_track(track_id=101, name="Static", artist="Juniper Vale", album="Night Letters", isrc="QZNIA0000101"),
            _tidal_track(track_id=102, name="Low Tide", artist="Nia Coltrane", album="Night Letters", isrc="QZNIA0000001"),
        ],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    result = albums_api.album_lookup("Nia Coltrane", "Night Letters")
    by_name = {track["name"]: track for track in result["tracks"]}

    assert by_name["Static"]["is_local"] is False
    assert by_name["Static"].get("local_path") in (None, "")
    assert by_name["Low Tide"]["is_local"] is True
    assert by_name["Low Tide"]["local_path"] == str(wanted)
    db.close()


def test_match_local_row_keeps_live_remix_and_radio_edit_distinct(tmp_path):
    """Version parentheticals are different recordings, even when both files exist."""
    original = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    live = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static (Live).flac")
    remix = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "02 Static (Remix).flac")
    radio = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "03 Static (Radio Edit).flac")
    rows = [
        {"path": str(original), "artist": "Juniper Vale", "title": "Static", "album": "Safe Room"},
        {"path": str(live), "artist": "Juniper Vale", "title": "Static (Live)", "album": "Safe Room"},
        {"path": str(remix), "artist": "Juniper Vale", "title": "Static (Remix)", "album": "Safe Room"},
        {"path": str(radio), "artist": "Juniper Vale", "title": "Static (Radio Edit)", "album": "Safe Room"},
    ]

    def _track(name: str) -> dict:
        return {"name": name, "artist": "Juniper Vale", "album": "Safe Room", "isrc": ""}

    assert match_local_row(_track("Static"), rows)["path"] == str(original)
    assert match_local_row(_track("Static (Live)"), rows)["path"] == str(live)
    assert match_local_row(_track("Static (Remix)"), rows)["path"] == str(remix)
    assert match_local_row(_track("Static (Radio Edit)"), rows)["path"] == str(radio)
    assert match_local_row(_track("Static (Acoustic)"), rows) is None


def test_match_local_row_does_not_let_shortest_path_steal_a_version(tmp_path):
    """A shorter original path must not win when the catalog title is the live cut."""
    original = _touch(tmp_path / "a" / "Static.flac")
    live = _touch(tmp_path / "library" / "Juniper Vale" / "Safe Room" / "01 Static (Live).flac")
    rows = [
        {"path": str(original), "artist": "Juniper Vale", "title": "Static", "album": "Safe Room"},
        {"path": str(live), "artist": "Juniper Vale", "title": "Static (Live)", "album": "Safe Room"},
    ]
    track = {"name": "Static (Live)", "artist": "Juniper Vale", "album": "Safe Room", "isrc": ""}

    matched = match_local_row(track, rows)

    assert matched is not None
    assert matched["path"] == str(live)


def test_stamp_track_clears_foreign_quality_when_restamp_misses():
    """Album-scoped miss must drop on-disk quality/format/codec from a prior stamp."""
    track = {
        "name": "Static",
        "artist": "Juniper Vale",
        "album": "Night Letters",
        "quality": "LOSSLESS",
        "is_local": False,
    }
    stamp_track(track, {
        "path": "/music/Juniper Vale/Safe Room/01 Static.flac",
        "quality": "FLAC",
        "format": "FLAC",
        "codec": "flac",
    })
    stamp_track(track, None)

    assert track["is_local"] is False
    assert track.get("local_path") in (None, "")
    assert track.get("path") in (None, "")
    assert track.get("format") in (None, "")
    assert track.get("codec") in (None, "")
    assert track.get("quality") != "FLAC"
    assert track.get("quality") == "LOSSLESS"


def test_album_tracks_clears_foreign_quality_when_shared_isrc_is_other_album(
    tmp_path, monkeypatch,
):
    """Remote album-detail rows must not keep another release's on-disk quality."""
    other = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        other,
        artist="Juniper Vale",
        title="Static",
        album="Safe Room",
        isrc="SHARED0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    compilation = _tidal_album(
        130,
        "Night Letters",
        "Nia Coltrane",
        [_tidal_track(
            track_id=131,
            name="Static",
            artist="Juniper Vale",
            album="Night Letters",
            isrc="SHARED0000001",
        )],
    )
    _patch_album_lookup(monkeypatch, db, compilation)

    result = albums_api.album_tracks(130)
    track = result["tracks"][0]

    assert track["is_local"] is False
    assert track.get("local_path") in (None, "")
    assert track.get("format") in (None, "")
    assert track.get("codec") in (None, "")
    assert track.get("quality") != "FLAC"
    db.close()


def test_album_lookup_stamps_guest_leftover_artist_album_tag(tmp_path, monkeypatch):
    """Guest credit tagged Artist - Album still enters the host album candidate pool."""
    live = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "04 Harbor Light.flac")
    host = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "01 Low Tide.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        host,
        artist="Nia Coltrane",
        title="Low Tide",
        album="Night Letters",
        album_artist="Nia Coltrane",
        isrc="QZNIA0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    _record(
        db,
        live,
        artist="Juniper Vale",
        title="Harbor Light",
        album="Nia Coltrane - Night Letters [FLAC]",
        album_artist="Nia Coltrane",
        isrc="USESK0000002",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        140,
        "Night Letters",
        "Nia Coltrane",
        [
            _tidal_track(track_id=141, name="Low Tide", artist="Nia Coltrane", album="Night Letters", isrc="QZNIA0000001"),
            _tidal_track(
                track_id=142,
                name="Harbor Light",
                artist="Juniper Vale",
                album="Night Letters",
                isrc="QZNIA0000142",
            ),
        ],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    pool = db.tracks_for_album_identity("Nia Coltrane", "Night Letters")
    assert any(row.get("path") == str(live) for row in pool)

    result = albums_api.album_lookup("Nia Coltrane", "Night Letters")
    by_name = {track["name"]: track for track in result["tracks"]}

    assert by_name["Harbor Light"]["is_local"] is True
    assert by_name["Harbor Light"]["local_path"] == str(live)
    assert result["missing_count"] == 0
    db.close()


def test_album_lookup_does_not_stamp_foreign_leftover_codec_tag_on_va(
    tmp_path, monkeypatch,
):
    """Another artist's leftover Album [FLAC] must not enter a VA compilation pool."""
    foreign = _touch(tmp_path / "music" / "Juniper Vale" / "Harbor Radio" / "01 Static.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        foreign,
        artist="Juniper Vale",
        title="Static",
        album="Harbor Radio [FLAC]",
        album_artist="Juniper Vale",
        isrc="USESK0000777",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        150,
        "Harbor Radio",
        "Various Artists",
        [_tidal_track(
            track_id=151,
            name="Static",
            artist="Nia Coltrane",
            album="Harbor Radio",
            isrc="QZNIA0000151",
        )],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    leftover = db.tracks_for_leftover_album_tags("Various Artists", "Harbor Radio")
    assert leftover == []
    pool = db.tracks_for_album_identity("Various Artists", "Harbor Radio")
    assert all(row.get("path") != str(foreign) for row in pool)

    result = albums_api.album_lookup("Various Artists", "Harbor Radio")
    assert result["tracks"][0]["is_local"] is False
    assert result["tracks"][0].get("local_path") in (None, "")
    assert result["missing_count"] == 1
    db.close()


def test_recording_title_strips_feat_when_leftover_suffix_follows():
    """Feat/ft/with is the same recording even when Explicit or Bonus Track follows."""
    assert recording_title("Static (feat. Icarus) [Explicit]") == recording_title("Static")
    assert recording_title("Static (feat. Icarus) (Bonus Track)") == recording_title("Static")
    assert recording_title("Static (Live)") != recording_title("Static")
    assert recording_title("Static (Remix)") != recording_title("Static")


def test_match_local_row_stamps_feat_title_with_extra_suffix(tmp_path):
    """Catalog Title (feat. X) [Explicit] must still hit a live file tagged Title."""
    live = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    rows = [{
        "path": str(live),
        "artist": "Juniper Vale",
        "title": "Static",
        "album": "Safe Room",
    }]

    matched = match_local_row(
        {
            "name": "Static (feat. Icarus) [Explicit]",
            "artist": "Juniper Vale",
            "album": "Safe Room",
            "isrc": "",
        },
        rows,
    )
    bonus = match_local_row(
        {
            "name": "Static (feat. Icarus) (Bonus Track)",
            "artist": "Juniper Vale",
            "album": "Safe Room",
            "isrc": "",
        },
        rows,
    )

    assert matched is not None
    assert matched["path"] == str(live)
    assert bonus is not None
    assert bonus["path"] == str(live)


def test_album_identity_does_not_return_unfiltered_va_exact_rows(tmp_path, monkeypatch):
    """VA album_tracks is title-only. A rejected filter must not return those rows."""
    foreign = _touch(tmp_path / "music" / "Juniper Vale" / "Harbor Radio" / "01 Static.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        foreign,
        artist="Juniper Vale",
        title="Static",
        album="Harbor Radio",
        album_artist="Juniper Vale",
        isrc="USESK0000888",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        160,
        "Harbor Radio",
        "Various Artists",
        [_tidal_track(
            track_id=161,
            name="Static",
            artist="Nia Coltrane",
            album="Harbor Radio",
            isrc="QZNIA0000161",
        )],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    exact = db.album_tracks("Various Artists", "Harbor Radio")
    assert any(row.get("path") == str(foreign) for row in exact)
    pool = db.tracks_for_album_identity("Various Artists", "Harbor Radio")
    assert all(row.get("path") != str(foreign) for row in pool)

    result = albums_api.album_lookup("Various Artists", "Harbor Radio")
    assert result["tracks"][0]["is_local"] is False
    assert result["tracks"][0].get("local_path") in (None, "")
    db.close()


def test_identity_finds_file_tagged_as_later_featured_artist(tmp_path, monkeypatch):
    """Comma-separated catalog credits must load every featured artist's rows."""
    host = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "01 Low Tide.flac")
    guest = _touch(tmp_path / "music" / "Juniper Vale" / "Safe Room" / "01 Static.flac")
    db = _open_db(tmp_path)
    _record(db, host, artist="Nia Coltrane", title="Low Tide", album="Night Letters", isrc="USESK0000901")
    _record(db, guest, artist="Juniper Vale", title="Static", album="Safe Room", isrc="USESK0000902")
    db.commit()
    _patch_search_db(monkeypatch, db)

    pool = db.tracks_for_identity(
        isrc="QZNIA0000902",
        title="Static",
        artist="Nia Coltrane, Juniper Vale",
        album="Harbor Radio",
    )
    assert any(row.get("path") == str(guest) for row in pool)

    result = search_api._serialize_track(_tidal_track(
        track_id=162,
        name="Static",
        artist="Nia Coltrane",
        extra_artists=["Juniper Vale"],
        album="Harbor Radio",
        isrc="QZNIA0000902",
    ))
    assert result["is_local"] is True
    assert result.get("local_path") == str(guest)
    db.close()


def test_album_lookup_stamps_guest_missing_album_artist_same_folder(tmp_path, monkeypatch):
    """Co-release guest with no album_artist still stamps when it shares the album folder."""
    host = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "01 Low Tide.flac")
    guest = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "04 Harbor Light.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        host,
        artist="Nia Coltrane",
        title="Low Tide",
        album="Night Letters",
        album_artist="Nia Coltrane",
        isrc="QZNIA0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    _record(
        db,
        guest,
        artist="Juniper Vale",
        title="Harbor Light",
        album="Night Letters",
        album_artist=None,
        isrc="USESK0000269",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        170,
        "Night Letters",
        "Nia Coltrane",
        [
            _tidal_track(track_id=171, name="Low Tide", artist="Nia Coltrane", album="Night Letters", isrc="QZNIA0000001"),
            _tidal_track(
                track_id=172,
                name="Harbor Light",
                artist="Juniper Vale",
                album="Night Letters",
                isrc="USESK0000269",
            ),
        ],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    pool = db.tracks_for_album_identity("Nia Coltrane", "Night Letters")
    assert any(row.get("path") == str(guest) for row in pool)

    result = albums_api.album_lookup("Nia Coltrane", "Night Letters")
    by_name = {track["name"]: track for track in result["tracks"]}

    assert by_name["Low Tide"]["is_local"] is True
    assert by_name["Harbor Light"]["is_local"] is True
    assert by_name["Harbor Light"]["local_path"] == str(guest)
    assert result["missing_count"] == 0
    db.close()


def test_album_tracks_stamps_guest_missing_album_artist_same_folder(tmp_path, monkeypatch):
    """Tidal album detail must restamp the same folder-scoped guest ISRC."""
    host = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "01 Low Tide.flac")
    guest = _touch(tmp_path / "music" / "Nia Coltrane" / "Night Letters" / "04 Harbor Light.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        host,
        artist="Nia Coltrane",
        title="Low Tide",
        album="Night Letters",
        album_artist="Nia Coltrane",
        isrc="QZNIA0000001",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    _record(
        db,
        guest,
        artist="Juniper Vale",
        title="Harbor Light",
        album="Night Letters",
        album_artist=None,
        isrc="USESK0000269",
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
    )
    db.commit()

    tidal = _tidal_album(
        180,
        "Night Letters",
        "Nia Coltrane",
        [
            _tidal_track(track_id=181, name="Low Tide", artist="Nia Coltrane", album="Night Letters", isrc="QZNIA0000001"),
            _tidal_track(
                track_id=182,
                name="Harbor Light",
                artist="Juniper Vale",
                album="Night Letters",
                isrc="USESK0000269",
            ),
        ],
    )
    _patch_album_lookup(monkeypatch, db, tidal)

    result = albums_api.album_tracks(180)
    by_name = {track["name"]: track for track in result["tracks"]}

    assert by_name["Harbor Light"]["is_local"] is True
    assert by_name["Harbor Light"]["local_path"] == str(guest)
    db.close()


def test_album_identity_includes_guest_sharing_album_dir_without_host_folder(tmp_path):
    """Host-matched rows pull in same-folder guests even when the path has no artist dir."""
    host = _touch(tmp_path / "music" / "Night Letters" / "01 Low Tide.flac")
    guest = _touch(tmp_path / "music" / "Night Letters" / "04 Harbor Light.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        host,
        artist="Nia Coltrane",
        title="Low Tide",
        album="Night Letters",
        album_artist="Nia Coltrane",
        isrc="QZNIA0000001",
    )
    _record(
        db,
        guest,
        artist="Juniper Vale",
        title="Harbor Light",
        album="Night Letters",
        album_artist=None,
        isrc="USESK0000269",
    )
    db.commit()

    pool = db.tracks_for_album_identity("Nia Coltrane", "Night Letters")
    assert any(row.get("path") == str(host) for row in pool)
    assert any(row.get("path") == str(guest) for row in pool)
    db.close()


def test_album_identity_does_not_use_home_folder_named_like_host(tmp_path):
    """A home/volume directory named for the host must not steal another artist's album."""
    foreign = _touch(
        tmp_path / "Users" / "Nia Coltrane" / "Music" / "Juniper Vale" / "Greatest Hits" / "01 Static.flac"
    )
    db = _open_db(tmp_path)
    _record(
        db,
        foreign,
        artist="Juniper Vale",
        title="Static",
        album="Greatest Hits",
        album_artist=None,
        isrc="USESK0000777",
    )
    db.commit()

    pool = db.tracks_for_album_identity("Nia Coltrane", "Greatest Hits")
    assert all(row.get("path") != str(foreign) for row in pool)
    db.close()


def test_album_identity_does_not_group_flat_library_same_title_dumps(tmp_path):
    """Two Greatest Hits files dumped in the library root are not one album folder."""
    host = _touch(tmp_path / "music" / "01 Low Tide.flac")
    foreign = _touch(tmp_path / "music" / "01 Static.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        host,
        artist="Nia Coltrane",
        title="Low Tide",
        album="Greatest Hits",
        album_artist="Nia Coltrane",
        isrc="QZNIA0000777",
    )
    _record(
        db,
        foreign,
        artist="Juniper Vale",
        title="Static",
        album="Greatest Hits",
        album_artist=None,
        isrc="USESK0000777",
    )
    db.commit()

    pool = db.tracks_for_album_identity("Nia Coltrane", "Greatest Hits")
    assert any(row.get("path") == str(host) for row in pool)
    assert all(row.get("path") != str(foreign) for row in pool)
    db.close()


def test_path_under_artist_ignores_filename_credit(tmp_path):
    from tidal_dl.helper.local_identity import path_under_artist

    path = tmp_path / "music" / "Juniper Vale" / "Safe Room" / "Nia Coltrane - Static.flac"
    assert path_under_artist(str(path), "Nia Coltrane") is False
    assert path_under_artist(str(path), "Juniper Vale") is True


def test_album_identity_does_not_take_same_title_from_other_artist_folder(tmp_path):
    """Same album title under another artist folder must stay out of the host pool."""
    host = _touch(tmp_path / "music" / "Nia Coltrane" / "Greatest Hits" / "01 Low Tide.flac")
    foreign = _touch(tmp_path / "music" / "Juniper Vale" / "Greatest Hits" / "01 Static.flac")
    db = _open_db(tmp_path)
    _record(
        db,
        host,
        artist="Nia Coltrane",
        title="Low Tide",
        album="Greatest Hits",
        album_artist="Nia Coltrane",
        isrc="QZNIA0000777",
    )
    _record(
        db,
        foreign,
        artist="Juniper Vale",
        title="Static",
        album="Greatest Hits",
        album_artist=None,
        isrc="USESK0000777",
    )
    db.commit()

    pool = db.tracks_for_album_identity("Nia Coltrane", "Greatest Hits")
    assert any(row.get("path") == str(host) for row in pool)
    assert all(row.get("path") != str(foreign) for row in pool)
    db.close()


def test_stamp_track_finish_drops_catalog_quality_stash():
    """API responses must not leak the internal catalog-quality stash."""
    track = {"name": "Static", "artist": "Juniper Vale", "album": "Safe Room", "quality": "LOSSLESS"}
    stamp_track(track, {
        "path": "/music/Juniper Vale/Safe Room/01 Static.flac",
        "quality": "FLAC",
        "format": "FLAC",
        "codec": "flac",
    })
    assert "_catalog_quality" in track
    finish_stamp(track)
    assert "_catalog_quality" not in track
    assert track["quality"] == "FLAC"
