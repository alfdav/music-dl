"""Issue #148: listed-HiRes downloads must not land as 16-bit/44.1 FLAC."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest
import requests
from mutagen.flac import FLAC
from tidalapi import Quality, Track

from tidal_dl.constants import DownloadSource, quality_name
from tidal_dl.download.streams import QualityMismatchError, StreamMixin
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


def test_listed_hires_empty_hifi_oauth_only_does_not_write_cd_flac():
    """Live #148 path: empty Hi-Fi + OAuth CD must not land as a successful 16/44.1 file."""
    oauth_stream = _oauth_cd_stream()
    track = _listed_hires_track(oauth_stream)
    subject, hifi_calls = _download_stream_subject()
    subject.tidal.hifi_client = type(
        "DeadHiFi",
        (),
        {
            "track_stream": staticmethod(
                lambda track_id, quality: (_ for _ in ()).throw(
                    requests.RequestException("No live Hi-Fi API instances available.")
                )
            )
        },
    )()

    with pytest.raises(QualityMismatchError, match="listed Hi-Res"):
        subject._get_stream_info(track)

    assert hifi_calls == []


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


def test_short_decoded_audio_is_not_saved_or_registered(tmp_path, monkeypatch):
    """Container duration can claim the full track while ffmpeg only decodes the preview."""
    from tidal_dl.download.items import ItemMixin

    registered: list[Path] = []
    monkeypatch.setattr(
        "tidal_dl.download.items.register_downloaded_track",
        lambda path: registered.append(Path(path)),
    )
    short = tmp_path / "preview.flac"
    _write_flac(short, 44100, 24)
    dest = tmp_path / "library" / "track.flac"
    dest.parent.mkdir(parents=True, exist_ok=True)

    class Subject(ItemMixin):
        def __init__(self):
            self.settings = type(
                "Settings",
                (),
                {
                    "data": type(
                        "Data",
                        (),
                        {"video_convert_mp4": False, "extract_flac": False, "path_binary_ffmpeg": "ffmpeg"},
                    )()
                },
            )()
            self.fn_logger = type(
                "Logger",
                (),
                {
                    "info": staticmethod(lambda *_a, **_k: None),
                    "error": staticmethod(lambda *_a, **_k: None),
                    "exception": staticmethod(lambda *_a, **_k: None),
                    "warning": staticmethod(lambda *_a, **_k: None),
                },
            )()

        def _download(self, media, stream_manifest, path_file, event_stop=None):
            path_file.write_bytes(short.read_bytes())
            return True, path_file

        def _handle_metadata_and_extras(self, *args, **kwargs):
            return None

    media = object.__new__(Track)
    media.duration = 216
    media.id = 66024828
    manifest = HiFiStreamManifest(
        urls=["https://example.invalid/preview.flac"],
        file_extension=".flac",
        codecs="flac",
        audio_quality="HI_RES_LOSSLESS",
        bit_depth=24,
        sample_rate=44100,
    )

    ok, path = Subject()._perform_actual_download(media, dest, manifest, False, False, None)

    assert ok is False
    assert path == dest
    assert not dest.exists()
    assert registered == []


def test_full_decoded_audio_is_still_saved(tmp_path):
    from tidal_dl.download.items import ItemMixin

    short = tmp_path / "full.flac"
    _write_flac(short, 44100, 16)
    dest = tmp_path / "library" / "track.flac"
    dest.parent.mkdir(parents=True, exist_ok=True)

    class Subject(ItemMixin):
        def __init__(self):
            self.settings = type(
                "Settings",
                (),
                {
                    "data": type(
                        "Data",
                        (),
                        {"video_convert_mp4": False, "extract_flac": False, "path_binary_ffmpeg": "ffmpeg"},
                    )()
                },
            )()
            self.fn_logger = type(
                "Logger",
                (),
                {
                    "info": staticmethod(lambda *_a, **_k: None),
                    "error": staticmethod(lambda *_a, **_k: None),
                    "exception": staticmethod(lambda *_a, **_k: None),
                    "warning": staticmethod(lambda *_a, **_k: None),
                },
            )()

        def _download(self, media, stream_manifest, path_file, event_stop=None):
            path_file.write_bytes(short.read_bytes())
            return True, path_file

        def _handle_metadata_and_extras(self, *args, **kwargs):
            return None

    media = object.__new__(Track)
    media.duration = 0.05
    media.id = 1
    manifest = type("Manifest", (), {"codecs": "flac", "file_extension": ".flac"})()

    ok, path = Subject()._perform_actual_download(media, dest, manifest, False, False, None)

    assert ok is True
    assert path.is_file()
    assert path.read_bytes() == short.read_bytes()


def _cover_jpeg(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64",
            "-frames:v",
            "1",
            "-y",
            str(path),
        ],
        check=True,
    )


