"""Upgrade identity: cloned ISRC must not auto-match different titles."""

from types import SimpleNamespace

CLONED_ISRC = "USJ3V1497673"
CLONED_TIDAL_ID = 241908392


def _track(*, name="Song", artists=None, duration=180, track_id=123, isrc=CLONED_ISRC):
    return SimpleNamespace(
        id=track_id,
        name=name,
        full_name=name,
        artists=[SimpleNamespace(name=a) for a in (artists or ["Artist"])],
        artist=SimpleNamespace(name=(artists or ["Artist"])[0]),
        duration=duration,
        isrc=isrc,
        audio_quality="HI_RES_LOSSLESS",
        media_metadata_tags=["HI_RES_LOSSLESS"],
    )


class _Session:
    def __init__(self, tracks):
        self.tracks = tracks

    def search(self, query, models=None, limit=10):
        return {"tracks": self.tracks}


def _cloned_playlist_rows():
    return [
        {"path": "/playlists/Aylaylay.flac", "title": "Aylaylay", "artist": "Artist",
         "album": "Dump", "isrc": CLONED_ISRC, "quality": "HIGH", "format": "M4A", "codec": "aac",
         "duration": 180},
        {"path": "/playlists/Golpe.flac", "title": "Golpe De Alabanza", "artist": "Artist",
         "album": "Dump", "isrc": CLONED_ISRC, "quality": "HIGH", "format": "M4A", "codec": "aac",
         "duration": 200},
        {"path": "/playlists/Hermanda.flac", "title": "La Hermanda", "artist": "Artist",
         "album": "Dump", "isrc": CLONED_ISRC, "quality": "HIGH", "format": "M4A", "codec": "aac",
         "duration": 210},
        {"path": "/playlists/Patras.flac", "title": "Patras", "artist": "Artist",
         "album": "Dump", "isrc": CLONED_ISRC, "quality": "HIGH", "format": "M4A", "codec": "aac",
         "duration": 190},
    ]


def test_same_title_shared_isrc_is_not_uncertain():
    from tidal_dl.gui.api.upgrade import _colliding_isrcs, _titles_compatible

    assert _titles_compatible("Aylaylay", "Aylaylay (Live)")
    assert _colliding_isrcs([
        {"isrc": CLONED_ISRC, "title": "Aylaylay"},
        {"isrc": CLONED_ISRC, "title": "Aylaylay"},
    ]) == set()


def test_probe_isrc_skips_when_titles_differ():
    from tidal_dl.gui.api.upgrade import _probe_tidal_isrc

    session = _Session([_track(name="Aylaylay", track_id=CLONED_TIDAL_ID)])

    result = _probe_tidal_isrc(session, CLONED_ISRC, title="Golpe De Alabanza", artist="Artist")

    assert result is None


def test_probe_isrc_matches_when_title_and_isrc_agree():
    from tidal_dl.gui.api.upgrade import _probe_tidal_isrc

    session = _Session([_track(name="Aylaylay", track_id=CLONED_TIDAL_ID)])

    result = _probe_tidal_isrc(session, CLONED_ISRC, title="Aylaylay", artist="Artist")

    assert result is not None
    assert result["tidal_track_id"] == CLONED_TIDAL_ID


def test_probe_prefers_title_artist_duration_over_cloned_isrc():
    from tidal_dl.gui.api.upgrade import _probe_tidal_isrc

    session = _Session([
        _track(name="Aylaylay", track_id=CLONED_TIDAL_ID, duration=180),
        _track(name="Golpe De Alabanza", artists=["Artist"], track_id=99, isrc="US-REAL-GOLPE", duration=200),
    ])

    result = _probe_tidal_isrc(session, CLONED_ISRC, title="Golpe De Alabanza", artist="Artist")

    assert result is not None
    assert result["tidal_track_id"] == 99


