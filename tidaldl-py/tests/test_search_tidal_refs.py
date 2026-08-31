"""Search URL intake, album-title track fallback, and hybrid artist."""

from __future__ import annotations

import time
from types import SimpleNamespace
from urllib.parse import quote

from fastapi.testclient import TestClient

from tidal_dl.gui.tidal_ref import looks_like_web_url, parse_tidal_ref

CLASICOS_ALBUM = "Clásicos de la Provincia 30 Años (Remastered & Expanded)"
CLASICOS_TRACK = "La gota fría (Remastered 30 años)"
CLASICOS_ALBUM_ID = 330865537
CLASICOS_TRACK_ID = 330865538
CARLOS_ID = 3628717
TRACK_URL = "https://tidal.com/track/330865538/u"


def test_parse_tidal_track_urls_and_bare_id():
    expected = ("track", "330865538")
    assert parse_tidal_ref(TRACK_URL) == expected
    assert parse_tidal_ref("https://tidal.com/browse/track/330865538") == expected
    assert parse_tidal_ref("https://listen.tidal.com/track/330865538/u") == expected
    assert parse_tidal_ref("tidal.com/track/330865538") == expected
    assert parse_tidal_ref("330865538", type_hint="tracks") == expected


def test_parse_tidal_album_artist_playlist_urls():
    assert parse_tidal_ref("https://tidal.com/album/330865537") == ("album", "330865537")
    assert parse_tidal_ref("https://tidal.com/browse/artist/3628717/u") == ("artist", "3628717")
    assert parse_tidal_ref("https://listen.tidal.com/playlist/abc-def-123") == (
        "playlist",
        "abc-def-123",
    )
    assert parse_tidal_ref("330865537", type_hint="albums") == ("album", "330865537")


def test_parse_rejects_unknown_and_non_tidal_urls():
    assert parse_tidal_ref("https://tidal.com/unknown/999") is None
    assert parse_tidal_ref("https://evil.example/track/330865538") is None
    assert parse_tidal_ref(CLASICOS_ALBUM) is None
    assert looks_like_web_url(TRACK_URL) is True
    assert looks_like_web_url("tidal.com/track/330865538") is True
    assert looks_like_web_url("https://evil.example/x") is True
    assert looks_like_web_url(CLASICOS_ALBUM) is False
    planted = "https://evil.example/tidal.com/track/330865538"
    assert looks_like_web_url(planted) is True
    assert parse_tidal_ref(planted) is None
    assert looks_like_web_url("evil.example/tidal.com/track/1") is False
    assert parse_tidal_ref("evil.example/tidal.com/track/1") is None


def test_percent_title_is_not_a_url_and_does_not_raise():
    query = "100% Pure Love"
    assert looks_like_web_url(query) is False
    assert parse_tidal_ref(query) is None
    assert looks_like_web_url("[::1%]") is False


def _track(track_id, name, artist, album_name, album_id, artist_id=None):
    album = SimpleNamespace(
        id=album_id,
        name=album_name,
        image=lambda size: f"cover-{album_id}",
    )
    return SimpleNamespace(
        id=track_id,
        name=name,
        full_name=name,
        artists=[SimpleNamespace(name=artist, id=artist_id)],
        album=album,
        duration=180,
        audio_quality="HI_RES_LOSSLESS",
        isrc="",
        media_metadata_tags=["HIRES_LOSSLESS"],
    )


def _album(album_id, name, artist, tracks):
    return SimpleNamespace(
        id=album_id,
        name=name,
        artist=SimpleNamespace(name=artist),
        num_tracks=len(tracks),
        tracks=lambda: list(tracks),
        image=lambda size: f"cover-{album_id}",
        media_metadata_tags=["HIRES_LOSSLESS"],
        audio_quality="HI_RES_LOSSLESS",
        audio_modes=[],
        explicit=False,
    )


def _artist(artist_id, name, albums):
    return SimpleNamespace(
        id=artist_id,
        name=name,
        image=lambda size: f"artist-{artist_id}",
        roles=[],
        get_albums=lambda limit=50: list(albums),
        get_ep_singles=lambda limit=50: [],
    )


def _logged_in_tidal(session):
    class FakeTidal:
        def __init__(self):
            self.session = session
            self.data = SimpleNamespace(
                access_token="token",
                refresh_token="refresh",
                expiry_time=time.time() + 3600,
            )

        def _ensure_token_fresh(self, refresh_window_sec=300):
            return True

    return FakeTidal


def _search_client(monkeypatch, session):
    from tidal_dl.gui import create_app
    from tidal_dl.gui.api import search as search_api

    monkeypatch.setattr(search_api, "Tidal", _logged_in_tidal(session))
    monkeypatch.setattr(search_api, "_get_library_db", lambda: SimpleNamespace(
        tracks_by_isrc=lambda isrc: [],
    ))
    return TestClient(create_app(port=8765))


