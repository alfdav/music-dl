"""cache.py

Thread-safe, TTL-backed in-memory cache for TIDAL API responses.

Used by :func:`~tidal_dl.helper.tidal.instantiate_media` to avoid redundant
HTTP round-trips when the same media object is requested multiple times during
a single download session (e.g. every track in an album re-fetching the same
album object).

Example usage::

    cache = TTLCache(ttl_sec=300)
    cache.set("track:12345", track_obj)
    result = cache.get("track:12345")   # returns track_obj
    cache.invalidate("track:12345")     # removes one entry
    cache.clear()                       # empties everything
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any


class TTLCache:
    """Thread-safe in-memory cache with per-entry time-to-live expiry.

    Entries are considered stale once ``ttl_sec`` seconds have elapsed since
    they were last written.  Stale entries are pruned lazily on ``get()``.

    Args:
        ttl_sec (int): Seconds before a cached entry expires. Defaults to 300.
    """

    def __init__(self, ttl_sec: int = 300) -> None:
        self._ttl: int = ttl_sec
        self._data: dict[str, Any] = {}
        self._timestamps: dict[str, float] = {}
        self._lock: Lock = Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """Return the cached value for *key*, or ``None`` if absent / stale.

        A stale entry is pruned from the cache before returning ``None``.

        Args:
            key (str): Cache key.

        Returns:
            The cached object, or ``None``.
        """
        with self._lock:
            if key not in self._data:
                return None

            age = time.monotonic() - self._timestamps[key]
            if age > self._ttl:
                # Prune stale entry
                del self._data[key]
                del self._timestamps[key]
                return None

            return self._data[key]

    def set(self, key: str, value: Any) -> None:
        """Store *value* under *key*, resetting its TTL.

        Args:
            key (str): Cache key.
            value: Object to cache.
        """
        with self._lock:
            self._data[key] = value
            self._timestamps[key] = time.monotonic()

    def invalidate(self, key: str) -> None:
        """Remove a single entry from the cache (no-op if absent).

        Args:
            key (str): Cache key to remove.
        """
        with self._lock:
            self._data.pop(key, None)
            self._timestamps.pop(key, None)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        with self._lock:
            self._data.clear()
            self._timestamps.clear()

    # ------------------------------------------------------------------
    # Helpers / introspection
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Number of entries currently held (includes potentially stale ones)."""
        with self._lock:
            return len(self._data)
