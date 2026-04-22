from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _FakeAlbumDB:
    def __init__(self, tracks):
        self._tracks = tracks

    def album_tracks(self, artist, album):
        return list(self._tracks)

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


def _serialize_stub(track, _isrc_index):
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


def test_album_lookup_prefers_candidate_with_local_track_overlap(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import albums as albums_api

    local_tracks = [
        {"title": "Mas De Ti", "artist": "Don Moen, Paul Wilbur, Aline Barros", "album": "Más De Ti (En Vivo)", "path": "/music/1.flac"},
        {"title": "Celebrad Al Dios De Amor", "artist": "Don Moen, Paul Wilbur, Aline Barros", "album": "Más De Ti (En Vivo)", "path": "/music/2.flac"},
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
    monkeypatch.setattr(albums_api, "_get_isrc_index", lambda: SimpleNamespace())
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_stub)

    result = albums_api.album_lookup("Don Moen, Paul Wilbur, Aline Barros", "Más De Ti (En Vivo)")

    assert result["album"]["id"] == 2
    assert result["album"]["artist"] == "Don Moen"
    assert [t["name"] for t in result["tracks"]] == ["Mas De Ti", "Celebrad Al Dios De Amor"]
    assert [t["is_local"] for t in result["tracks"]] == [True, True]
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
    monkeypatch.setattr(albums_api, "_get_isrc_index", lambda: SimpleNamespace())
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
    monkeypatch.setattr(albums_api, "_get_isrc_index", lambda: SimpleNamespace())
    monkeypatch.setattr(albums_api, "_serialize_track", _serialize_stub)

    result = albums_api.album_lookup("Don Moen", "Más De Ti (En Vivo)")

    assert result["album"]["id"] == 2
    assert result["missing_count"] == 1