class _ResolveSession:
    def __init__(self):
        self.searches: list[str] = []
        clasicos_track = _track(
            CLASICOS_TRACK_ID,
            CLASICOS_TRACK,
            "Carlos Vives",
            CLASICOS_ALBUM,
            CLASICOS_ALBUM_ID,
            artist_id=CARLOS_ID,
        )
        self._track = clasicos_track
        self._album = _album(CLASICOS_ALBUM_ID, CLASICOS_ALBUM, "Carlos Vives", [clasicos_track])
        self._artist = _artist(CARLOS_ID, "Carlos Vives", [self._album])

    def check_login(self):
        return True

    def search(self, q, models=None, limit=50, offset=0):
        self.searches.append(q)
        return {"tracks": [], "albums": [], "artists": [], "playlists": []}

    def track(self, track_id, with_album=False):
        if int(track_id) != CLASICOS_TRACK_ID:
            raise RuntimeError("unknown track")
        return self._track

    def album(self, album_id):
        if int(album_id) != CLASICOS_ALBUM_ID:
            raise RuntimeError("unknown album")
        return self._album

    def artist(self, artist_id):
        if int(artist_id) != CARLOS_ID:
            raise RuntimeError("unknown artist")
        return self._artist

    def playlist(self, playlist_id):
        raise RuntimeError("unknown playlist")


