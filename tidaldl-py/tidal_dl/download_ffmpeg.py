"""FFmpeg helpers for media post-processing."""

from __future__ import annotations

import pathlib
import shutil
import subprocess

from tidalapi.media import AudioExtensions


def ffmpeg_executable(path_binary_ffmpeg: str | None) -> str:
    return path_binary_ffmpeg or shutil.which("ffmpeg") or "ffmpeg"


def run_ffmpeg(path_binary_ffmpeg: str | None, *args: str) -> None:
    subprocess.run([ffmpeg_executable(path_binary_ffmpeg), *args], check=True)


def video_convert(path_binary_ffmpeg: str | None, path_file: pathlib.Path) -> pathlib.Path:
    path_file_out = path_file.with_suffix(AudioExtensions.MP4)
    run_ffmpeg(
        path_binary_ffmpeg,
        "-y",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(path_file),
        "-codec",
        "copy",
        "-map",
        "0",
        "-loglevel",
        "quiet",
        str(path_file_out),
    )
    return path_file_out


def extract_flac(path_binary_ffmpeg: str | None, path_media_src: pathlib.Path) -> pathlib.Path:
    path_media_out = path_media_src.with_suffix(AudioExtensions.FLAC)
    run_ffmpeg(
        path_binary_ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-i",
        str(path_media_src),
        "-map",
        "0:a",
        "-vn",
        "-acodec",
        "copy",
        "-map_metadata",
        "0:g",
        "-loglevel",
        "quiet",
        str(path_media_out),
    )
    return path_media_out
