"""Issue #148: listed-HiRes downloads must not land as 16-bit/44.1 FLAC."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from mutagen.flac import FLAC
from tidalapi import Quality, Track

from tidal_dl.constants import DownloadSource, quality_name
from tidal_dl.download.streams import StreamMixin
from tidal_dl.hifi_api import HiFiStreamResult
from tidal_dl.model.downloader import HiFiStreamManifest


# Reporter track: Sting — The Last Ship (Live at the Rijksmuseum)
_HIRES_TRACK_ID = 534789853


def _write_flac(path: Path, sample_rate: int, bit_depth: int) -> None:
    sample_fmt = {16: "s16", 24: "s32"}.get(bit_depth)
    if sample_fmt is None:
        raise AssertionError(f"unsupported bit depth {bit_depth}")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.05",
            "-ac",
            "2",
            "-ar",
            str(sample_rate),
            "-sample_fmt",
            sample_fmt,
            "-c:a",
            "flac",
            "-y",
            str(path),
        ],
        check=True,
    )


def _flac_params(path: Path) -> tuple[int, int]:
    audio = FLAC(path)
    return int(audio.info.bits_per_sample), int(audio.info.sample_rate)


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


def _hires_hifi_result() -> HiFiStreamResult:
    return HiFiStreamResult(
        urls=["https://example.invalid/hires.flac"],
        file_extension=".flac",
        codecs="flac",
        mime_type="audio/flac",
        audio_quality="HI_RES_LOSSLESS",
        bit_depth=24,
        sample_rate=96000,
    )


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
            # Tidal catalog field is often LOSSLESS even when HiRes is tagged.
            return "LOSSLESS"

        @property
        def media_metadata_tags(self):
            return ["HIRES_LOSSLESS", "LOSSLESS"]

        def get_stream(self):
            return stream

    return ListedHiResTrack()


def _listed_lossless_track(stream):
    class ListedLosslessTrack(Track):
        def __init__(self):
            pass

        @property
        def id(self):
            return 1

        @property
        def audio_modes(self):
            return []

        @property
        def audio_quality(self):
            return "LOSSLESS"

        @property
        def media_metadata_tags(self):
            return ["LOSSLESS"]

        def get_stream(self):
            return stream

    return ListedLosslessTrack()


def _download_stream_subject(hifi_result: HiFiStreamResult | None = None):
    hifi_calls: list[tuple[int, str]] = []

    class HiFiClient:
        def track_stream(self, track_id, quality):
            hifi_calls.append((track_id, quality))
            if hifi_result is None:
                raise AssertionError("Hi-Fi should not be required for this case")
            return hifi_result

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
            "hifi_client": HiFiClient() if hifi_result is not None else None,
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
    if isinstance(manifest, HiFiStreamManifest):
        quality = str(getattr(manifest, "audio_quality", "") or "").upper()
        bit_depth = getattr(manifest, "bit_depth", None)
        sample_rate = getattr(manifest, "sample_rate", None)
        if quality and bit_depth and sample_rate:
            return quality, int(bit_depth), int(sample_rate)
    raise AssertionError("stream pick did not expose FLAC quality/bit-depth/sample-rate")


def test_listed_hires_small_download_selects_and_writes_hires_flac(tmp_path):
    """First-install OAuth + listed HiRes must not write the CD-quality fallback."""
    oauth_stream = _oauth_cd_stream()
    track = _listed_hires_track(oauth_stream)
    subject, hifi_calls = _download_stream_subject(_hires_hifi_result())

    manifest, extension, _extract, media_stream = subject._get_stream_info(track)
    quality, bit_depth, sample_rate = _chosen_flac_params(manifest, media_stream)

    out = tmp_path / "The Last Ship (Live at the Rijksmuseum).flac"
    _write_flac(out, sample_rate=sample_rate, bit_depth=bit_depth)
    written_bits, written_rate = _flac_params(out)

    assert extension == ".flac"
    assert quality == "HI_RES_LOSSLESS"
    assert bit_depth > 16 or sample_rate > 44100
    assert written_bits > 16 or written_rate > 44100
    assert hifi_calls == [(_HIRES_TRACK_ID, "HI_RES_LOSSLESS")]
    assert manifest.get_urls() == ["https://example.invalid/hires.flac"]


def test_listed_lossless_still_writes_cd_flac(tmp_path):
    oauth_stream = _oauth_cd_stream()
    track = _listed_lossless_track(oauth_stream)
    subject, hifi_calls = _download_stream_subject(_hires_hifi_result())

    manifest, extension, _extract, media_stream = subject._get_stream_info(track)
    quality, bit_depth, sample_rate = _chosen_flac_params(manifest, media_stream)

    out = tmp_path / "standard-lossless.flac"
    _write_flac(out, sample_rate=sample_rate, bit_depth=bit_depth)
    written_bits, written_rate = _flac_params(out)

    assert extension == ".flac"
    assert quality == "LOSSLESS"
    assert (written_bits, written_rate) == (16, 44100)
    assert hifi_calls == []
    assert manifest.get_urls() == ["https://example.invalid/cd.flac"]
