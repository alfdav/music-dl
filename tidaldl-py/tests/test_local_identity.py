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
    _patch_search_db(monkeypatch, db)

    tidal_track = _tidal_track(
        track_id=61,
        name="Harbor Light",
        artist="Nia Coltrane",
        album="Night Letters",
        isrc="QZNIA0000061",
    )
    tidal_album = _tidal_album(60, "Night Letters", "Nia Coltrane", [tidal_track])
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        album=lambda album_id: tidal_album,
    )
    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))

    result = albums_api.album_tracks(60)

    assert result["tracks"][0]["is_local"] is True
    assert result["tracks"][0]["local_path"] == str(live)
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
