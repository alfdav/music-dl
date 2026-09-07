"""Product-wide download pacing: Tidal API only, never the media byte stream.

These tests hold for any library / any download. They do not depend on a
specific album, artist, or track fixture.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from threading import Event, Lock
from unittest.mock import MagicMock

import pytest
import requests


def _make_download_stub():
    from tidal_dl.config import Settings
    from tidal_dl.constants import DownloadSource
    from tidal_dl.download import Download

    settings = Settings()
    tidal = MagicMock()
    tidal.session = MagicMock()
    tidal.settings = settings
    tidal.api_cache = None
    tidal.active_source = DownloadSource.OAUTH
    tidal.hifi_client = None

    dl = object.__new__(Download)
    dl.settings = settings
    dl.tidal = tidal
    dl.session = tidal.session
    dl.fn_logger = MagicMock()
    dl.path_base = "/tmp"
    dl.skip_existing = False
    dl.event_abort = Event()
    dl.event_run = Event()
    dl.event_run.set()
    dl._checkpoint = None
    dl._rate_limit_hits = 0
    dl._successful_since_limit = 0
    dl._rate_limit_lock = Lock()
    dl._adaptive_delay_sec_min = settings.data.download_delay_sec_min
    dl._adaptive_delay_sec_max = settings.data.download_delay_sec_max
    dl._api_cache = None
    return dl


def test_post_processing_does_not_sleep_on_stream_path():
    """download_delay must not pause after media bytes are already on disk."""
    from tidal_dl.download.api_pacing import TidalApiPacer

    dl = _make_download_stub()
    dl.settings.data.symlink_to_track = False
    waits: list[float] = []
    event_stop = Event()
    event_stop.wait = lambda timeout=None: waits.append(timeout) or True  # type: ignore[method-assign]

    dl._perform_post_processing(
        MagicMock(),
        Path("/tmp/any-track.flac"),
        None,
        None,
        None,
        None,
        True,
        False,
        event_stop,
    )

    assert waits == []
    assert not hasattr(TidalApiPacer, "sleep_after_media")


def test_api_pacer_skips_first_call_and_waits_between_later_calls():
    from tidal_dl.download.api_pacing import TidalApiPacer

    slept: list[float] = []
    clock = [0.0]

    def now() -> float:
        return clock[0]

    def sleeper(seconds: float) -> None:
        slept.append(seconds)
        clock[0] += seconds

    pacer = TidalApiPacer(delay_min=0.4, delay_max=0.4, sleeper=sleeper, clock=now)
    assert pacer.wait_before_api(enabled=True) == 0.0
    assert slept == []
    assert pacer.wait_before_api(enabled=True) == pytest.approx(0.4)
    assert slept == [pytest.approx(0.4)]


def test_api_pacer_disabled_never_sleeps():
    from tidal_dl.download.api_pacing import TidalApiPacer

    slept: list[float] = []
    pacer = TidalApiPacer(delay_min=10.0, delay_max=10.0, sleeper=slept.append)
    assert pacer.wait_before_api(enabled=False) == 0.0
    assert pacer.wait_before_api(enabled=False) == 0.0
    assert slept == []


def test_get_stream_info_paces_api_not_media_bytes():
    """Stream-info / auth API is paced; segment byte transfer is not."""
    from tidal_dl.download import segments, streams

    dl = _make_download_stub()
    assert callable(dl._pace_tidal_api)
    stream_src = inspect.getsource(streams.StreamMixin._get_stream_info)
    segment_src = inspect.getsource(segments)
    assert "_pace_stream_api" in stream_src
    assert "_pace_stream_api" not in segment_src
    assert "_pace_tidal_api" not in segment_src
    assert "download_delay" not in segment_src


def test_download_segments_uses_concurrent_chunk_setting(monkeypatch):
    from concurrent import futures

    from tidal_dl.download.segments import SegmentMixin

    captured: dict[str, int] = {}

    class FakeExecutor:
        def __init__(self, max_workers=None):
            captured["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, fn, *args, **kwargs):
            raise AssertionError("segment submit must not run in this unit test")

    monkeypatch.setattr(futures, "ThreadPoolExecutor", FakeExecutor)

    class Subject(SegmentMixin):
        def __init__(self):
            self.settings = type(
                "Settings",
                (),
                {"data": type("Data", (), {"downloads_simultaneous_per_track_max": 17})()},
            )()
            task = type("Task", (), {"finished": False})()
            self.progress = type("Progress", (), {"tasks": {0: task}})()
            self.event_abort = Event()

        def _download_segment(self, *args, **kwargs):
            raise AssertionError("must not download bytes while inspecting concurrency")

    subject = Subject()
    with pytest.raises(AssertionError, match="segment submit"):
        subject._download_segments(["https://cdn.example/seg"], Path("/tmp"), None, 0, False)

    assert captured["max_workers"] == 17


def test_download_segment_source_has_no_artificial_sleep():
    from tidal_dl.download import segments

    source = inspect.getsource(segments)
    assert "time.sleep" not in source
    assert "download_delay" not in source


def test_upgrade_probe_sleep_is_not_on_media_path():
    from tidal_dl.download import segments
    from tidal_dl.gui.api import upgrade as upgrade_api

    upgrade_src = inspect.getsource(upgrade_api)
    segment_src = inspect.getsource(segments)
    assert "time.sleep(2)" in upgrade_src
    assert "time.sleep(2)" not in segment_src
    assert "0.5 req/sec" in upgrade_src


def test_note_429_honors_retry_after_and_widens_delay():
    from tidal_dl.download.api_pacing import TidalApiPacer, retry_after_seconds

    pacer = TidalApiPacer(delay_min=3.0, delay_max=5.0)
    wait = pacer.note_429(retry_after_sec=7.0)
    assert wait == 7.0
    assert pacer.delay_min == 6.0
    assert pacer.delay_max == 10.0

    response = requests.Response()
    response.headers["Retry-After"] = "12"
    assert retry_after_seconds(response, fallback=4.0) == 12.0
    assert retry_after_seconds(None, fallback=4.0) == 4.0


def test_on_rate_limit_hit_widens_api_pacing_delay():
    dl = _make_download_stub()
    original_min = dl._adaptive_delay_sec_min
    original_max = dl._adaptive_delay_sec_max
    dl._on_rate_limit_hit()
    assert dl._rate_limit_hits == 1
    assert dl._adaptive_delay_sec_min == min(original_min * 2, 30.0)
    assert dl._adaptive_delay_sec_max == min(original_max * 2, 30.0)


def test_job_service_429_prefers_retry_after_header(tmp_path, monkeypatch):
    from tidal_dl.gui.services.download_job_service import DownloadJobService

    service = DownloadJobService(db_path=Path(tmp_path) / "library.db", autostart=False)
    service.enqueue_download([55])
    job = service.claim_next_for_test()
    slept: list[float] = []
    attempts: list[int] = []

    class LocalTrack:
        id = 55
        name = "Any Track"
        full_name = "Any Track"
        artists = ()
        album = None

    class LocalTidal:
        session = type("Session", (), {"track": lambda _self, _track_id: LocalTrack()})()

    class LocalSettings:
        data = type(
            "Data",
            (),
            {
                "download_base_path": str(tmp_path / "downloads"),
                "skip_existing": True,
                "format_track": "{track_title}",
                "quality_audio": "LOSSLESS",
                "download_delay": True,
            },
        )()

    class RateLimitedDownload:
        def __init__(self, **_kwargs):
            pass

        def item(self, **_kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                response = requests.Response()
                response.status_code = 429
                response.headers["Retry-After"] = "9"
                raise requests.exceptions.HTTPError("rate limited", response=response)
            return __import__("tidal_dl.model.downloader", fromlist=["DownloadOutcome"]).DownloadOutcome.DOWNLOADED, tmp_path / "out.flac"

    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", LocalTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", LocalSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", RateLimitedDownload)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.time.sleep", slept.append)
    monkeypatch.setattr(
        "tidal_dl.gui.services.download_job_service.scan_new_downloads",
        lambda *_args, **_kwargs: None,
    )

    service.execute_job_for_test(job)
    assert len(attempts) == 2
    assert slept == [9.0]


def test_gui_worker_count_follows_downloads_concurrent_max(tmp_path):
    from tidal_dl.gui.services.download_job_service import DownloadJobService

    class LocalSettings:
        data = type("Data", (), {"downloads_concurrent_max": 4})()

    def dependencies():
        return LocalSettings, object, object

    service = DownloadJobService(
        db_path=Path(tmp_path) / "library.db",
        autostart=False,
        dependency_provider=dependencies,
    )
    assert service._worker_count() == 4
    service.start_worker()
    try:
        assert len(service._worker_threads) == 4
        assert service._worker_thread is service._worker_threads[0]
    finally:
        service.stop_worker()
