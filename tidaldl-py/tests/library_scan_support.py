"""Helpers for library scan and reconcile tests.

Paths are generic fakes under pytest's tmp_path (or literal /music/... strings).
"""

from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

import pytest

from tidal_dl.helper.library_db import LibraryDB

DURATIONS: dict[str, int] = {}

_SKIP_CHMOD = sys.platform == "win32" or getattr(os, "geteuid", lambda: 1)() == 0

skip_unless_chmod_blocks = pytest.mark.skipif(
    _SKIP_CHMOD,
    reason="chmod 000 does not block root or Windows",
)


def write_wav(path: Path, frames: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * frames)


def fake_metadata(path, scan_dirs=None):
    del scan_dirs
    file_path = Path(path)
    if not file_path.is_file():
        return None
    return {
        "path": str(file_path),
        "name": file_path.stem,
        "artist": file_path.parts[-3],
        "album": file_path.parts[-2],
        "duration": DURATIONS.get(file_path.name, 1),
        "isrc": "",
        "genre": None,
        "quality": "WAV",
        "format": "WAV",
        "codec": "pcm",
        "metadata_complete": True,
        "is_local": True,
    }


def open_db(tmp_path: Path) -> LibraryDB:
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    return db


def legacy_row(db: LibraryDB, path: Path, duration: int) -> None:
    """A row as an older app wrote it: no file identity, never missing."""
    db.record(
        str(path),
        status="tagged",
        artist=path.parts[-3],
        title=path.stem,
        album=path.parts[-2],
        duration=duration,
        quality="WAV",
        fmt="WAV",
        codec="pcm",
        metadata_complete=True,
    )


def build_legacy_library(root: Path, tmp_path: Path) -> dict[str, list[Path]]:
    """Unchanged rows, three kinds of move, and files that have no row yet.

    The unchanged set is larger than 100 so the mass-prune guard can fire.
    """
    db = open_db(tmp_path)
    n = 0
    out: dict[str, list[Path]] = {key: [] for key in (
        "unchanged",
        "layout_old",
        "layout_new",
        "recycled_old",
        "renamed_old",
        "renamed_new",
        "new",
    )}

    def track(album_dir: Path, index: int) -> tuple[Path, int]:
        nonlocal n
        n += 1
        name = f"{index:02d} Song {n}.wav"
        DURATIONS[name] = 100 + n
        return album_dir / name, 100 + n

    for album in range(12):
        for index in range(1, 11):
            path, duration = track(root / f"Artist {album}" / f"Album {album}", index)
            write_wav(path, duration)
            legacy_row(db, path, duration)
            out["unchanged"].append(path)
    for index in range(1, 11):
        old, duration = track(root / "Artist A" / "Artist A - Album One", index)
        new = root / "Artist A" / "Album One" / old.name
        write_wav(new, duration)
        legacy_row(db, old, duration)
        out["layout_old"].append(old)
        out["layout_new"].append(new)
    for index in range(1, 11):
        old, duration = track(root / "Artist C" / "Album Three", index)
        write_wav(root / "#recycle" / "Artist C" / "Album Three" / old.name, duration)
        legacy_row(db, old, duration)
        out["recycled_old"].append(old)
    for index in range(1, 11):
        old, duration = track(root / "Artist E" / "Old Name", index)
        new = root / "Artist E" / "Renamed" / old.name
        write_wav(new, duration)
        legacy_row(db, old, duration)
        out["renamed_old"].append(old)
        out["renamed_new"].append(new)
    for index in range(1, 11):
        path, duration = track(root / "Artist D" / "Album Four", index)
        write_wav(path, duration)
        out["new"].append(path)
    db.commit()
    db.close()
    return out


def rows_by_path(tmp_path: Path) -> dict[str, dict]:
    db = open_db(tmp_path)
    rows = {row["path"]: row for row in db.identity_rows()}
    db.close()
    return rows


def dir_count(tmp_path: Path) -> int:
    db = open_db(tmp_path)
    count = len(db.dir_signatures())
    db.close()
    return count


class StatOverride:
    """os.stat_result stand-in with a chosen inode and device."""

    def __init__(self, real, *, inode: int, device: int) -> None:
        self._real = real
        self.st_ino = inode
        self.st_dev = device

    def __getattr__(self, name: str):
        return getattr(self._real, name)
