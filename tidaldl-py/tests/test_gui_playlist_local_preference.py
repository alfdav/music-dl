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

    def has_live_isrc(self, isrc):
        return bool(self.tracks_by_isrc(isrc))

    def primary_path_for_isrc(self, isrc):
        rows = self.tracks_by_isrc(isrc)
        return rows[0]["path"] if rows else None

    def all_tracks(self):
        if self._all_rows is not None:
            return list(self._all_rows)
        rows = []
        for vals in self.rows_by_isrc.values():
            rows.extend(vals)
        return rows

    def close(self):
        return None


def _patch_playlist_library_db(monkeypatch, playlists_api, fake_db):
    monkeypatch.setattr(playlists_api, "_get_playlist_db", lambda: fake_db)
    monkeypatch.setattr("tidal_dl.gui.api.search._get_library_db", lambda: fake_db)


def test_tidal_search_serializes_live_local_isrc_metadata(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import search as search_api

    local_path = tmp_path / "local.flac"
    local_path.touch()
    local_row = {
        "path": str(local_path),
        "quality": "44100Hz/24bit",
        "format": "FLAC",
        "codec": "flac",
    }
    monkeypatch.setattr(search_api, "_get_library_db", lambda: _FakePlaylistDB({"ISRC123": [local_row]}))

    result = search_api._serialize_track(_fake_track())

    assert result["is_local"] is True
    assert result["local_path"] == str(local_path)
    assert result["path"] == str(local_path)
    assert result["quality"] == "44100Hz/24bit"
    assert result["format"] == "FLAC"
    assert result["codec"] == "flac"


def test_tidal_search_stays_remote_without_live_local_isrc(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import search as search_api

    monkeypatch.setattr(search_api, "_get_library_db", lambda: _FakePlaylistDB({}))

    result = search_api._serialize_track(_fake_track(isrc="ISRC999"))

    assert result["is_local"] is False
    assert "local_path" not in result
    assert "path" not in result
    assert "format" not in result


def test_tidal_search_reads_isrc_rows_once_to_find_a_live_local_file(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import search as search_api

    live_path = tmp_path / "local.flac"
    live_path.touch()
    rows = [{"path": str(live_path), "quality": "LOSSLESS", "format": "FLAC"}]

    class CountingDB:
        def __init__(self):
            self.calls = []

        def has_live_isrc(self, isrc):
            self.calls.append("has_live_isrc")
            return True

        def primary_path_for_isrc(self, isrc):
            self.calls.append("primary_path_for_isrc")
            return rows[0]["path"]

        def tracks_by_isrc(self, isrc):
            self.calls.append("tracks_by_isrc")
            return rows

    db = CountingDB()
    monkeypatch.setattr(search_api, "_get_library_db", lambda: db)

    result = search_api._serialize_track(_fake_track())

    assert result["local_path"] == str(live_path)
    assert db.calls == ["tracks_by_isrc"]


def test_playlist_tracks_include_local_path_when_isrc_matches(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import playlists as playlists_api

    fake_track = _fake_track()
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        playlist=lambda playlist_id: SimpleNamespace(tracks=lambda: [fake_track]),
    )

    monkeypatch.setattr(playlists_api, "get_tidal", lambda: SimpleNamespace(session=fake_session, data=SimpleNamespace(access_token="a", refresh_token="r"), _ensure_token_fresh=lambda refresh_window_sec=300: True))
    _patch_playlist_library_db(
        monkeypatch,
        playlists_api,
        _FakePlaylistDB({"ISRC123": [{"path": "/music/local.flac", "artist": "Artist", "title": "Song", "album": "Album"}]}),
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

    monkeypatch.setattr(playlists_api, "get_tidal", lambda: SimpleNamespace(session=fake_session, data=SimpleNamespace(access_token="a", refresh_token="r"), _ensure_token_fresh=lambda refresh_window_sec=300: True))
    _patch_playlist_library_db(monkeypatch, playlists_api, _FakePlaylistDB({}))

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

    monkeypatch.setattr(playlists_api, "get_tidal", lambda: SimpleNamespace(session=fake_session, data=SimpleNamespace(access_token="a", refresh_token="r"), _ensure_token_fresh=lambda refresh_window_sec=300: True))
    _patch_playlist_library_db(
        monkeypatch,
        playlists_api,
        _FakePlaylistDB(
            {},
            all_rows=[{"path": "/music/mas-de-ti.flac", "artist": "Don Moen", "title": "Mas De Ti", "album": "Más De Ti"}],
        ),
    )
    monkeypatch.setattr(playlists_api, "_enqueue_playlist_downloads", lambda track_ids, request=None: queued.extend(track_ids))

    playlists_api._playlist_tracks_cache.clear()
    result = playlists_api.sync_playlist("pl-local-fallback")

    assert result == {"status": "up_to_date", "missing": 0, "total": 1}
    assert queued == []


def test_playlist_sync_skips_local_track_when_library_db_has_isrc_match(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import playlists as playlists_api

    fake_track = _fake_track(track_id=8, isrc="ISRC123")
    fake_session = SimpleNamespace(
        check_login=lambda: True,
        playlist=lambda playlist_id: SimpleNamespace(tracks=lambda: [fake_track]),
    )
    queued = []

    monkeypatch.setattr(playlists_api, "get_tidal", lambda: SimpleNamespace(session=fake_session, data=SimpleNamespace(access_token="a", refresh_token="r"), _ensure_token_fresh=lambda refresh_window_sec=300: True))
    _patch_playlist_library_db(
        monkeypatch,
        playlists_api,
        _FakePlaylistDB({"ISRC123": [{"path": "/music/local.flac", "artist": "Artist", "title": "Song", "album": "Album"}]}),
    )
    monkeypatch.setattr(playlists_api, "_enqueue_playlist_downloads", lambda track_ids, request=None: queued.extend(track_ids))

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

    monkeypatch.setattr(playlists_api, "get_tidal", lambda: SimpleNamespace(session=fake_session, data=SimpleNamespace(access_token="a", refresh_token="r"), _ensure_token_fresh=lambda refresh_window_sec=300: True))
    _patch_playlist_library_db(
        monkeypatch,
        playlists_api,
        _FakePlaylistDB(
            {},
            all_rows=[
                {"path": "/music/a.flac", "artist": "Artist", "title": "Song", "album": "Album A"},
                {"path": "/music/b.flac", "artist": "Artist", "title": "Song", "album": "Album B"},
            ],
        ),
    )
    monkeypatch.setattr(playlists_api, "_enqueue_playlist_downloads", lambda track_ids, request=None: queued.extend(track_ids))

    playlists_api._playlist_tracks_cache.clear()
    result = playlists_api.sync_playlist("pl-ambiguous")

    assert result == {"status": "syncing", "missing": 1, "total": 1}
    assert queued == [9]
