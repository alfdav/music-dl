"""library_scanner.py

Scans a directory tree for audio files and extracts ISRC identifiers from
their metadata tags.  The results are fed into an :class:`~tidal_dl.helper.isrc_index.IsrcIndex`
so that tidal-dl can skip re-downloading tracks that already exist on disk,
even if they were not originally downloaded through tidal-dl.

Supported formats and tag locations (mirrors the write logic in metadata.py):
    - FLAC  → Vorbis Comment ``ISRC``
    - MP3   → ID3 ``TSRC`` frame
    - MP4 / M4A → iTunes atom ``isrc``
    - OGG   → Vorbis Comment ``ISRC``
"""

from __future__ import annotations

import pathlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import mutagen
import mutagen.flac
import mutagen.mp3
import mutagen.mp4
import mutagen.oggvorbis

if TYPE_CHECKING:
    from tidal_dl.helper.isrc_index import IsrcIndex


# Audio file extensions to consider during scanning.
SCAN_EXTENSIONS: frozenset[str] = frozenset({".flac", ".mp3", ".m4a", ".mp4", ".ogg"})


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Summary returned after a scan run.

    Attributes:
        files_scanned (int): Total audio files examined.
        isrcs_found (int): New ISRCs successfully extracted and added to the index.
        already_indexed (int): Files whose ISRC was already present in the index.
        no_isrc (int): Files that had no ISRC tag at all.
        errors (int): Files that could not be read (permission error, corrupt tag, etc.).
        elapsed_sec (float): Wall-clock seconds the scan took.
        error_paths (list[str]): Paths of files that raised errors (capped at 50).
    """

    files_scanned: int = 0
    isrcs_found: int = 0
    already_indexed: int = 0
    no_isrc: int = 0
    errors: int = 0
    elapsed_sec: float = 0.0
    error_paths: list[str] = field(default_factory=list)

    # Maximum error paths stored to avoid unbounded memory use.
    _ERROR_PATH_CAP: int = field(default=50, init=False, repr=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_isrc(path: pathlib.Path) -> str | None:
    """Return the ISRC string from *path*'s audio metadata, or None if absent.

    Mirrors the tag keys written by :class:`~tidal_dl.metadata.Metadata`:
        - FLAC  → Vorbis Comment ``ISRC``
        - MP3   → ID3 ``TSRC``
        - MP4/M4A → ``isrc`` atom
        - OGG   → Vorbis Comment ``ISRC``

    Args:
        path (pathlib.Path): Path to the audio file.

    Returns:
        str | None: Upper-cased ISRC string, or None if not found / not readable.
    """
    try:
        audio = mutagen.File(str(path), easy=False)
    except Exception:
        return None

    if audio is None or audio.tags is None:
        return None

    isrc: str | None = None

    if isinstance(audio, mutagen.flac.FLAC):
        # Vorbis Comment: value is a list of strings
        values = audio.tags.get("ISRC") or audio.tags.get("isrc")
        if values:
            isrc = values[0] if isinstance(values, list) else str(values)

    elif isinstance(audio, mutagen.mp3.MP3):
        # ID3: TSRC frame, .text is a list
        frames = audio.tags.getall("TSRC")
        for frame in frames:
            text = getattr(frame, "text", [])
            if text:
                isrc = text[0]
                break

    elif isinstance(audio, mutagen.mp4.MP4):
        # iTunes atom: value may be str or bytes
        raw = audio.tags.get("isrc")
        if raw is not None:
            if isinstance(raw, list):
                raw = raw[0] if raw else None
            if isinstance(raw, bytes):
                isrc = raw.decode("utf-8", errors="ignore")
            elif isinstance(raw, mutagen.mp4.MP4FreeForm):
                isrc = bytes(raw).decode("utf-8", errors="ignore")
            elif isinstance(raw, str):
                isrc = raw

    elif isinstance(audio, mutagen.oggvorbis.OggVorbis):
        # Vorbis Comment: same as FLAC
        values = audio.tags.get("ISRC") or audio.tags.get("isrc")
        if values:
            isrc = values[0] if isinstance(values, list) else str(values)

    if isrc:
        isrc = isrc.strip().upper()
        return isrc if isrc else None

    return None


# ---------------------------------------------------------------------------
# Public scanner
# ---------------------------------------------------------------------------


def scan_directory(
    root: pathlib.Path,
    isrc_index: "IsrcIndex",
    *,
    dry_run: bool = False,
    on_file: Callable[[pathlib.Path], None] | None = None,
) -> ScanResult:
    """Walk *root* recursively, extract ISRCs, and populate *isrc_index*.

    The caller is responsible for calling ``isrc_index.save()`` after this
    function returns (unless ``dry_run`` is True, in which case no writes
    are performed at all).

    Args:
        root (pathlib.Path): Directory to scan recursively.
        isrc_index (IsrcIndex): Index to populate with discovered ISRCs.
        dry_run (bool): If True, discover ISRCs but do not mutate *isrc_index*.
        on_file (Callable | None): Optional callback invoked with each file
            path just before it is examined.  Useful for driving a progress bar.

    Returns:
        ScanResult: Summary of the scan.
    """
    result = ScanResult()
    start = time.monotonic()

    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SCAN_EXTENSIONS:
            continue

        if on_file is not None:
            on_file(file_path)

        result.files_scanned += 1

        try:
            isrc = _extract_isrc(file_path)
        except Exception:
            result.errors += 1
            if len(result.error_paths) < result._ERROR_PATH_CAP:
                result.error_paths.append(str(file_path))
            continue

        if not isrc:
            result.no_isrc += 1
            continue

        if isrc_index.contains(isrc):
            result.already_indexed += 1
            continue

        # New ISRC — record it.
        if not dry_run:
            isrc_index.add(isrc, file_path)

        result.isrcs_found += 1

    result.elapsed_sec = time.monotonic() - start
    return result
