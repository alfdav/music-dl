"""Local playlist resolver — finds and parses .m3u/.m3u8 files by name."""

from __future__ import annotations

from pathlib import Path


def resolve_playlist_name(name: str, roots: list[Path]) -> Path | None:
    """Find a playlist file matching *name* (case-insensitive) across *roots*.

    Recursively searches each root for .m3u and .m3u8 files whose stem
    matches *name* (case-insensitive). music-dl writes playlists to
    nested paths (per-album subdirs, "Playlists/{name}/..." etc.), so
    immediate-children-only matching misses the common case. Returns
    the first match in sorted order, or None.
    """
    wanted = name.strip().casefold()
    if not wanted:
        return None

    for root in roots:
        if not root.is_dir():
            continue
        for candidate in sorted(root.rglob("*")):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in {".m3u", ".m3u8"}:
                continue
            if candidate.stem.casefold() == wanted:
                return candidate
    return None


def parse_playlist_file(path: Path) -> list[str]:
    """Parse an .m3u/.m3u8 file, returning absolute track paths in order.

    Skips comment lines (starting with #) and blank lines. music-dl
    writes relative paths in generated playlists, so each entry is
    resolved against the playlist file's directory — callers get
    absolute paths they can use directly.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    base = path.parent
    tracks: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        track_path = Path(stripped)
        if not track_path.is_absolute():
            track_path = (base / track_path).resolve()
        tracks.append(str(track_path))
    return tracks
