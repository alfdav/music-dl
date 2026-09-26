"""Issue #188: session-capped Hi-Res requests must fall back to delivered LOSSLESS."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
import requests
from tidalapi import Quality, Track

from tidal_dl.constants import CTX_TIDAL, DownloadSource, MediaType, quality_name
from tidal_dl.download.streams import QualityMismatchError, StreamMixin

_HIRES_NOTICE = "This login can't get Hi-Res streams, so downloading Lossless instead"
_HIRES_TRACK_ID = 534789853


def _oauth_cd_stream():
    manifest = type(
        "Manifest",
        (),
        {
            "file_extension": ".flac",
            "codecs": "flac",
            "get_urls": lambda self: ["https://example.invalid/cd.flac"],
        },
    )()
    return type(
        "Stream",
        (),
        {
            "audio_quality": Quality.high_lossless,
            "bit_depth": 16,
            "sample_rate": 44100,
            "get_stream_manifest": lambda self: manifest,
        },
    )()


def _listed_hires_track(stream):
    class ListedHiResTrack(Track):
        def __init__(self):
            pass

        @property
        def id(self):
            return _HIRES_TRACK_ID

        @property
        def audio_modes(self):
            return []

        @property
        def audio_quality(self):
            return "LOSSLESS"

        @property
        def media_metadata_tags(self):
            return ["HIRES_LOSSLESS", "LOSSLESS"]

        def get_stream(self):
            return stream

    return ListedHiResTrack()


def _download_stream_subject():
    hifi_calls: list[tuple[int, str]] = []
    subject = type("Subject", (StreamMixin,), {})()
    subject.settings = type(
        "Settings",
        (),
        {"data": type("Data", (), {"download_dolby_atmos": False, "extract_flac": True})()},
    )()
    subject.session = type("Session", (), {"audio_quality": Quality.hi_res_lossless})()
    subject.tidal = type(
        "Tidal",
        (),
        {
            "active_source": DownloadSource.OAUTH,
            "hifi_client": None,
            "stream_lock": threading.Lock(),
            "_ensure_token_fresh": lambda self: None,
            "restore_normal_session": lambda self: True,
        },
    )()
    subject.fn_logger = type(
        "Logger",
        (),
        {
            "error": lambda *_args: None,
            "exception": lambda *_args: None,
            "warning": lambda *_args: None,
        },
    )()
    return subject, hifi_calls


def _chosen_flac_params(manifest, media_stream) -> tuple[str, int, int]:
    if media_stream is not None:
        return (
            quality_name(media_stream.audio_quality).upper(),
            int(media_stream.bit_depth),
            int(media_stream.sample_rate),
        )
    raise AssertionError("stream pick did not expose FLAC quality/bit-depth/sample-rate")


def _logger_with_warnings() -> tuple[object, list[str]]:
    warnings: list[str] = []
    logger = SimpleNamespace(
        error=lambda *_args, **_kwargs: None,
        exception=lambda *_args, **_kwargs: None,
        warning=lambda msg, *args, **_kwargs: warnings.append(msg % args if args else str(msg)),
        info=lambda *_args, **_kwargs: None,
        debug=lambda *_args, **_kwargs: None,
    )
    return logger, warnings


def test_listed_hires_session_capped_at_lossless_downloads_lossless():
    """#188: Tidal Web / LOSSLESS session max + HI_RES request keeps the CD stream."""
    oauth_stream = _oauth_cd_stream()
    track = _listed_hires_track(oauth_stream)
    subject, hifi_calls = _download_stream_subject()
    subject.tidal.hifi_client = SimpleNamespace(
        track_stream=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            requests.RequestException("No live Hi-Fi API instances available.")
        )
    )
    subject.tidal.session_max_quality = "LOSSLESS"
    subject.fn_logger, warnings = _logger_with_warnings()

    manifest, extension, _extract, media_stream = subject._get_stream_info(
        track, quality_audio=Quality.hi_res_lossless
    )
    quality, bit_depth, sample_rate = _chosen_flac_params(manifest, media_stream)

    assert extension == ".flac"
    assert quality == "LOSSLESS"
    assert (bit_depth, sample_rate) == (16, 44100)
    assert manifest.get_urls() == ["https://example.invalid/cd.flac"]
    assert hifi_calls == []
    assert any(_HIRES_NOTICE in msg for msg in warnings)
    assert getattr(subject, "last_delivered_quality", None) == "LOSSLESS"
    assert warnings.count(next(msg for msg in warnings if _HIRES_NOTICE in msg)) == 1

    subject._get_stream_info(track, quality_audio=Quality.hi_res_lossless)
    notice_messages = [msg for msg in warnings if _HIRES_NOTICE in msg]
    assert len(notice_messages) == 1


def test_listed_hires_capable_session_still_raises_in_strict_mode():
    """A Hi-Res-capable login that still gets CD must keep the #148 fail-closed gate."""
    oauth_stream = _oauth_cd_stream()
    track = _listed_hires_track(oauth_stream)
    subject, _hifi_calls = _download_stream_subject()
    subject.tidal.hifi_client = SimpleNamespace(
        track_stream=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            requests.RequestException("No live Hi-Fi API instances available.")
        )
    )
    subject.tidal.session_max_quality = "HI_RES_LOSSLESS"

    with pytest.raises(QualityMismatchError, match="listed Hi-Res"):
        subject._get_stream_info(track, quality_audio=Quality.hi_res_lossless)


