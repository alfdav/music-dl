"""Lossless streams must land as native *.flac — follow-up to #149 / #148 (container)."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from threading import Event, Lock
from unittest.mock import MagicMock

import pytest
from mutagen.flac import FLAC
from tidalapi import Quality, Track

from tidal_dl.constants import DownloadSource
from tidal_dl.download.streams import StreamMixin
from tidal_dl.hifi_api import HiFiApiClient, HiFiStreamResult
from tidal_dl.model.cfg import Settings as CfgSettings
from tidal_dl.model.downloader import HiFiStreamManifest

_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00" + (b"\x08" * 64) + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f\xff\xd9"
)


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


def _mux_flac_into_m4a_with_cover(flac_path: Path, cover_path: Path, out_path: Path) -> None:
    """Reproduce the Zeratool file: FLAC audio + MJPEG cover inside an MP4 box.

    The ipod/.m4a muxer cannot store FLAC. Tidal DASH uses ISO BMFF (`-f mp4`).
    """
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(flac_path),
            "-i",
            str(cover_path),
            "-map",
            "0:a",
            "-map",
            "1:v",
            "-c:a",
            "copy",
            "-c:v",
            "mjpeg",
            "-disposition:v",
            "attached_pic",
            "-f",
            "mp4",
            "-y",
            str(out_path),
        ],
        check=True,
    )


def _ffprobe_streams(path: Path) -> list[dict]:
    raw = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type,sample_fmt,sample_rate,bits_per_raw_sample",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(raw.stdout).get("streams") or []


def _flac_track() -> Track:
    class LocalTrack(Track):
        def __init__(self):
            pass

        @property
        def id(self):
            return 534789853

        @property
        def name(self):
            return "The Last Ship"

        @property
        def full_name(self):
            return self.name

        @property
        def artists(self):
            return []

        @property
        def album(self):
            return None

        @property
        def allow_streaming(self):
            return True

        @property
        def media_metadata_tags(self):
            return ["HIRES_LOSSLESS", "LOSSLESS"]

        @property
        def isrc(self):
            return "US-TST-24-53478"

        @property
        def audio_modes(self):
            return []

    return LocalTrack()


def _download_subject(tmp_path: Path):
    from tidal_dl.download import Download

    settings = type("Settings", (), {})()
    settings.data = CfgSettings()
    settings.data.extract_flac = True
    settings.data.metadata_cover_embed = True
    settings.data.cover_album_file = False
    settings.data.lyrics_embed = False
    settings.data.lyrics_file = False
    settings.data.path_binary_ffmpeg = "ffmpeg"

    tidal = MagicMock()
    tidal.session = MagicMock()
    tidal.session.audio_quality = Quality.hi_res_lossless
    tidal.settings = settings
    tidal.api_cache = None
    tidal.active_source = DownloadSource.HIFI_API
    tidal.hifi_client = MagicMock()
    tidal.stream_lock = MagicMock()
    tidal.stream_lock.__enter__ = MagicMock(return_value=None)
    tidal.stream_lock.__exit__ = MagicMock(return_value=False)

    dl = object.__new__(Download)
    dl.settings = settings
    dl.tidal = tidal
    dl.session = tidal.session
    dl.fn_logger = MagicMock()
    dl.path_base = str(tmp_path / "out")
    dl.skip_existing = False
    dl.event_abort = Event()
    dl.event_run = Event()
    dl.event_run.set()
    dl._checkpoint = None
    dl._rate_limit_hits = 0
    dl._successful_since_limit = 0
    dl._rate_limit_lock = Lock()
    dl._adaptive_delay_sec_min = 0
    dl._adaptive_delay_sec_max = 0
    dl._api_cache = None
    return dl


def test_settings_default_quality_is_hi_res_lossless_not_lossy():
    data = CfgSettings()
    assert data.quality_audio == Quality.hi_res_lossless
    assert data.extract_flac is True
    assert str(data.quality_audio) != "HIGH"
    assert str(data.quality_audio) != "LOW"


def test_hifi_mp4_mime_with_flac_codec_plans_native_flac_extract():
    """BTS often labels FLAC as audio/mp4. That is a container, not a lossy default."""
    result = HiFiStreamResult(
        urls=["https://example.invalid/hires.mp4"],
        file_extension=".m4a",
        codecs="flac",
        mime_type="audio/mp4",
        audio_quality="HI_RES_LOSSLESS",
        bit_depth=24,
        sample_rate=96000,
    )
    subject = type("Subject", (StreamMixin,), {})()
    subject.settings = type("Settings", (), {"data": type("Data", (), {"extract_flac": True})()})()
    subject.session = type("Session", (), {"audio_quality": Quality.hi_res_lossless})()
    subject.tidal = type(
        "Tidal",
        (),
        {
            "hifi_client": type("HiFi", (), {"track_stream": staticmethod(lambda *_a, **_k: result)})(),
        },
    )()

    info = subject._get_track_stream_info_hifi(_flac_track())

    assert info.file_extension == ".flac"
    assert info.requires_flac_extraction is True
    assert info.stream_manifest.file_extension == ".flac"


def test_hifi_bts_mp4_mime_flac_codec_parses_as_flac_extension():
    manifest_json = {
        "mimeType": "audio/mp4",
        "codecs": "flac",
        "encryptionType": "NONE",
        "urls": ["https://example.invalid/hires"],
    }
    encoded = base64.b64encode(json.dumps(manifest_json).encode("utf-8")).decode("utf-8")
    payload = {
        "data": {
            "audioQuality": "HI_RES_LOSSLESS",
            "manifestMimeType": "application/vnd.tidal.bts",
            "manifest": encoded,
            "bitDepth": 24,
            "sampleRate": 96000,
        }
    }

    parsed = HiFiApiClient.parse_track_payload(payload)

    assert parsed.codecs == "flac"
    assert parsed.file_extension == ".flac"
    assert parsed.file_extension != ".m4a"


def test_flac_in_mp4_with_cover_writes_native_flac(tmp_path: Path):
    """Shared mux path: FLAC-in-MP4 + cover must become *.flac, not a renamed .m4a."""
    src_flac = tmp_path / "src.flac"
    cover = tmp_path / "cover.jpg"
    boxed = tmp_path / "boxed.m4a"
    _write_flac(src_flac, sample_rate=96000, bit_depth=24)
    cover.write_bytes(_JPEG)
    _mux_flac_into_m4a_with_cover(src_flac, cover, boxed)

    header = boxed.read_bytes()[:12]
    assert header[4:8] == b"ftyp"

    dl = _download_subject(tmp_path)
    dest = tmp_path / "out" / "The Last Ship.flac"
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _copy_boxed(*, media, stream_manifest, path_file, event_stop=None):
        path_file.write_bytes(boxed.read_bytes())
        return True, path_file

    dl._download = _copy_boxed
    dl.metadata_write = lambda *args, **kwargs: (True, None, None)

    manifest = HiFiStreamManifest(
        urls=["https://example.invalid/hires"],
        file_extension=".m4a",
        codecs="flac",
        audio_quality="HI_RES_LOSSLESS",
        bit_depth=24,
        sample_rate=96000,
    )

    ok, out_path = dl._perform_actual_download(
        media=_flac_track(),
        path_media_dst=dest,
        stream_manifest=manifest,
        do_flac_extract=False,
        is_parent_album=False,
        media_stream=None,
    )

    assert ok is True
    assert Path(out_path).suffix == ".flac"
    assert Path(out_path).suffix != ".m4a"
    assert Path(out_path).is_file()

    audio = FLAC(out_path)
    assert audio.info.bits_per_sample >= 24
    assert audio.info.sample_rate == 96000

    streams = _ffprobe_streams(Path(out_path))
    audio_codecs = [s.get("codec_name") for s in streams]
    assert "flac" in audio_codecs
    assert "aac" not in audio_codecs
    assert "alac" not in audio_codecs
    assert "mjpeg" not in audio_codecs
    assert "png" not in audio_codecs


def test_flac_in_mp4_keeps_cover_as_flac_picture(tmp_path: Path):
    src_flac = tmp_path / "src.flac"
    cover = tmp_path / "cover.jpg"
    boxed = tmp_path / "boxed.m4a"
    _write_flac(src_flac, sample_rate=96000, bit_depth=24)
    cover.write_bytes(_JPEG)
    _mux_flac_into_m4a_with_cover(src_flac, cover, boxed)

    dl = _download_subject(tmp_path)
    dest = tmp_path / "out" / "cover-track.flac"
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _copy_boxed(*, media, stream_manifest, path_file, event_stop=None):
        path_file.write_bytes(boxed.read_bytes())
        return True, path_file

    def _write_cover(media, tmp_path_file, is_parent_album, media_stream):
        from tidal_dl.metadata import Metadata

        meta = Metadata(
            path_file=tmp_path_file,
            target_upc={"FLAC": "UPC", "MP3": "UPC", "MP4": "UPC"},
            title="The Last Ship",
            album="Live",
            artists="Sting",
            albumartist="Sting",
            cover_data=_JPEG,
        )
        meta.save()
        return True, None, None

    dl._download = _copy_boxed
    dl.metadata_write = _write_cover

    manifest = HiFiStreamManifest(
        urls=["https://example.invalid/hires"],
        file_extension=".m4a",
        codecs="flac",
        audio_quality="HI_RES_LOSSLESS",
        bit_depth=24,
        sample_rate=96000,
    )

    ok, out_path = dl._perform_actual_download(
        media=_flac_track(),
        path_media_dst=dest,
        stream_manifest=manifest,
        do_flac_extract=False,
        is_parent_album=False,
        media_stream=None,
    )

    assert ok is True
    assert Path(out_path).suffix == ".flac"
    tagged = FLAC(out_path)
    assert tagged.pictures, "cover must remain as a FLAC PICTURE, not an MP4 MJPEG stream"
    assert tagged.pictures[0].data == _JPEG
    assert tagged.info.sample_rate == 96000
    assert tagged.info.bits_per_sample >= 24
    streams = _ffprobe_streams(Path(out_path))
    # Mutagen JPEG PICTURE may show as mjpeg. ffmpeg -map 0 leftover is png video.
    assert "png" not in [s.get("codec_name") for s in streams]
    assert not any(s.get("codec_type") == "video" and s.get("codec_name") == "png" for s in streams)


def test_aac_high_still_writes_m4a(tmp_path: Path):
    """Lossy HIGH stays .m4a — this ticket is the lossless path only."""
    m4a = tmp_path / "lossy.m4a"
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
            "-c:a",
            "aac",
            "-y",
            str(m4a),
        ],
        check=True,
    )

    dl = _download_subject(tmp_path)
    dest = tmp_path / "out" / "lossy.m4a"
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _copy(*, media, stream_manifest, path_file, event_stop=None):
        path_file.write_bytes(m4a.read_bytes())
        return True, path_file

    dl._download = _copy
    dl.metadata_write = lambda *args, **kwargs: (True, None, None)

    manifest = HiFiStreamManifest(urls=["https://example.invalid/high"], file_extension=".m4a", codecs="aac")
    ok, out_path = dl._perform_actual_download(
        media=_flac_track(),
        path_media_dst=dest,
        stream_manifest=manifest,
        do_flac_extract=False,
        is_parent_album=False,
        media_stream=None,
    )

    assert ok is True
    assert Path(out_path).suffix == ".m4a"
    streams = _ffprobe_streams(Path(out_path))
    assert "aac" in [s.get("codec_name") for s in streams]


def test_detect_does_not_rename_boxed_flac_to_m4a(tmp_path: Path):
    """Boxed FLAC must stay .flac. .m4a is only for actual AAC/lossy."""
    from tidal_dl.download import Download

    dl = _download_subject(tmp_path)
    src_flac = tmp_path / "src.flac"
    boxed = tmp_path / "boxed.mp4"
    cover = tmp_path / "cover.jpg"
    _write_flac(src_flac, sample_rate=96000, bit_depth=24)
    cover.write_bytes(_JPEG)
    _mux_flac_into_m4a_with_cover(src_flac, cover, boxed)

    detect = Download._detect_downloaded_audio_extension.__get__(dl, Download)
    assert detect(boxed, ".flac", codecs="flac") == ".flac"
    assert detect(boxed, ".m4a", codecs="flac") == ".flac"
    assert detect(boxed, ".m4a", codecs="") == ".flac"
    extracted = tmp_path / "extracted.flac"
    _write_flac(extracted, sample_rate=96000, bit_depth=24)
    assert detect(extracted, ".m4a", codecs="flac") == ".flac"


def test_boxed_flac_fails_closed_when_extract_disabled(tmp_path: Path):
    src_flac = tmp_path / "src.flac"
    boxed = tmp_path / "boxed.mp4"
    cover = tmp_path / "cover.jpg"
    _write_flac(src_flac, sample_rate=96000, bit_depth=24)
    cover.write_bytes(_JPEG)
    _mux_flac_into_m4a_with_cover(src_flac, cover, boxed)

    dl = _download_subject(tmp_path)
    dl.settings.data.extract_flac = False
    dest = tmp_path / "out" / "The Last Ship.flac"
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _copy_boxed(*, media, stream_manifest, path_file, event_stop=None):
        path_file.write_bytes(boxed.read_bytes())
        return True, path_file

    dl._download = _copy_boxed
    dl.metadata_write = lambda *args, **kwargs: (True, None, None)

    manifest = HiFiStreamManifest(
        urls=["https://example.invalid/hires"],
        file_extension=".m4a",
        codecs="flac",
        audio_quality="HI_RES_LOSSLESS",
        bit_depth=24,
        sample_rate=96000,
    )
    ok, out_path = dl._perform_actual_download(
        media=_flac_track(),
        path_media_dst=dest,
        stream_manifest=manifest,
        do_flac_extract=False,
        is_parent_album=False,
        media_stream=None,
    )

    assert ok is False
    written = [p for p in (tmp_path / "out").glob("*") if p.is_file()]
    assert not any(p.read_bytes()[:8][4:8] == b"ftyp" and p.suffix == ".flac" for p in written)


def test_empty_codec_m4a_dest_still_extracts_boxed_flac(tmp_path: Path):
    """DASH / audio/mp4 mime can leave codec empty and dest .m4a. Still write *.flac."""
    src_flac = tmp_path / "src.flac"
    boxed = tmp_path / "boxed.mp4"
    cover = tmp_path / "cover.jpg"
    _write_flac(src_flac, sample_rate=96000, bit_depth=24)
    cover.write_bytes(_JPEG)
    _mux_flac_into_m4a_with_cover(src_flac, cover, boxed)

    dl = _download_subject(tmp_path)
    dest = tmp_path / "out" / "empty-codec.m4a"
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _copy_boxed(*, media, stream_manifest, path_file, event_stop=None):
        path_file.write_bytes(boxed.read_bytes())
        return True, path_file

    dl._download = _copy_boxed
    dl.metadata_write = lambda *args, **kwargs: (True, None, None)

    manifest = HiFiStreamManifest(urls=["https://example.invalid/dash"], file_extension=".m4a", codecs="")
    ok, out_path = dl._perform_actual_download(
        media=_flac_track(),
        path_media_dst=dest,
        stream_manifest=manifest,
        do_flac_extract=False,
        is_parent_album=False,
        media_stream=None,
    )

    assert ok is True
    assert Path(out_path).suffix == ".flac"
    streams = _ffprobe_streams(Path(out_path))
    names = [s.get("codec_name") for s in streams]
    assert "flac" in names
    assert "mjpeg" not in names
    assert "png" not in names
    assert "aac" not in names


def test_extract_flac_copies_audio_only_no_video_transcode(tmp_path: Path):
    from tidal_dl.download_ffmpeg import extract_flac

    src_flac = tmp_path / "src.flac"
    boxed = tmp_path / "boxed.mp4"
    cover = tmp_path / "cover.jpg"
    _write_flac(src_flac, sample_rate=96000, bit_depth=24)
    cover.write_bytes(_JPEG)
    _mux_flac_into_m4a_with_cover(src_flac, cover, boxed)

    out = extract_flac("ffmpeg", boxed)
    assert out.suffix == ".flac"
    streams = _ffprobe_streams(out)
    names = [s.get("codec_name") for s in streams]
    types = [s.get("codec_type") for s in streams]
    assert "flac" in names
    assert "mjpeg" not in names
    assert "png" not in names
    assert "video" not in types


def test_plan_flac_output_extracts_even_when_extension_already_flac():
    from tidal_dl.download.streams import plan_flac_output

    extension, extract = plan_flac_output("flac", ".flac", True)
    assert extension == ".flac"
    assert extract is True


def test_extract_failure_fails_closed(tmp_path: Path):
    src_flac = tmp_path / "src.flac"
    boxed = tmp_path / "boxed.mp4"
    cover = tmp_path / "cover.jpg"
    _write_flac(src_flac, sample_rate=96000, bit_depth=24)
    cover.write_bytes(_JPEG)
    _mux_flac_into_m4a_with_cover(src_flac, cover, boxed)

    dl = _download_subject(tmp_path)
    dest = tmp_path / "out" / "fail.flac"
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _copy_boxed(*, media, stream_manifest, path_file, event_stop=None):
        path_file.write_bytes(boxed.read_bytes())
        return True, path_file

    def _boom(_path):
        raise RuntimeError("ffmpeg exploded")

    dl._download = _copy_boxed
    dl._extract_flac = _boom
    dl.metadata_write = lambda *args, **kwargs: (True, None, None)

    manifest = HiFiStreamManifest(urls=["https://example.invalid/hires"], file_extension=".m4a", codecs="flac")
    ok, _out_path = dl._perform_actual_download(
        media=_flac_track(),
        path_media_dst=dest,
        stream_manifest=manifest,
        do_flac_extract=True,
        is_parent_album=False,
        media_stream=None,
    )

    assert ok is False
    written = [p for p in (tmp_path / "out").glob("*") if p.is_file()]
    assert not any(p.suffix == ".m4a" for p in written)


def test_extension_guess_lossless_defaults_to_flac_not_m4a(tmp_path: Path):
    dl = _download_subject(tmp_path)
    assert dl.extension_guess(Quality.hi_res_lossless, [], is_video=False) == ".flac"
    assert dl.extension_guess(Quality.high_lossless, [], is_video=False) == ".flac"
    assert dl.extension_guess(Quality.low_320k, [], is_video=False) == ".m4a"
