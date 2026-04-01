from urllib.parse import quote


def test_get_local_lyrics_returns_synced_payload(client, monkeypatch, tmp_path):
    path = tmp_path / "track.flac"
    path.write_bytes(b"fake")

    from tidal_dl.gui.security import LocalAudioPathResolution

    monkeypatch.setattr(
        "tidal_dl.gui.api.lyrics.resolve_local_audio_path",
        lambda raw_path, allowed_dirs: LocalAudioPathResolution("ok", path.resolve()),
    )
    monkeypatch.setattr(
        "tidal_dl.gui.api.lyrics.read_local_lyrics",
        lambda audio_path: {
            "mode": "synced",
            "track_path": str(path.resolve()),
            "lines": [{"start_ms": 1000, "end_ms": 3000, "text": "Hello"}],
            "text": "",
            "source": "lrc-synced",
        },
    )

    resp = client.get(f"/api/lyrics/local?path={quote(str(path))}", headers=client._host_header)

    assert resp.status_code == 200
    assert resp.json()["mode"] == "synced"
    assert resp.json()["source"] == "lrc-synced"


def test_get_local_lyrics_returns_400_for_blank_path(client):
    resp = client.get("/api/lyrics/local?path=%20%20", headers=client._host_header)

    assert resp.status_code == 400


def test_get_local_lyrics_returns_403_for_forbidden_path(client, monkeypatch):
    from tidal_dl.gui.security import LocalAudioPathResolution

    monkeypatch.setattr(
        "tidal_dl.gui.api.lyrics.resolve_local_audio_path",
        lambda raw_path, allowed_dirs: LocalAudioPathResolution("forbidden"),
    )

    resp = client.get("/api/lyrics/local?path=%2Fetc%2Fpasswd", headers=client._host_header)

    assert resp.status_code == 403


def test_get_local_lyrics_returns_404_for_missing_trusted_path(client, monkeypatch):
    from tidal_dl.gui.security import LocalAudioPathResolution

    monkeypatch.setattr(
        "tidal_dl.gui.api.lyrics.resolve_local_audio_path",
        lambda raw_path, allowed_dirs: LocalAudioPathResolution("not_found"),
    )

    resp = client.get("/api/lyrics/local?path=%2Ftmp%2Fmissing.flac", headers=client._host_header)

    assert resp.status_code == 404


def test_get_local_lyrics_returns_404_for_not_audio(client, monkeypatch):
    from tidal_dl.gui.security import LocalAudioPathResolution

    monkeypatch.setattr(
        "tidal_dl.gui.api.lyrics.resolve_local_audio_path",
        lambda raw_path, allowed_dirs: LocalAudioPathResolution("not_audio"),
    )

    resp = client.get("/api/lyrics/local?path=%2Ftmp%2Fnotes.txt", headers=client._host_header)

    assert resp.status_code == 404


def test_get_local_lyrics_none_payload_keeps_required_fields(client, monkeypatch, tmp_path):
    path = tmp_path / "track.flac"
    path.write_bytes(b"fake")

    from tidal_dl.gui.security import LocalAudioPathResolution

    monkeypatch.setattr(
        "tidal_dl.gui.api.lyrics.resolve_local_audio_path",
        lambda raw_path, allowed_dirs: LocalAudioPathResolution("ok", path.resolve()),
    )
    monkeypatch.setattr(
        "tidal_dl.gui.api.lyrics.read_local_lyrics",
        lambda audio_path: {
            "mode": "none",
            "track_path": str(path.resolve()),
            "lines": [],
            "text": "",
            "source": "none",
        },
    )

    resp = client.get(f"/api/lyrics/local?path={quote(str(path))}", headers=client._host_header)

    assert resp.status_code == 200
    assert resp.json() == {
        "mode": "none",
        "track_path": str(path.resolve()),
        "lines": [],
        "text": "",
        "source": "none",
    }
