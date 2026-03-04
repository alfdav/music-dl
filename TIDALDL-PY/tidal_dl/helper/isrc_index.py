"""isrc_index.py

Persistent, thread-safe index mapping ISRC identifiers to the local paths of
already-downloaded tracks. Used by :class:`~tidal_dl.download.Download` to skip
re-downloading a track that already exists somewhere in the library, even when
the output path for the current context (album vs. playlist vs. mix) differs
from where the track was previously stored.

The index is a plain JSON file stored alongside the other tidal-dl config files
(``~/.config/tidal-dl/isrc_index.json``).  Each entry is::

    { "ISRC_VALUE": "/absolute/path/to/track.flac", ... }

Stale entries (path no longer on disk) are pruned lazily by
:meth:`IsrcIndex.contains`.
"""

from __future__ import annotations

import json
import pathlib
from threading import Lock


class IsrcIndex:
    """Thread-safe persistent index of ISRC → absolute file path.

    Args:
        index_path (pathlib.Path): Where to read/write the JSON index file.
    """

    def __init__(self, index_path: pathlib.Path) -> None:
        self._path: pathlib.Path = index_path
        self._data: dict[str, str] = {}
        self._lock: Lock = Lock()
        self._dirty_count: int = 0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Deserialise the index from disk, silently ignoring missing/corrupt files."""
        try:
            if self._path.is_file():
                with self._path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    with self._lock:
                        self._data = {str(k): str(v) for k, v in loaded.items() if k and v}
        except Exception:
            # Corrupt file — start fresh; will be overwritten on next save.
            with self._lock:
                self._data = {}

    def save(self) -> None:
        """Serialise the index to disk, creating parent directories as needed."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                snapshot = dict(self._data)
            with self._path.open("w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # Non-fatal — dedup simply won't persist this session

    # ------------------------------------------------------------------
    # Query / mutation
    # ------------------------------------------------------------------

    def contains(self, isrc: str) -> bool:
        """Return True if *isrc* is indexed and its recorded path still exists.

        Stale entries (file deleted/moved) are pruned from the in-memory dict
        so they don't accumulate indefinitely.

        Args:
            isrc (str): ISRC identifier to look up.

        Returns:
            bool: True if a live file for this ISRC is already in the library.
        """
        if not isrc:
            return False

        with self._lock:
            path_str = self._data.get(isrc)

        if path_str is None:
            return False

        if pathlib.Path(path_str).is_file():
            return True

        # Prune stale entry
        with self._lock:
            self._data.pop(isrc, None)

        return False

    def add(self, isrc: str, path: pathlib.Path) -> None:
        """Record *isrc* → *path* in the index.

        Only the most-recently-downloaded path is kept per ISRC. Thread-safe.

        Args:
            isrc (str): ISRC identifier.
            path (pathlib.Path): Absolute path to the downloaded file.
        """
        if not isrc or not path:
            return

        with self._lock:
            self._data[isrc] = str(path.absolute())
            self._dirty_count += 1

    def maybe_flush(self, every_n: int = 25) -> None:
        if every_n <= 0:
            return
        with self._lock:
            should_flush = self._dirty_count >= every_n
            if should_flush:
                self._dirty_count = 0
        if should_flush:
            self.save()

    # ------------------------------------------------------------------
    # Helpers for testing
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Number of entries currently in the index."""
        with self._lock:
            return len(self._data)
