"""Local playlist name lookup and M3U/M3U8 file parsing.

Used by the bot API to resolve playlist names without filesystem logic
leaking into HTTP routes.
"""

from __future__ import annotations

from pathlib import Path


def resolve_playlist_name(name: str, roots: list[Path]) -> Path | None:
    """Find a .m3u/.m3u8 file whose stem matches *name* (case-insensitive).

    Args:
        name: Playlist name to search for.
        roots: Directories to search recursively.

    Returns:
        Path to the first matching playlist file, or None.
    """
    wanted = name.strip().casefold()
    if not wanted:
        return None

    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            if candidate.suffix.lower() not in {".m3u", ".m3u8"}:
                continue
            if candidate.stem.casefold() == wanted:
                return candidate
    return None


def parse_playlist_file(path: Path) -> list[str]:
    """Parse an M3U/M3U8 playlist file into a list of track paths.

    Skips blank lines and lines starting with ``#`` (comments / EXTINF).

    Args:
        path: Path to the playlist file.

    Returns:
        List of track path strings (relative or absolute as written in the file).
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
