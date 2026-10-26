"""Upgrade probes must not hold the library write lock across network work.

A stale Artist/Artist - Album playback heal has to commit while a probe is
in flight, and a locked heal must still serve the file already found on disk.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from types import SimpleNamespace

from tests.test_library_path_reconcile import (
    TestPlaybackBackstop as _PlaybackBackstop,
)
from tests.test_library_path_reconcile import (
    _write_wav,
)
from tidal_dl.helper.library_db import LibraryDB

_PLAYBACK_BUDGET_SEC = 1.5


class _FakeTidal:
    def __init__(self):
        self.session = SimpleNamespace()


def _seed_stale_layout(tmp_path):
    root = tmp_path / "Music"
    old = root / "Artist" / "Artist - Album" / "01 - Track.wav"
    live = root / "Artist" / "Album" / "01 - Track.wav"
    _write_wav(live, frames=8000)
    other = root / "Artist" / "Album" / "02 - Other.wav"
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    db.record(
        str(old),
        status="tagged",
        isrc="USAAA0000001",
        artist="Artist",
        title="Track",
        album="Album",
        duration=1,
        quality="WAV",
        fmt="WAV",
        codec="pcm",
        metadata_complete=True,
    )
    db.record(
        str(other),
        status="tagged",
        isrc="USBBB0000002",
        artist="Artist",
        title="Other",
        album="Album",
        duration=1,
        quality="WAV",
        fmt="WAV",
        codec="pcm",
        metadata_complete=True,
    )
    db.commit()
    db.close()
    return old, live


def test_playback_heals_while_probe_blocks_on_second_isrc(tmp_path, monkeypatch):
    """A mid-probe network wait must not stop the stale-path repair."""
    from tidal_dl.gui.api import upgrade as upgrade_api

    old, live = _seed_stale_layout(tmp_path)
    client, headers, _library_api = _PlaybackBackstop()._playback_client(
        tmp_path, monkeypatch, tmp_path / "Music",
    )

    release = threading.Event()
    second_isrc = threading.Event()
    calls = {"n": 0}
    errors: list[BaseException] = []

    def _fake_probe(_session, isrc, title="", artist="", duration=0):
        calls["n"] += 1
        if calls["n"] >= 2:
            second_isrc.set()
            assert release.wait(timeout=8)
        return {"tidal_track_id": 100 + calls["n"], "max_quality": "HI_RES_LOSSLESS"}

    monkeypatch.setattr(upgrade_api, "_probe_tidal_isrc", _fake_probe)
    monkeypatch.setattr("tidal_dl.config.Tidal", _FakeTidal)

    def _run_probe():
        try:
            upgrade_api.probe_isrcs(
                upgrade_api.ProbeRequest(isrcs=["USAAA0000001", "USBBB0000002"])
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            second_isrc.set()

    worker = threading.Thread(target=_run_probe, name="upgrade-probe")
    worker.start()
    assert second_isrc.wait(timeout=5), "probe never reached the second ISRC"

    try:
        with client:
            started = time.monotonic()
            response = client.get(
                "/api/playback/local",
                params={"path": str(old)},
                headers=headers,
            )
            elapsed = time.monotonic() - started
        assert response.status_code == 200, response.text
        assert elapsed < _PLAYBACK_BUDGET_SEC, f"playback blocked for {elapsed:.3f}s"

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        try:
            assert db.get(str(live)) is not None
            assert db.get(str(old)) is None
        finally:
            db.close()
    finally:
        release.set()
    worker.join(timeout=5)
    assert not errors
    assert not worker.is_alive()

    db = LibraryDB(tmp_path / "library.db")
    db.open()
    try:
        first = db.get_probe("USAAA0000001")
        second = db.get_probe("USBBB0000002")
    finally:
        db.close()
    assert first is not None and first["tidal_track_id"]
    assert second is not None and second["tidal_track_id"]
    assert {first["tidal_track_id"], second["tidal_track_id"]} == {101, 102}


def test_playback_serves_file_when_layout_heal_cannot_lock(tmp_path, monkeypatch):
    """A busy library DB must not turn a resolved local file into HTTP 500."""
    old, live = _seed_stale_layout(tmp_path)
    client, headers, _library_api = _PlaybackBackstop()._playback_client(
        tmp_path, monkeypatch, tmp_path / "Music",
    )

    holder = sqlite3.connect(tmp_path / "library.db")
    holder.execute("BEGIN IMMEDIATE")
    try:
        with client:
            started = time.monotonic()
            response = client.get(
                "/api/playback/local",
                params={"path": str(old)},
                headers=headers,
            )
            elapsed = time.monotonic() - started
    finally:
        holder.rollback()
        holder.close()

    assert response.status_code == 200, response.text
    assert elapsed < _PLAYBACK_BUDGET_SEC, f"playback blocked for {elapsed:.3f}s"
    assert int(response.headers["content-length"]) == live.stat().st_size
