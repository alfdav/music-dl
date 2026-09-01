"""Library DB helpers and constants."""

from __future__ import annotations

import datetime
import pathlib
import re
import sqlite3
import unicodedata

_SQLITE_CORRUPTION_MESSAGES = (
    "file is not a database",
    "database disk image is malformed",
)


def canonical_library_path(path: str) -> str:
    """Index paths as NFC so macOS NFD walk strings match tag/download NFC."""
    return unicodedata.normalize("NFC", str(path))


def _is_sqlite_corruption(exc: sqlite3.DatabaseError) -> bool:
    message = str(exc).casefold()
    return any(fragment in message for fragment in _SQLITE_CORRUPTION_MESSAGES)


def _corrupt_backup_path(path: pathlib.Path) -> pathlib.Path:
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.corrupt-{stamp}")
    index = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.corrupt-{stamp}-{index}")
        index += 1
    return candidate


def _quarantine_corrupt_db(path: pathlib.Path) -> None:
    if not path.exists():
        return

    backup = _corrupt_backup_path(path)
    path.replace(backup)
    for suffix in ("-wal", "-shm"):
        sidecar = path.with_name(f"{path.name}{suffix}")
        if sidecar.exists():
            sidecar.replace(backup.with_name(f"{backup.name}{suffix}"))


def _normalize_track_text(value: str | None) -> str:
    return (value or "").strip().casefold()


def _local_quality_rank(
    quality: str | None,
    fmt: str | None,
    codec: str | None = None,
) -> int:
    codec_family = (codec or "").casefold()
    if codec_family in {"aac", "mp3", "ogg", "opus", "vorbis"}:
        return 1
    if codec_family not in {"flac", "alac", "pcm"}:
        return 0
    if not quality:
        return 2

    direct = {
        "LOW": 0,
        "HIGH": 1,
        "LOSSLESS": 2,
        "HI_RES": 3,
        "HI_RES_LOSSLESS": 4,
        "FLAC": 2,
    }.get(quality.upper())
    if direct is not None:
        return direct

    match = re.match(r"(\d+)Hz/(\d+)bit", quality, re.IGNORECASE)
    if not match:
        return 0

    sample_rate = int(match.group(1))
    bit_depth = int(match.group(2))
    if bit_depth >= 24 and sample_rate > 48000:
        return 4
    if bit_depth >= 24:
        return 3
    if bit_depth >= 16:
        return 2
    return 0


def _path_suffix_rank(path: str | None) -> int:
    stem = pathlib.Path(path or "").stem
    return 1 if re.search(r"_\d{2}$", stem) else 0


def _album_track_key(row: dict) -> tuple[str, str]:
    return (
        _normalize_track_text(row.get("title")),
        _normalize_track_text(row.get("artist")),
    )


def _album_track_preference(row: dict) -> tuple[int, int, int, str]:
    path = row.get("path") or ""
    return (
        -_local_quality_rank(
            row.get("quality"), row.get("format"), row.get("codec")
        ),
        _path_suffix_rank(path),
        len(path),
        path,
    )


DOWNLOAD_JOB_FIELDS = {
    "kind",
    "status",
    "track_id",
    "name",
    "artist",
    "album",
    "cover_url",
    "quality",
    "progress",
    "error",
    "old_path",
    "new_path",
    "metadata_json",
    "created_at",
    "started_at",
    "finished_at",
}
