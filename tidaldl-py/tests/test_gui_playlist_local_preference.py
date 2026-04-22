from types import SimpleNamespace


def _fake_track(track_id=1, *, isrc="ISRC123", name="Song", artist="Artist", album="Album"):
    album_obj = SimpleNamespace(id=99, name=album, image=lambda size: "cover-url")
    artist_obj = SimpleNamespace(name=artist)
    return SimpleNamespace(
        id=track_id,
        name=name,
        full_name=name,
        artists=[artist_obj],
        album=album_obj,
        duration=180,
        audio_quality="LOSSLESS",
        isrc=isrc,
        media_metadata_tags=[],
    )


class _FakePlaylistDB:
    def __init__(self, rows_by_isrc, all_rows=None):
        self.rows_by_isrc = rows_by_isrc
        self._all_rows = all_rows

    def tracks_by_isrc(self, isrc):
        return list(self.rows_by_isrc.get(isrc, []))

    def all_tracks(self):
        if self._all_rows is not None:
            return list(self._all_rows)
        rows = []
        for vals in self.rows_by_isrc.values():
            rows.extend(vals)
        return rows

    def close(self):
        return None


def test_playlist_tracks_include_local_path_when_isrc_matches(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import playlists as playlists_api

    fake_track = _fake_track()
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        playlist=lambda playlist_id: SimpleNamespace(tracks=lambda: [fake_track]),
    )

    monkeypatch.setattr(playlists_api, "get_tidal_session", lambda: fake_session)
    monkeypatch.setattr(playlists_api, "_get_isrc_index", lambda: SimpleNamespace(contains=lambda isrc: True))
    monkeypatch.setattr(
        playlists_api,
        "_get_playlist_db",
        lambda: _FakePlaylistDB({"ISRC123": [{"path": "/music/local.flac", "artist": "Artist", "title": "Song", "album": "Album"}]}),
    )

    playlists_api._playlist_tracks_cache.clear()
    data = playlists_api.playlist_tracks("pl-local")

    assert data["tracks"][0]["is_local"] is True
    assert data["tracks"][0]["local_path"] == "/music/local.flac"


def test_playlist_tracks_fall_back_to_stream_when_no_local_match(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import playlists as playlists_api

    fake_track = _fake_track(isrc="ISRC999")
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        playlist=lambda playlist_id: SimpleNamespace(tracks=lambda: [fake_track]),
    )

    monkeypatch.setattr(playlists_api, "get_tidal_session", lambda: fake_session)
    monkeypatch.setattr(playlists_api, "_get_isrc_index", lambda: SimpleNamespace(contains=lambda isrc: False))
    monkeypatch.setattr(playlists_api, "_get_playlist_db", lambda: _FakePlaylistDB({}))

    playlists_api._playlist_tracks_cache.clear()
    data = playlists_api.playlist_tracks("pl-stream")

    assert data["tracks"][0]["is_local"] is False
    assert data["tracks"][0].get("local_path") in (None, "")


def test_playlist_sync_uses_same_local_match_logic_as_playlist_view(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import playlists as playlists_api

    fake_track = _fake_track(track_id=7, isrc="", name="Mas De Ti", artist="Don Moen", album="Más De Ti")
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        playlist=lambda playlist_id: SimpleNamespace(tracks=lambda: [fake_track]),
    )
    queued = []

    monkeypatch.setattr(playlists_api, "get_tidal_session", lambda: fake_session)
    monkeypatch.setattr(playlists_api, "_get_isrc_index", lambda: SimpleNamespace(contains=lambda isrc: False))
    monkeypatch.setattr(
        playlists_api,
        "_get_playlist_db",
        lambda: _FakePlaylistDB(
            {},
            all_rows=[{"path": "/music/mas-de-ti.flac", "artist": "Don Moen", "title": "Mas De Ti", "album": "Más De Ti"}],
        ),
    )
    monkeypatch.setattr("tidal_dl.gui.api.downloads.trigger_download", lambda track_ids: queued.extend(track_ids))

    playlists_api._playlist_tracks_cache.clear()
    result = playlists_api.sync_playlist("pl-local-fallback")

    assert result == {"status": "up_to_date", "missing": 0, "total": 1}
    assert queued == []


def test_playlist_sync_skips_local_track_when_isrc_index_is_stale(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import playlists as playlists_api

    fake_track = _fake_track(track_id=8, isrc="ISRC123")
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        playlist=lambda playlist_id: SimpleNamespace(tracks=lambda: [fake_track]),
    )
    queued = []

    monkeypatch.setattr(playlists_api, "get_tidal_session", lambda: fake_session)
    monkeypatch.setattr(playlists_api, "_get_isrc_index", lambda: SimpleNamespace(contains=lambda isrc: False))
    monkeypatch.setattr(
        playlists_api,
        "_get_playlist_db",
        lambda: _FakePlaylistDB({"ISRC123": [{"path": "/music/local.flac", "artist": "Artist", "title": "Song", "album": "Album"}]}),
    )
    monkeypatch.setattr("tidal_dl.gui.api.downloads.trigger_download", lambda track_ids: queued.extend(track_ids))

    playlists_api._playlist_tracks_cache.clear()
    result = playlists_api.sync_playlist("pl-stale-index")

    assert result == {"status": "up_to_date", "missing": 0, "total": 1}
    assert queued == []


def test_playlist_sync_downloads_when_title_artist_match_is_ambiguous(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import playlists as playlists_api

    fake_track = _fake_track(track_id=9, isrc="", name="Song", artist="Artist", album="Wanted Album")
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        playlist=lambda playlist_id: SimpleNamespace(tracks=lambda: [fake_track]),
    )
    queued = []

    monkeypatch.setattr(playlists_api, "get_tidal_session", lambda: fake_session)
    monkeypatch.setattr(playlists_api, "_get_isrc_index", lambda: SimpleNamespace(contains=lambda isrc: False))
    monkeypatch.setattr(
        playlists_api,
        "_get_playlist_db",
        lambda: _FakePlaylistDB(
            {},
            all_rows=[
                {"path": "/music/a.flac", "artist": "Artist", "title": "Song", "album": "Album A"},
                {"path": "/music/b.flac", "artist": "Artist", "title": "Song", "album": "Album B"},
            ],
        ),
    )
    monkeypatch.setattr("tidal_dl.gui.api.downloads.trigger_download", lambda track_ids: queued.extend(track_ids))

    playlists_api._playlist_tracks_cache.clear()
    result = playlists_api.sync_playlist("pl-ambiguous")

    assert result == {"status": "syncing", "missing": 1, "total": 1}
    assert queued == [9]
