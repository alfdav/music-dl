from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _FakeAlbumDB:
    def __init__(self, tracks):
        self._tracks = tracks

    def album_tracks(self, artist, album):
        if artist == "Various Artists":
            return [row for row in self._tracks if row.get("album") == album]
        return [
            row for row in self._tracks
            if row.get("artist") == artist and row.get("album") == album
        ]

    def close(self):
        return None


def _track(name, artist, album, track_id):
    return SimpleNamespace(
        id=track_id,
        name=name,
        full_name=name,
        artists=[SimpleNamespace(name=artist)],
        album=SimpleNamespace(id=track_id + 1000, name=album),
        duration=180,
        audio_quality="LOSSLESS",
        isrc=f"ISRC{track_id}",
        media_metadata_tags=[],
    )


def _album(album_id, name, artist, tracks):
    return SimpleNamespace(
        id=album_id,
        name=name,
        artist=SimpleNamespace(name=artist),
        num_tracks=len(tracks),
        tracks=lambda: list(tracks),
        image=lambda size: f"cover-{album_id}",
    )


def _serialize_stub(track, _library_db=None):
    artist_name = ", ".join(a.name for a in getattr(track, "artists", []) if getattr(a, "name", None))
    album = getattr(track, "album", None)
    return {
        "id": track.id,
        "name": track.full_name,
        "artist": artist_name,
        "album": getattr(album, "name", ""),
        "quality": getattr(track, "audio_quality", ""),
        "isrc": getattr(track, "isrc", ""),
        "is_local": False,
    }


def test_album_lookup_prefers_candidate_with_local_track_overlap(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import albums as albums_api

    live_a = tmp_path / "1.flac"
    live_b = tmp_path / "2.flac"
    live_a.write_bytes(b"fLaC")
    live_b.write_bytes(b"fLaC")
    local_tracks = [
        {"title": "Mas De Ti", "artist": "Don Moen, Paul Wilbur, Aline Barros", "album": "Más De Ti (En Vivo)", "path": str(live_a)},
        {"title": "Celebrad Al Dios De Amor", "artist": "Don Moen, Paul Wilbur, Aline Barros", "album": "Más De Ti (En Vivo)", "path": str(live_b)},
    ]

    wrong = _album(
        1,
        "En Vivo",
        "Los Enanitos Verdes",
        [
            _track("Amores Lejanos (En Vivo)", "Los Enanitos Verdes", "En Vivo", 11),
            _track("Tequila (En Vivo)", "Los Enanitos Verdes", "En Vivo", 12),
        ],
    )
    correct = _album(
        2,
        "Más De Ti (En Vivo)",
        "Don Moen",
        [
            _track("Mas De Ti", "Don Moen, Paul Wilbur, Aline Barros", "Más De Ti (En Vivo)", 21),
            _track("Celebrad Al Dios De Amor", "Don Moen, Paul Wilbur, Aline Barros", "Más De Ti (En Vivo)", 22),
        ],
    )
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        search=lambda query, models=None, limit=20: {"albums": [wrong, correct]},
    )

    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))
    monkeypatch.setattr(albums_api, "_get_library_db", lambda: _FakeAlbumDB(local_tracks))
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_stub)

    result = albums_api.album_lookup("Don Moen, Paul Wilbur, Aline Barros", "Más De Ti (En Vivo)")

    assert result["album"]["id"] == 2
    assert result["album"]["artist"] == "Don Moen"
    assert [t["name"] for t in result["tracks"]] == ["Mas De Ti", "Celebrad Al Dios De Amor"]
    assert [t["is_local"] for t in result["tracks"]] == [True, True]
    assert [t.get("path") for t in result["tracks"]] == [str(live_a), str(live_b)]
    assert [t.get("local_path") for t in result["tracks"]] == [str(live_a), str(live_b)]
    assert result["missing_count"] == 0