def test_track_url_resolves_by_id_without_calling_search(monkeypatch):
    session = _ResolveSession()
    client = _search_client(monkeypatch, session)

    resp = client.get(
        f"/api/search?q={quote(TRACK_URL, safe='')}&type=tracks",
        headers={"host": "localhost:8765"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert session.searches == []
    assert data["tracks"][0]["id"] == CLASICOS_TRACK_ID
    assert data["tracks"][0]["name"] == CLASICOS_TRACK
    assert data["tracks"][0]["album_id"] == CLASICOS_ALBUM_ID
    assert data["resolve"]["kind"] == "track"
    assert data["resolve"]["id"] == CLASICOS_TRACK_ID


def test_bare_track_id_resolves_without_search(monkeypatch):
    session = _ResolveSession()
    client = _search_client(monkeypatch, session)

    resp = client.get(
        f"/api/search?q={CLASICOS_TRACK_ID}&type=tracks",
        headers={"host": "localhost:8765"},
    )

    assert resp.status_code == 200
    assert session.searches == []
    assert resp.json()["tracks"][0]["id"] == CLASICOS_TRACK_ID


def test_unknown_url_returns_error_without_search(monkeypatch):
    session = _ResolveSession()
    client = _search_client(monkeypatch, session)
    bad = "https://tidal.com/unknown/999"

    resp = client.get(
        f"/api/search?q={quote(bad, safe='')}&type=tracks",
        headers={"host": "localhost:8765"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert session.searches == []
    assert data["tracks"] == []
    assert data["total"] == 0
    assert data["error"]


def test_planted_tidal_path_is_not_resolved_or_searched(monkeypatch):
    session = _ResolveSession()
    client = _search_client(monkeypatch, session)
    planted = "https://evil.example/tidal.com/track/330865538"

    resp = client.get(
        f"/api/search?q={quote(planted, safe='')}&type=tracks",
        headers={"host": "localhost:8765"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert session.searches == []
    assert data["tracks"] == []
    assert data["error"] == "Not a recognized Tidal URL"


def test_track_url_can_be_queued_for_download_without_search(monkeypatch, client):
    from tidal_dl.gui.api import search as search_api

    session = _ResolveSession()
    monkeypatch.setattr(search_api, "Tidal", _logged_in_tidal(session))
    monkeypatch.setattr(search_api, "_get_library_db", lambda: SimpleNamespace(
        tracks_by_isrc=lambda isrc: [],
    ))
    monkeypatch.setattr(
        "tidal_dl.gui.api.settings.require_tidal",
        lambda tidal=None: tidal,
    )

    search_resp = client.get(
        f"/api/search?q={quote(TRACK_URL, safe='')}&type=tracks",
        headers=client._host_header,
    )
    track_id = search_resp.json()["tracks"][0]["id"]
    assert track_id == CLASICOS_TRACK_ID
    assert session.searches == []

    dl = client.post(
        "/api/download",
        json={"track_ids": [track_id]},
        headers=client._headers,
    )

    assert dl.status_code == 200
    assert dl.json()["status"] == "queued"
    assert dl.json()["count"] >= 1
    assert session.searches == []


def test_album_title_track_search_surfaces_clasicos_album_tracks(monkeypatch):
    from tidalapi.album import Album
    from tidalapi.media import Track

    clasicos_track = _track(
        CLASICOS_TRACK_ID,
        CLASICOS_TRACK,
        "Carlos Vives",
        CLASICOS_ALBUM,
        CLASICOS_ALBUM_ID,
        artist_id=CARLOS_ID,
    )
    clasicos_album = _album(
        CLASICOS_ALBUM_ID, CLASICOS_ALBUM, "Carlos Vives", [clasicos_track]
    )

    class Session:
        def __init__(self):
            self.searches = []

        def check_login(self):
            return True

        def search(self, q, models=None, limit=50, offset=0):
            self.searches.append((q, models[0] if models else None))
            model = models[0] if models else None
            if model is Track:
                return {"tracks": []}
            if model is Album:
                return {"albums": [clasicos_album]}
            return {}

        def album(self, album_id):
            assert int(album_id) == CLASICOS_ALBUM_ID
            return clasicos_album

        def track(self, *_args, **_kwargs):
            raise AssertionError("album-title search must not get-by-id")

    session = Session()
    client = _search_client(monkeypatch, session)

    resp = client.get(
        f"/api/search?q={quote(CLASICOS_ALBUM)}&type=tracks",
        headers={"host": "localhost:8765"},
    )

    assert resp.status_code == 200
    data = resp.json()
    ids = [t["id"] for t in data["tracks"]]
    assert CLASICOS_TRACK_ID in ids
    assert any(t.get("album_id") == CLASICOS_ALBUM_ID for t in data["tracks"])
    assert Track in {model for _, model in session.searches}
    assert Album in {model for _, model in session.searches}


def test_artist_name_track_search_keeps_track_hits(monkeypatch):
    from tidalapi.album import Album
    from tidalapi.media import Track

    hit_a = _track(11, "La tierra del olvido", "Carlos Vives", "La Tierra del Olvido", 100, artist_id=CARLOS_ID)
    hit_b = _track(12, "Pa' Mayte", "Carlos Vives", "La Tierra del Olvido", 100, artist_id=CARLOS_ID)
    self_titled = _track(99, "Carlos Vives", "Carlos Vives", "Carlos Vives", 200, artist_id=CARLOS_ID)
    self_titled_album = _album(200, "Carlos Vives", "Carlos Vives", [self_titled])

    class Session:
        def __init__(self):
            self.album_searches = 0

        def check_login(self):
            return True

        def search(self, q, models=None, limit=50, offset=0):
            model = models[0] if models else None
            if model is Track:
                return {"tracks": [hit_a, hit_b]}
            if model is Album:
                self.album_searches += 1
                return {"albums": [self_titled_album]}
            return {}

        def album(self, album_id):
            return self_titled_album

    session = Session()
    client = _search_client(monkeypatch, session)

    resp = client.get(
        f"/api/search?q={quote('Carlos Vives')}&type=tracks",
        headers={"host": "localhost:8765"},
    )

    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()["tracks"]]
    assert ids == [11, 12]
    assert 99 not in ids
    assert session.album_searches == 0


def test_percent_title_search_does_not_500(monkeypatch):
    class Session:
        def check_login(self):
            return True

        def search(self, q, models=None, limit=50, offset=0):
            return {"tracks": [], "albums": [], "artists": [], "playlists": []}

    client = _search_client(monkeypatch, Session())
    resp = client.get(
        f"/api/search?q={quote('100% Pure Love')}&type=tracks",
        headers={"host": "localhost:8765"},
    )
    assert resp.status_code == 200
    assert resp.json()["tracks"] == []


def test_library_album_search_does_not_regroup_the_whole_library(tmp_path, monkeypatch):
    from tidal_dl.gui.api import library as library_api
    from tidal_dl.helper.library_db import LibraryDB

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    db.record(
        "/music/vallenato/grandes.flac",
        status="tagged",
        artist="Various",
        title="Track",
        album="Los Grandes Del Vallenato",
        duration=180,
        art_available=False,
    )
    db.commit()
    monkeypatch.setattr(library_api, "_get_db", lambda: db)

    def fail_cards(*_args, **_kwargs):
        raise AssertionError("library album search must not call _album_cards")

    monkeypatch.setattr(library_api, "_album_cards", fail_cards)

    payload = library_api.library_search(q="Los Grandes Del Vallenato", type="albums", limit=20)

    assert payload["total"] == 1
    assert payload["albums"][0]["name"] == "Los Grandes Del Vallenato"
    db.close()


def test_artist_discography_is_not_library_only(monkeypatch):
    session = _ResolveSession()
    client = _search_client(monkeypatch, session)

    resp = client.get(
        f"/api/artists/{CARLOS_ID}/albums",
        headers={"host": "localhost:8765"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["artist"]["id"] == CARLOS_ID
    assert any(album["id"] == CLASICOS_ALBUM_ID for album in data["albums"])
    assert session.searches == []
