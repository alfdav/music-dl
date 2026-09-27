"""CLI parity for #188 session-capped Hi-Res fallback.

Fallback lives in ``StreamMixin._get_stream_info`` (shared with desktop).
These tests only wrap the CLI: track, album, playlist, mix.
"""

from __future__ import annotations

import threading
from pathlib import Path

import requests
from tidalapi import Quality
from typer.testing import CliRunner

from tidal_dl.constants import CTX_TIDAL, DownloadSource, QualityVideo
from tidal_dl.download.quality import SESSION_HIRES_FALLBACK_NOTICE
from tidal_dl.download.streams import StreamMixin
from tidal_dl.model.downloader import DownloadOutcome

_TRACK_URL = "https://tidal.com/browse/track/66024828"
_ALBUM_URL = "https://tidal.com/browse/album/66024823"
_PLAYLIST_URL = "https://tidal.com/browse/playlist/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_MIX_URL = "https://tidal.com/browse/mix/01234567890abcdef"


def _listed_hires_track():
    from tests.test_hires_flac_quality import _listed_hires_track as _track
    from tests.test_hires_flac_quality import _oauth_cd_stream

    return _track(_oauth_cd_stream())


def _settings():
    return type(
        "Settings",
        (),
        {
            "data": type(
                "Data",
                (),
                {
                    "quality_audio": Quality.hi_res_lossless,
                    "quality_video": QualityVideo.P720,
                    "download_base_path": "/tmp/music-dl-cli-hires-test",
                    "skip_existing": False,
                    "download_delay": False,
                    "video_download": False,
                    "extract_flac": True,
                    "download_dolby_atmos": False,
                    "download_source_fallback": True,
                    "format_track": "{track_title}",
                    "format_album": "{album_title}",
                    "format_playlist": "{playlist_name}",
                    "format_mix": "{mix_name}",
                    "format_video": "{video_title}",
                },
            )()
        },
    )()


def _tidal(*, session_max: str | None, probe_to: str | None = None):
    tidal = type(
        "Tidal",
        (),
        {
            "settings": _settings(),
            "session": type("Session", (), {"audio_quality": Quality.hi_res_lossless, "access_token": "token"})(),
            "session_max_quality": session_max,
            "_hires_fallback_notice_emitted": False,
            "stream_lock": threading.Lock(),
            "_ensure_token_fresh": lambda self: None,
            "restore_normal_session": lambda self: True,
            "active_source": DownloadSource.OAUTH,
            "hifi_client": type(
                "DeadHiFi",
                (),
                {
                    "track_stream": staticmethod(
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            requests.RequestException("No live Hi-Fi API instances available.")
                        )
                    )
                },
            )(),
        },
    )()

    def _probe():
        if probe_to is not None:
            tidal.session_max_quality = probe_to

    tidal._probe_subscription_quality = _probe
    return tidal


def _install_cli(
    monkeypatch, *, session_max: str | None, media, probe_to: str | None = None, accept: bool = True
):

    tidal = _tidal(session_max=session_max, probe_to=probe_to)
    captured: list[str] = []

    def fake_resolve(ctx, *args, **kwargs):
        if not isinstance(getattr(ctx, "obj", None), dict):
            ctx.obj = {}
        ctx.obj[CTX_TIDAL] = tidal
        return True

    monkeypatch.setattr("tidal_dl.cli._ctx_tidal", lambda _ctx: tidal)
    monkeypatch.setattr("tidal_dl.cli._ctx_settings", lambda _ctx: tidal.settings)

    class CliDownload(StreamMixin):
        def __init__(self, tidal_obj, fn_logger, **_kwargs):
            self.tidal = tidal_obj
            self.session = tidal_obj.session
            self.settings = tidal_obj.settings
            self.fn_logger = type(
                "Logger",
                (),
                {
                    "debug": lambda *_a, **_k: None,
                    "info": lambda *_a, **_k: None,
                    "warning": lambda _self, message: captured.append(str(message)),
                    "error": lambda *_a, **_k: None,
                    "exception": lambda *_a, **_k: None,
                },
            )()
            self._track_manifest_formats = lambda _media, **_kw: ["FLAC", "FLAC_HIRES"]

        def item(self, media=None, **_kwargs):
            self._get_stream_info(media or _listed_hires_track())
            if not accept:
                return DownloadOutcome.FAILED, ""
            self._note_accepted_lossless_fallback()
            return DownloadOutcome.DOWNLOADED, Path("/tmp/cohen.flac")

        def items(self, **_kwargs):
            self._get_stream_info(_listed_hires_track())
            if not accept:
                return False
            self._note_accepted_lossless_fallback()

    monkeypatch.setattr("tidal_dl.cli._resolve_session", fake_resolve)
    monkeypatch.setattr("tidal_dl.cli.instantiate_media", lambda **_kwargs: media)
    monkeypatch.setattr("tidal_dl.cli.Download", CliDownload)
    return captured


