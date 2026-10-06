"""Read artist, title, and duration from a downloaded file."""

from __future__ import annotations

from typing import Any


def _tag(audio: Any, key: str) -> str:
    value = audio.get(key) if audio is not None else None
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value) if value else ""


def read_audio_tags(path: str) -> dict[str, Any] | None:
    """Return tags via mutagen, the same reader the library scanner uses."""
    from mutagen._file import File as mutagen_file

    try:
        audio = mutagen_file(path, easy=True)
    except Exception:  # noqa: BLE001
        return None
    if audio is None:
        return None
    duration = None
    info = getattr(audio, "info", None)
    length = getattr(info, "length", None) if info is not None else None
    if length is not None:
        duration = float(length)
    isrc = _tag(audio, "isrc").strip()
    return {
        "title": _tag(audio, "title"),
        "artist": _tag(audio, "artist"),
        "album": _tag(audio, "album"),
        "version": _tag(audio, "version"),
        "duration": duration,
        "isrc": isrc or None,
    }