def test_cli_album_path_accepts_lossless_when_session_capped():
    """CLI album/playlist handler uses the same stream fallback as the desktop app."""
    from tidalapi.media import Quality as TidalQuality

    from tidal_dl.cli import _handle_album_playlist_mix_artist
    from tidal_dl.config import Tidal

    oauth_stream = _oauth_cd_stream()
    track = _listed_hires_track(oauth_stream)
    subject, _hifi_calls = _download_stream_subject()
    subject.tidal.session_max_quality = "LOSSLESS"
    subject.fn_logger, warnings = _logger_with_warnings()
    subject.tidal.hifi_client = None

    def items(**kwargs):
        return subject._get_stream_info(track, quality_audio=kwargs.get("quality_audio"))

    subject.items = items

    tidal = Tidal.__new__(Tidal)
    tidal.settings = SimpleNamespace(
        data=SimpleNamespace(
            quality_audio=TidalQuality.hi_res_lossless,
            quality_video=None,
            download_delay=False,
            video_download=False,
        )
    )
    tidal.session_max_quality = "LOSSLESS"
    ctx = SimpleNamespace(obj={CTX_TIDAL: tidal})
    handling = SimpleNamespace(event_abort=threading.Event())
    album = SimpleNamespace(id="99")

    result = _handle_album_playlist_mix_artist(
        ctx,
        subject,
        handling,
        MediaType.ALBUM,
        album,
        "99",
        "{track_title}",
    )

    assert result is True
    assert any(_HIRES_NOTICE in msg for msg in warnings)
    assert getattr(subject, "last_delivered_quality", None) == "LOSSLESS"


def test_probe_stores_session_max_without_changing_configured_quality():
    from tidal_dl.config import Tidal

    class SettingsData:
        quality_audio = Quality.hi_res_lossless

    class ProbeSettings:
        data = SettingsData()
        save_calls = 0

        def save(self):
            self.save_calls += 1

    class ProbeSession:
        audio_quality = Quality.hi_res_lossless

        def track(self, _track_id):
            stream = SimpleNamespace(audio_quality=Quality.high_lossless)
            return SimpleNamespace(get_stream=lambda: stream)

    probe = Tidal.__new__(Tidal)
    probe.settings = ProbeSettings()
    probe.session = ProbeSession()
    probe.session_max_quality = None
    probe.session_quality_notice = None
    probe._hires_fallback_notice_emitted = False

    Tidal._probe_subscription_quality(probe)

    assert probe.settings.data.quality_audio == Quality.hi_res_lossless
    assert probe.session.audio_quality == Quality.hi_res_lossless
    assert probe.settings.save_calls == 0
    assert probe.session_max_quality == "LOSSLESS"
    assert _HIRES_NOTICE in (probe.session_quality_notice or "")


def test_probe_hires_capable_session_does_not_warn_fallback(capsys):
    from tidal_dl.config import Tidal

    class ProbeSettings:
        data = SimpleNamespace(quality_audio=Quality.hi_res_lossless)
        save_calls = 0

        def save(self):
            self.save_calls += 1

    class ProbeSession:
        audio_quality = Quality.hi_res_lossless

        def track(self, _track_id):
            stream = SimpleNamespace(audio_quality=Quality.hi_res_lossless)
            return SimpleNamespace(get_stream=lambda: stream)

    probe = Tidal.__new__(Tidal)
    probe.settings = ProbeSettings()
    probe.session = ProbeSession()
    probe.session_max_quality = None
    probe.session_quality_notice = None
    probe._hires_fallback_notice_emitted = False

    Tidal._probe_subscription_quality(probe)

    output = capsys.readouterr().out
    assert probe.session_max_quality == "HI_RES_LOSSLESS"
    assert _HIRES_NOTICE not in output
    assert probe.session_quality_notice is None


def test_download_job_history_records_delivered_lossless_not_requested_hires(tmp_path, monkeypatch):
    from tidal_dl.gui.services.download_job_service import DownloadJobService
    from tidal_dl.model.downloader import DownloadOutcome

    service = DownloadJobService(db_path=tmp_path / "library.db", autostart=False)
    service.enqueue_download([123])

    class FakeTrack:
        id = 123
        name = "Song"
        full_name = "Song"
        duration = 1
        artists = ()
        album = None

    class FakeTidal:
        session = SimpleNamespace(track=lambda _track_id: FakeTrack())
        session_max_quality = "LOSSLESS"
        session_quality_notice = _HIRES_NOTICE

    class FakeSettings:
        data = SimpleNamespace(
            download_base_path=str(tmp_path),
            skip_existing=True,
            format_track="{track_title}",
            quality_audio="HI_RES_LOSSLESS",
        )

    class FakeDownload:
        last_delivered_quality = "LOSSLESS"

        def __init__(self, **_kwargs):
            pass

        def item(self, **_kwargs):
            return DownloadOutcome.DOWNLOADED, tmp_path / "Song.flac"

    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Tidal", FakeTidal)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Settings", FakeSettings)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.Download", FakeDownload)
    monkeypatch.setattr("tidal_dl.gui.services.download_job_service.scan_new_downloads", lambda *_args: None)

    job = service.claim_next_for_test()
    service.execute_job_for_test(job)

    history = service.history(limit=10)["downloads"]
    stored = service.get_job_for_test(job.id)
    assert history[0]["status"] == "done"
    assert history[0]["quality"] == "LOSSLESS"
    assert stored.quality == "LOSSLESS"


def test_unknown_session_max_still_fail_closes_listed_hires():
    """Unprobed sessions keep the #148 gate so a capable login cannot silently write CD."""
    oauth_stream = _oauth_cd_stream()
    track = _listed_hires_track(oauth_stream)
    subject, _hifi_calls = _download_stream_subject()
    subject.tidal.hifi_client = SimpleNamespace(
        track_stream=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            requests.RequestException("No live Hi-Fi API instances available.")
        )
    )

    with pytest.raises(QualityMismatchError, match="listed Hi-Res"):
        subject._get_stream_info(track, quality_audio=Quality.hi_res_lossless)