def _embed_cover(flac_path: Path, jpeg_path: Path) -> None:
    from mutagen.flac import FLAC, Picture

    pic = Picture()
    pic.type = 3
    pic.mime = "image/jpeg"
    pic.data = jpeg_path.read_bytes()
    audio = FLAC(flac_path)
    audio.add_picture(pic)
    audio.save()


def _audio_seconds(path: Path) -> float:
    from tidal_dl.download_ffmpeg import audio_stream_duration_seconds

    measured = audio_stream_duration_seconds(path, "ffmpeg")
    assert measured is not None
    return measured


def test_cover_art_does_not_replace_audio_duration(tmp_path):
    """A front cover is its own stream. Duration must stay the audio length, not 0."""
    audio = tmp_path / "full.flac"
    cover = tmp_path / "cover.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=20",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-sample_fmt",
            "s16",
            "-c:a",
            "flac",
            "-y",
            str(audio),
        ],
        check=True,
    )
    _cover_jpeg(cover)
    _embed_cover(audio, cover)

    measured = _audio_seconds(audio)
    assert abs(measured - 20.0) < 0.25
    assert measured > 1.0


def test_thirty_second_preview_of_a_216_second_track_is_still_refused(tmp_path):
    from tidal_dl.download.items import ItemMixin

    preview = tmp_path / "preview.flac"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=30",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-sample_fmt",
            "s16",
            "-c:a",
            "flac",
            "-y",
            str(preview),
        ],
        check=True,
    )
    cover = tmp_path / "cover.jpg"
    _cover_jpeg(cover)
    _embed_cover(preview, cover)
    dest = tmp_path / "library" / "track.flac"
    dest.parent.mkdir(parents=True, exist_ok=True)

    class Subject(ItemMixin):
        def __init__(self):
            self.settings = type(
                "Settings",
                (),
                {
                    "data": type(
                        "Data",
                        (),
                        {"video_convert_mp4": False, "extract_flac": False, "path_binary_ffmpeg": "ffmpeg"},
                    )()
                },
            )()
            self.fn_logger = type(
                "Logger",
                (),
                {
                    "info": staticmethod(lambda *_a, **_k: None),
                    "error": staticmethod(lambda *_a, **_k: None),
                    "exception": staticmethod(lambda *_a, **_k: None),
                    "warning": staticmethod(lambda *_a, **_k: None),
                },
            )()

        def _download(self, media, stream_manifest, path_file, event_stop=None):
            path_file.write_bytes(preview.read_bytes())
            return True, path_file

        def _handle_metadata_and_extras(self, *args, **kwargs):
            return None

    media = object.__new__(Track)
    media.duration = 216
    media.id = 66024828
    manifest = HiFiStreamManifest(
        urls=["https://example.invalid/preview.flac"],
        file_extension=".flac",
        codecs="flac",
        audio_quality="LOSSLESS",
        bit_depth=16,
        sample_rate=44100,
    )

    ok, _path = Subject()._perform_actual_download(media, dest, manifest, False, False, None)

    assert ok is False
    assert not dest.exists()


def test_full_flac_with_embedded_cover_is_saved(tmp_path):
    from tidal_dl.download.items import ItemMixin

    audio = tmp_path / "full.flac"
    _write_flac(audio, 44100, 16)
    cover = tmp_path / "cover.jpg"
    _cover_jpeg(cover)
    _embed_cover(audio, cover)
    measured = _audio_seconds(audio)
    dest = tmp_path / "library" / "track.flac"
    dest.parent.mkdir(parents=True, exist_ok=True)

    class Subject(ItemMixin):
        def __init__(self):
            self.settings = type(
                "Settings",
                (),
                {
                    "data": type(
                        "Data",
                        (),
                        {"video_convert_mp4": False, "extract_flac": False, "path_binary_ffmpeg": "ffmpeg"},
                    )()
                },
            )()
            self.fn_logger = type(
                "Logger",
                (),
                {
                    "info": staticmethod(lambda *_a, **_k: None),
                    "error": staticmethod(lambda *_a, **_k: None),
                    "exception": staticmethod(lambda *_a, **_k: None),
                    "warning": staticmethod(lambda *_a, **_k: None),
                },
            )()

        def _download(self, media, stream_manifest, path_file, event_stop=None):
            path_file.write_bytes(audio.read_bytes())
            return True, path_file

        def _handle_metadata_and_extras(self, media, tmp_path_file, path_media_dst, is_parent_album, media_stream):
            _embed_cover(tmp_path_file, cover)

    media = object.__new__(Track)
    media.duration = measured
    media.id = 1
    manifest = type("Manifest", (), {"codecs": "flac", "file_extension": ".flac"})()

    ok, path = Subject()._perform_actual_download(media, dest, manifest, False, False, None)

    assert ok is True
    assert path.is_file()
    saved = _audio_seconds(path)
    assert abs(saved - measured) < 0.05
