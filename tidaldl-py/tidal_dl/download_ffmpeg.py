"""FFmpeg helpers for media post-processing."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

from tidalapi.media import AudioExtensions


def ffmpeg_executable(path_binary_ffmpeg: str | None) -> str:
    return path_binary_ffmpeg or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_executable(path_binary_ffmpeg: str | None) -> str:
    """ffprobe next to the configured ffmpeg, else the one on PATH."""
    ffmpeg = pathlib.Path(ffmpeg_executable(path_binary_ffmpeg))
    sibling_name = "ffprobe.exe" if ffmpeg.name.lower() == "ffmpeg.exe" else "ffprobe"
    sibling = ffmpeg.with_name(sibling_name)
    if sibling.is_file():
        return str(sibling)
    return shutil.which("ffprobe") or "ffprobe"


def audio_stream_duration_seconds(path: pathlib.Path, path_binary_ffmpeg: str | None = None) -> float | None:
    """Duration of the first audio stream. Cover art is a different stream."""
    try:
        proc = subprocess.run(
            [
                ffprobe_executable(path_binary_ffmpeg),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    try:
        payload = json.loads(proc.stdout or "")
    except json.JSONDecodeError:
        return None
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        return None
    try:
        return float(streams[0]["duration"])
    except (KeyError, TypeError, ValueError):
        return None


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
