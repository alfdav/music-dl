"""Local playlist resolver — finds and parses .m3u/.m3u8 files by name."""

from __future__ import annotations

from pathlib import Path


def resolve_playlist_name(name: str, roots: list[Path]) -> Path | None:
    """Find a playlist file matching *name* (case-insensitive) across *roots*.

    Searches for .m3u and .m3u8 files whose stem matches *name*
    (case-insensitive). Returns the first match, or None.
    """
    wanted = name.strip().casefold()
    if not wanted:
        return None

    for root in roots:
        if not root.is_dir():
            continue
        for candidate in sorted(root.iterdir()):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in {".m3u", ".m3u8"}:
                continue
            if candidate.stem.casefold() == wanted:
                return candidate
    return None


def parse_playlist_file(path: Path) -> list[str]:
    """Parse an .m3u/.m3u8 file, returning track paths in order.

    Skips comment lines (starting with #) and blank lines.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    tracks: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tracks.append(stripped)
    return tracks