def test_album_lookup_rejects_weak_match_with_no_track_overlap(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import albums as albums_api

    local_tracks = [
        {"title": "Mas De Ti", "artist": "Don Moen, Paul Wilbur, Aline Barros", "album": "Más De Ti (En Vivo)", "path": "/music/1.flac"},
    ]

    wrong = _album(
        1,
        "En Vivo",
        "Los Enanitos Verdes",
        [_track("Amores Lejanos (En Vivo)", "Los Enanitos Verdes", "En Vivo", 11)],
    )
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        search=lambda query, models=None, limit=20: {"albums": [wrong]},
    )

    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))
    monkeypatch.setattr(albums_api, "_get_library_db", lambda: _FakeAlbumDB(local_tracks))
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_stub)

    with pytest.raises(HTTPException) as exc:
        albums_api.album_lookup("Don Moen, Paul Wilbur, Aline Barros", "Más De Ti (En Vivo)")

    assert exc.value.status_code == 404
    assert "confident" in exc.value.detail.lower()


def test_album_metadata_score_does_not_reward_blank_candidate_fields(clear_singletons):
    from tidal_dl.gui.api import albums as albums_api

    score = albums_api._album_metadata_score("", "", "Target Album", "Target Artist")

    assert score == 0.0



def test_album_lookup_ignores_empty_normalized_local_titles(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import albums as albums_api

    local_tracks = [
        {"title": "!!!", "artist": "Don Moen", "album": "Más De Ti (En Vivo)", "path": "/music/1.flac"},
    ]

    correct = _album(
        2,
        "Más De Ti (En Vivo)",
        "Don Moen",
        [
            _track("Mas De Ti", "Don Moen", "Más De Ti (En Vivo)", 21),
        ],
    )
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        search=lambda query, models=None, limit=20: {"albums": [correct]},
    )

    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))
    monkeypatch.setattr(albums_api, "_get_library_db", lambda: _FakeAlbumDB(local_tracks))
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_stub)

    result = albums_api.album_lookup("Don Moen", "Más De Ti (En Vivo)")

    assert result["album"]["id"] == 2
    assert result["missing_count"] == 1


def test_album_lookup_marks_local_when_tidal_album_string_differs(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import albums as albums_api

    live = tmp_path / "Sandy, PAPO" / "Otra Vez" / "Huelepega.flac"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"fLaC")
    local_tracks = [
        {
            "title": "Huelepega",
            "artist": "Sandy, PAPO",
            "album": "Otra Vez",
            "path": str(live),
        },
    ]
    tidal = _album(
        9,
        "Otra Vez (Explicit)",
        "Sandy",
        [_track("Huelepega", "Sandy, PAPO", "Otra Vez (Explicit)", 91)],
    )
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        search=lambda query, models=None, limit=20: {"albums": [tidal]},
    )

    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))
    monkeypatch.setattr(albums_api, "_get_library_db", lambda: _FakeAlbumDB(local_tracks))
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_stub)

    result = albums_api.album_lookup("Sandy, PAPO", "Otra Vez")

    assert result["tracks"][0]["is_local"] is True
    assert result["tracks"][0]["path"] == str(live)
    assert result["tracks"][0]["local_path"] == str(live)
    assert result["missing_count"] == 0


def test_album_lookup_does_not_mark_same_title_from_a_different_album(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import albums as albums_api

    other = tmp_path / "Other Artist" / "Hits" / "Other Song.flac"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"fLaC")
    local_tracks = [
        {
            "title": "Huelepega",
            "artist": "Sandy, PAPO",
            "album": "Otra Vez",
            "path": "/music/Sandy, PAPO/Otra Vez/Huelepega.flac",
        },
        {
            "title": "Other Song",
            "artist": "Other Artist",
            "album": "Hits",
            "path": str(other),
        },
    ]
    compilation = _album(
        3,
        "Hits",
        "Other Artist",
        [
            _track("Huelepega", "Sandy, PAPO", "Hits", 31),
            _track("Other Song", "Other Artist", "Hits", 32),
        ],
    )
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        search=lambda query, models=None, limit=20: {"albums": [compilation]},
    )

    def _serialize_isrc_hit(track, _library_db=None):
        data = _serialize_stub(track, _library_db)
        if track.id == 31:
            data["is_local"] = True
            data["local_path"] = "/music/Sandy, PAPO/Otra Vez/Huelepega.flac"
            data["path"] = "/music/Sandy, PAPO/Otra Vez/Huelepega.flac"
        return data

    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))
    monkeypatch.setattr(albums_api, "_get_library_db", lambda: _FakeAlbumDB(local_tracks))
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_isrc_hit)

    result = albums_api.album_lookup("Other Artist", "Hits")

    by_name = {track["name"]: track for track in result["tracks"]}
    assert by_name["Huelepega"]["is_local"] is False
    assert by_name["Huelepega"].get("path") in (None, "")
    assert by_name["Huelepega"].get("local_path") in (None, "")
    assert by_name["Other Song"]["is_local"] is True
    assert by_name["Other Song"]["path"] == str(other)


