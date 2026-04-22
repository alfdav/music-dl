from pathlib import Path
from types import SimpleNamespace


def _open_db(db_path: Path):
    from tidal_dl.helper.library_db import LibraryDB

    db = LibraryDB(db_path)
    db.open()
    return db


class _FakeSettings:
    def __init__(self):
        self.data = SimpleNamespace(upgrade_target_quality="HI_RES_LOSSLESS")


class _FakeTidal:
    def __init__(self):
        self.session = SimpleNamespace()


def test_probe_uses_cached_result_by_default(monkeypatch, tmp_path, clear_singletons):
    from tidal_dl.gui.api import upgrade as upgrade_api

    db_path = tmp_path / "library.db"
    db = _open_db(db_path)
    db.record("/music/track.flac", status="tagged", isrc="US123", artist="Artist", title="Song")
    db.set_probe("US123", 111, "LOSSLESS")
    db.commit()
    db.close()

    calls = []

    monkeypatch.setattr(upgrade_api, "_get_db", lambda: _open_db(db_path))
    monkeypatch.setattr(upgrade_api, "_probe_tidal_isrc", lambda *args, **kwargs: calls.append(kwargs) or {"tidal_track_id": 222, "max_quality": "HI_RES_LOSSLESS"})
    monkeypatch.setattr("tidal_dl.config.Settings", _FakeSettings)
    monkeypatch.setattr("tidal_dl.config.Tidal", _FakeTidal)

    result = upgrade_api.probe_isrcs(upgrade_api.ProbeRequest(isrcs=["US123"]))

    assert calls == []
    assert result["results"][0]["tidal_track_id"] == 111
    assert result["results"][0]["max_quality"] == "LOSSLESS"


def test_probe_force_refresh_bypasses_cached_result(monkeypatch, tmp_path, clear_singletons):
    from tidal_dl.gui.api import upgrade as upgrade_api

    db_path = tmp_path / "library.db"
    db = _open_db(db_path)
    db.record("/music/track.flac", status="tagged", isrc="US123", artist="Artist", title="Song")
    db.set_probe("US123", 111, "LOSSLESS")
    db.commit()
    db.close()

    calls = []

    def _fake_probe(*args, **kwargs):
        calls.append(kwargs)
        return {"tidal_track_id": 222, "max_quality": "HI_RES_LOSSLESS"}

    monkeypatch.setattr(upgrade_api, "_get_db", lambda: _open_db(db_path))
    monkeypatch.setattr(upgrade_api, "_probe_tidal_isrc", _fake_probe)
    monkeypatch.setattr("tidal_dl.config.Settings", _FakeSettings)
    monkeypatch.setattr("tidal_dl.config.Tidal", _FakeTidal)

    result = upgrade_api.probe_isrcs(upgrade_api.ProbeRequest(isrcs=["US123"], force=True))

    assert len(calls) == 1
    assert result["results"][0]["tidal_track_id"] == 222
    assert result["results"][0]["max_quality"] == "HI_RES_LOSSLESS"

    db = _open_db(db_path)
    probe = db.get_probe("US123")
    db.close()
    assert probe["tidal_track_id"] == 222
    assert probe["max_quality"] == "HI_RES_LOSSLESS"
