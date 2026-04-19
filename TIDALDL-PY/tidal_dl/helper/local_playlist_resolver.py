"""Local playlist resolver — finds and parses .m3u/.m3u8 files by name."""

from __future__ import annotations

import time
from pathlib import Path

# F-016: cache the playlist index so /play queries don't trigger a full
# library walk each time. Caches {name_casefold -> Path} per frozenset
# of roots, with a TTL after which the index is rebuilt. Bounded staleness
# acceptable for V1: new playlists appear within TTL_SECONDS of creation.
_INDEX_CACHE: dict[frozenset[str], tuple[dict[str, Path], float]] = {}
_TTL_SECONDS = 60.0


def _build_playlist_index(roots: list[Path]) -> dict[str, Path]:
    """Walk roots once and map casefolded playlist name -> path.

    Uses iterdir with manual recursion (depth-bounded) and filters by
    lowercased suffix so case-sensitive filesystems still match
    uppercase .M3U/.M3U8 extensions.
    """
    index: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in {".m3u", ".m3u8"}:
                continue
            key = candidate.stem.casefold()
            # First-seen wins (consistent with prior first-match behavior)
            index.setdefault(key, candidate)
    return index


def _get_playlist_index(roots: list[Path]) -> dict[str, Path]:
    cache_key = frozenset(str(r) for r in roots)
    cached = _INDEX_CACHE.get(cache_key)
    now = time.time()
    if cached is not None and (now - cached[1]) < _TTL_SECONDS:
        return cached[0]
    index = _build_playlist_index(roots)
    _INDEX_CACHE[cache_key] = (index, now)
    return index


def invalidate_playlist_index_cache() -> None:
    """Drop the cached playlist index. For tests and after bulk changes."""
    _INDEX_CACHE.clear()


def resolve_playlist_name(name: str, roots: list[Path]) -> Path | None:
    """Find a playlist file matching *name* (case-insensitive) across *roots*.

    Uses a TTL-cached index so repeated calls don't re-walk the library.
    The first call (or first after TTL expiry) scans *roots* recursively
    for .m3u / .m3u8 files. Subsequent calls within the TTL are O(1)
    dict lookups.
    """
    wanted = name.strip().casefold()
    if not wanted:
        return None
    index = _get_playlist_index(roots)
    return index.get(wanted)


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