def test_album_lookup_does_not_stamp_local_when_indexed_file_is_missing(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import albums as albums_api

    local_tracks = [
        {
            "title": "Huelepega",
            "artist": "Sandy, PAPO",
            "album": "Otra Vez",
            "path": "/music/does-not-exist/Huelepega.flac",
        },
    ]
    tidal = _album(
        9,
        "Otra Vez",
        "Sandy",
        [_track("Huelepega", "Sandy, PAPO", "Otra Vez", 91)],
    )
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        search=lambda query, models=None, limit=20: {"albums": [tidal]},
    )

    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))
    monkeypatch.setattr(albums_api, "_get_library_db", lambda: _FakeAlbumDB(local_tracks))
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_stub)

    result = albums_api.album_lookup("Sandy, PAPO", "Otra Vez")

    track = result["tracks"][0]
    assert track["is_local"] is False
    assert track.get("playable") is not True
    assert track.get("path") in (None, "")
    assert track.get("local_path") in (None, "")
    assert result["missing_count"] == 1


def test_album_lookup_stamps_local_only_when_file_exists(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import albums as albums_api

    live = tmp_path / "Sandy, PAPO" / "Otra Vez" / "Huelepega.flac"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"fLaC")
    local_tracks = [
        {
            "title": "Huelepega",
            "artist": "Sandy, PAPO",
            "album": "Otra Vez",
            "path": str(live),
        },
    ]
    tidal = _album(
        9,
        "Otra Vez",
        "Sandy",
        [_track("Huelepega", "Sandy, PAPO", "Otra Vez", 91)],
    )
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        search=lambda query, models=None, limit=20: {"albums": [tidal]},
    )

    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))
    monkeypatch.setattr(albums_api, "_get_library_db", lambda: _FakeAlbumDB(local_tracks))
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_stub)

    result = albums_api.album_lookup("Sandy, PAPO", "Otra Vez")

    track = result["tracks"][0]
    assert track["is_local"] is True
    assert track["playable"] is True
    assert track["path"] == str(live)
    assert track["local_path"] == str(live)
    assert result["missing_count"] == 0


def test_album_lookup_persists_artist_album_layout_heal(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import albums as albums_api
    from tidal_dl.helper.library_db import LibraryDB

    old = tmp_path / "Artist One" / "Artist One - First Album" / "01 - Song.flac"
    live = tmp_path / "Artist One" / "First Album" / "01 - Song.flac"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"fLaC")
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    db.record(
        str(old),
        status="tagged",
        artist="Artist One",
        title="Song",
        album="First Album",
        duration=180,
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
        metadata_complete=True,
    )
    db.commit()
    db.close()

    tidal = _album(
        9,
        "First Album",
        "Artist One",
        [_track("Song", "Artist One", "First Album", 91)],
    )
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        search=lambda query, models=None, limit=20: {"albums": [tidal]},
    )

    def _open_library_db():
        handle = LibraryDB(tmp_path / "library.db")
        handle.open()
        return handle

    monkeypatch.setattr(albums_api, "Tidal", lambda: SimpleNamespace(session=fake_session))
    monkeypatch.setattr(albums_api, "_get_library_db", _open_library_db)
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_stub)

    result = albums_api.album_lookup("Artist One", "First Album")

    track = result["tracks"][0]
    assert track["is_local"] is True
    assert track["playable"] is True
    assert track["path"] == str(live)
    assert track["local_path"] == str(live)

    check = LibraryDB(tmp_path / "library.db")
    check.open()
    assert check.get(str(live)) is not None
    assert check.get(str(old)) is None
    check.close()
