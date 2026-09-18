"""Local /api/playback must stay live while a download job is busy.

OAuth-free: any local fixture file + a simulated download-worker lock.
No Tidal session, no album-specific cleanup.
"""

from __future__ import annotations

import io
import threading
import time
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from tidal_dl.config import Settings, _token_fresh_lock
from tidal_dl.gui import create_app


_HOST = {"host": "localhost:8765"}
_HOLD_SEC = 2.0
_PLAYBACK_BUDGET_SEC = 0.75


def _write_wav(path: Path, *, frames: int = 44100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\x00\x00" * frames)
    return path


def _wav_duration_sec(payload: bytes) -> float:
    with wave.open(io.BytesIO(payload), "rb") as audio:
        return audio.getnframes() / float(audio.getframerate())


def _playback_client(tmp_path: Path, root: Path) -> TestClient:
    settings = Settings()
    settings.data.download_base_path = str(root)
    settings.save()
    return TestClient(create_app(port=8765, job_db_path=tmp_path / "jobs.db"))


def test_local_playback_stays_prompt_while_download_holds_token_lock(tmp_path):
    """Download worker I/O on `_token_fresh_lock` must not freeze local serve."""
    root = tmp_path / "library"
    track = _write_wav(root / "already-local.wav", frames=44100)
    client = _playback_client(tmp_path, root)

    held = threading.Event()

    def _download_worker_token_refresh() -> None:
        with _token_fresh_lock:
            held.set()
            time.sleep(_HOLD_SEC)

    worker = threading.Thread(target=_download_worker_token_refresh, name="sim-download-worker")
    worker.start()
    assert held.wait(timeout=1.0)

    started = time.monotonic()
    response = client.get("/api/playback/local", params={"path": str(track)}, headers=_HOST)
    elapsed = time.monotonic() - started
    worker.join(timeout=_HOLD_SEC + 1.0)

    assert response.status_code == 200, response.text
    assert elapsed < _PLAYBACK_BUDGET_SEC, f"local playback blocked for {elapsed:.3f}s"
    assert int(response.headers["content-length"]) == track.stat().st_size
    assert abs(_wav_duration_sec(response.content) - 1.0) < 0.01


def test_local_playback_skips_blocking_token_refresh_on_event_loop(tmp_path, monkeypatch):
    """A blocking `_ensure_token_fresh` (same loop as sidecar) must not run for local files."""
    root = tmp_path / "library"
    track = _write_wav(root / "fixture.wav", frames=22050)
    calls: list[str] = []

    def _blocking_refresh(self, refresh_window_sec=300):
        calls.append(str(refresh_window_sec))
        time.sleep(_HOLD_SEC)
        return False

    monkeypatch.setattr("tidal_dl.config.Tidal._ensure_token_fresh", _blocking_refresh)
    client = _playback_client(tmp_path, root)

    started = time.monotonic()
    response = client.get("/api/playback/local", params={"path": str(track)}, headers=_HOST)
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    assert calls == []
    assert elapsed < _PLAYBACK_BUDGET_SEC, f"token refresh ran on playback path ({elapsed:.3f}s)"
    assert abs(_wav_duration_sec(response.content) - 0.5) < 0.01


def test_local_playback_does_not_wait_on_library_db_for_on_disk_file(tmp_path, monkeypatch):
    """Already-local files must serve from disk, not a download-held library DB."""
    root = tmp_path / "library"
    track = _write_wav(root / "on-disk.wav", frames=44100)

    def _blocked_library_lookup(path: str):
        time.sleep(_HOLD_SEC)
        return False

    monkeypatch.setattr(
        "tidal_dl.gui.api.library._path_in_library", _blocked_library_lookup
    )
    monkeypatch.setattr(
        "tidal_dl.gui.api.library._trusted_library_path", lambda path: None
    )
    client = _playback_client(tmp_path, root)

    started = time.monotonic()
    response = client.get("/api/playback/local", params={"path": str(track)}, headers=_HOST)
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    assert elapsed < _PLAYBACK_BUDGET_SEC, f"library DB lookup blocked playback ({elapsed:.3f}s)"
    assert abs(_wav_duration_sec(response.content) - 1.0) < 0.01


def test_tidal_facing_paths_still_refresh_token(tmp_path, monkeypatch):
    """Skipping playback refresh must not disable Tidal-facing token checks."""
    calls: list[int] = []

    def _record_refresh(self, refresh_window_sec=300):
        calls.append(refresh_window_sec)
        return False

    monkeypatch.setattr("tidal_dl.config.Tidal._ensure_token_fresh", _record_refresh)
    client = _playback_client(tmp_path, tmp_path / "library")
    client.get("/api/search", params={"q": "x"}, headers=_HOST)

    assert calls, "Tidal-facing paths must still attempt token refresh"
