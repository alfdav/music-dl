"""Lossy AAC must never be labeled as CD 16/44.1 lossless."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tidal_dl.gui.api.library import _read_metadata
from tidal_dl.helper.library_db.utils import local_quality_label


def _write_audio(path: Path, *, codec: str, extra: list[str] | None = None) -> None:
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
            "44100",
            *(extra or []),
            "-c:a",
            codec,
            "-y",
            str(path),
        ],
        check=True,
    )


@pytest.fixture(scope="module")
def samples(tmp_path_factory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("quality-samples")
    aac = root / "04 Aylaylay.m4a"
    alac = root / "alac.m4a"
    flac = root / "cd.flac"
    _write_audio(aac, codec="aac", extra=["-b:a", "192k"])
    _write_audio(alac, codec="alac", extra=["-sample_fmt", "s16p"])
    _write_audio(flac, codec="flac", extra=["-sample_fmt", "s16"])
    return {"aac": aac, "alac": alac, "flac": flac}


def test_m4a_aac_is_not_cd_lossless(samples):
    meta = _read_metadata(samples["aac"])
    assert meta is not None
    assert meta["codec"] == "aac"
    assert meta["format"] == "M4A"
    assert meta["quality"] != "44100Hz/16bit"
    assert "16bit" not in meta["quality"]
    assert local_quality_label(meta["quality"], meta["format"], meta["codec"]) == "AAC"


def test_m4a_alac_keeps_hz_bit(samples):
    meta = _read_metadata(samples["alac"])
    assert meta is not None
    assert meta["codec"] == "alac"
    assert meta["format"] == "M4A"
    assert meta["quality"] == "44100Hz/16bit"
    assert local_quality_label(meta["quality"], meta["format"], meta["codec"]) == "44100Hz/16bit"


def test_flac_keeps_hz_bit(samples):
    meta = _read_metadata(samples["flac"])
    assert meta is not None
    assert meta["codec"] == "flac"
    assert meta["format"] == "FLAC"
    assert meta["quality"] == "44100Hz/16bit"
    assert local_quality_label(meta["quality"], meta["format"], meta["codec"]) == "44100Hz/16bit"


def test_stored_aac_hz_bit_is_rewritten_for_display():
    assert local_quality_label("44100Hz/16bit", "M4A", "aac") == "AAC"
    assert local_quality_label("44100Hz/16bit", "M4A", None) == "M4A"
    assert local_quality_label("44100Hz/16bit", "M4A", "alac") == "44100Hz/16bit"
    assert local_quality_label("44100Hz/16bit", "FLAC", "flac") == "44100Hz/16bit"