def test_rebuild_skips_cloned_isrc_with_different_titles(tmp_path, monkeypatch):
    from tidal_dl.gui.api import upgrade as upgrade_api
    from tidal_dl.helper.library_db import LibraryDB

    db_path = tmp_path / "library.db"
    db = LibraryDB(db_path)
    db.open()
    for row in _cloned_playlist_rows():
        db.record(
            row["path"],
            status="tagged",
            isrc=row["isrc"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            quality=row["quality"],
            fmt=row["format"],
            codec=row["codec"],
            duration=row["duration"],
        )
    db.record(
        "/music/Real.flac",
        status="tagged",
        isrc="USOTHER0000001",
        title="Real Song",
        artist="Artist",
        album="Album",
        quality="HIGH",
        fmt="M4A",
        codec="aac",
    )
    db.set_probe(CLONED_ISRC, CLONED_TIDAL_ID, "HI_RES_LOSSLESS")
    db.set_probe("USOTHER0000001", 1, "HI_RES_LOSSLESS")
    db.commit()
    db.close()

    opened = []

    def _open():
        conn = LibraryDB(db_path)
        conn.open()
        opened.append(conn)
        return conn

    monkeypatch.setattr(upgrade_api, "_get_db", _open)
    monkeypatch.setattr(
        "tidal_dl.config.Settings",
        lambda: SimpleNamespace(data=SimpleNamespace(upgrade_target_quality="HI_RES_LOSSLESS")),
    )

    results = upgrade_api._rebuild_results_from_db()
    for conn in opened:
        conn.close()

    assert [r["title"] for r in results] == ["Real Song"]
    assert all(r["tidal_track_id"] != CLONED_TIDAL_ID for r in results)


def test_scan_status_drops_cloned_isrc_collision():
    from tidal_dl.gui.api import upgrade as upgrade_api

    previous = {key: upgrade_api._scan_state[key] for key in upgrade_api._scan_state}
    upgrade_api._scan_state.update(
        running=False,
        cancel=None,
        status="complete",
        checked=5,
        total=5,
        upgradeable=5,
        skipped_no_isrc=0,
        error=None,
        results=[
            *[{**row, "current_quality": "HIGH", "available_quality": "HI_RES_LOSSLESS",
               "tidal_track_id": CLONED_TIDAL_ID} for row in _cloned_playlist_rows()],
            {"path": "/music/Real.flac", "title": "Real Song", "artist": "Artist", "album": "Album",
             "current_quality": "HIGH", "available_quality": "HI_RES_LOSSLESS",
             "isrc": "USOTHER0000001", "tidal_track_id": 1},
        ],
    )
    try:
        resp = upgrade_api.scan_status(include_results=True)
        titles = [row["title"] for row in resp["results"]]
        assert titles == ["Real Song"]
        assert resp["upgradeable"] == 1
    finally:
        upgrade_api._scan_state.update(previous)


def test_upgrade_status_returns_uncertain_for_cloned_isrc(tmp_path, monkeypatch):
    from tidal_dl.gui.api import upgrade as upgrade_api
    from tidal_dl.helper.library_db import LibraryDB

    db_path = tmp_path / "library.db"
    db = LibraryDB(db_path)
    db.open()
    for row in _cloned_playlist_rows():
        db.record(
            row["path"],
            status="tagged",
            isrc=row["isrc"],
            title=row["title"],
            artist=row["artist"],
        )
    db.set_probe(CLONED_ISRC, CLONED_TIDAL_ID, "HI_RES_LOSSLESS")
    db.commit()
    db.close()

    def _open():
        conn = LibraryDB(db_path)
        conn.open()
        return conn

    monkeypatch.setattr(upgrade_api, "_get_db", _open)

    resp = upgrade_api.upgrade_status(isrcs=CLONED_ISRC)
    assert resp["results"][0]["tidal_track_id"] is None
    assert resp["results"][0]["max_quality"] is None


def test_start_upgrade_skips_shared_tidal_id_with_different_titles(client, monkeypatch):
    rows = {row["path"]: row for row in _cloned_playlist_rows()}

    class FakeSettings:
        data = SimpleNamespace(upgrade_target_quality="HI_RES_LOSSLESS")

    class FakeDB:
        def get(self, path):
            return rows.get(path)

        def get_probe(self, isrc):
            return {"tidal_track_id": CLONED_TIDAL_ID, "max_quality": "HI_RES_LOSSLESS"}

        def tracks_by_isrc(self, isrc):
            return [row for row in rows.values() if row["isrc"] == isrc]

        def close(self):
            pass

    captured = []

    def fake_enqueue(items):
        captured.extend(items)
        return {"status": "queued", "count": len(items), "skipped": 0}

    monkeypatch.setattr("tidal_dl.config.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.api.upgrade._get_db", lambda: FakeDB())
    monkeypatch.setattr(client.app.state.download_jobs, "enqueue_upgrade", fake_enqueue)

    resp = client.post(
        "/api/upgrade/start",
        json={
            "tracks": [
                {"path": path, "tidal_track_id": CLONED_TIDAL_ID}
                for path in rows
            ]
        },
        headers=client._headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert captured == []
    assert body["skipped"] == 4