def _invoke(url: str) -> object:
    from tidal_dl.cli import app

    return CliRunner().invoke(app, ["dl", url], catch_exceptions=False)


def _dummy_media(kind: str):
    if kind == "track":
        return _listed_hires_track()
    return type(kind.title(), (), {"id": "1"})()


def test_cli_track_capped_session_downloads_lossless(monkeypatch):
    notices = _install_cli(monkeypatch, session_max="LOSSLESS", media=_dummy_media("track"))
    result = _invoke(_TRACK_URL)
    assert result.exit_code == 0
    assert "Traceback" not in (result.output or "")
    assert notices == [SESSION_HIRES_FALLBACK_NOTICE]


def test_cli_refused_track_does_not_announce_lossless_and_exits(monkeypatch):
    notices = _install_cli(monkeypatch, session_max="LOSSLESS", media=_dummy_media("track"), accept=False)
    result = _invoke(_TRACK_URL)
    assert result.exit_code == 1
    assert notices == []


def test_cli_album_with_a_failed_track_exits_nonzero(monkeypatch):
    notices = _install_cli(monkeypatch, session_max="LOSSLESS", media=_dummy_media("album"), accept=False)
    result = _invoke(_ALBUM_URL)
    assert result.exit_code == 1
    assert notices == []


def test_cli_album_capped_session_downloads_lossless(monkeypatch):
    notices = _install_cli(monkeypatch, session_max="LOSSLESS", media=_dummy_media("album"))
    result = _invoke(_ALBUM_URL)
    assert result.exit_code == 0
    assert "Traceback" not in (result.output or "")
    assert notices == [SESSION_HIRES_FALLBACK_NOTICE]


def test_cli_playlist_capped_session_downloads_lossless(monkeypatch):
    notices = _install_cli(monkeypatch, session_max="LOSSLESS", media=_dummy_media("playlist"))
    result = _invoke(_PLAYLIST_URL)
    assert result.exit_code == 0
    assert "Traceback" not in (result.output or "")
    assert notices == [SESSION_HIRES_FALLBACK_NOTICE]


def test_cli_mix_capped_session_downloads_lossless(monkeypatch):
    notices = _install_cli(monkeypatch, session_max="LOSSLESS", media=_dummy_media("mix"))
    result = _invoke(_MIX_URL)
    assert result.exit_code == 0
    assert "Traceback" not in (result.output or "")
    assert notices == [SESSION_HIRES_FALLBACK_NOTICE]


def test_cli_capable_session_prints_clean_mismatch_and_exits(monkeypatch):
    notices = _install_cli(monkeypatch, session_max="HI_RES_LOSSLESS", media=_dummy_media("track"))
    result = _invoke(_TRACK_URL)
    assert result.exit_code == 1
    assert "Traceback" not in (result.output or "")
    assert "Quality mismatch" in (result.output or "")
    assert "FLAC_HIRES" in (result.output or "")
    assert notices == []


def test_cli_start_from_existing_token_probes_capped_login(monkeypatch):
    """CLI dl with a stored token must probe before the Hi-Res gate."""
    notices = _install_cli(
        monkeypatch,
        session_max=None,
        media=_dummy_media("track"),
        probe_to="LOSSLESS",
    )
    result = _invoke(_TRACK_URL)
    assert result.exit_code == 0
    assert "Traceback" not in (result.output or "")
    assert "Quality mismatch" not in (result.output or "")
    assert notices == [SESSION_HIRES_FALLBACK_NOTICE]
