"""Pace Tidal first/auth API calls. Never wrap CDN/media byte transfers."""

from __future__ import annotations

import random
import time
from threading import Event, Lock
from typing import Callable


Clock = Callable[[], float]
Sleeper = Callable[[float], None]

_MAX_DELAY_SEC = 30.0
_RECOVERY_SUCCESS_COUNT = 50

_shared: TidalApiPacer | None = None
_shared_lock = Lock()


def retry_after_seconds(response: object | None, fallback: float) -> float:
    """Return Retry-After seconds from an HTTP response, else *fallback*."""
    headers = getattr(response, "headers", None)
    if not headers:
        return float(fallback)
    raw = headers.get("Retry-After")
    if raw is None:
        return float(fallback)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return float(fallback)


class TidalApiPacer:
    """Inter-call delay for Tidal stream-info / auth API pressure only."""

    def __init__(
        self,
        delay_min: float = 3.0,
        delay_max: float = 5.0,
        sleeper: Sleeper | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.delay_min = float(delay_min)
        self.delay_max = float(delay_max)
        self.rate_limit_hits = 0
        self.successful_since_limit = 0
        self._lock = Lock()
        self._last_call_mono: float | None = None
        self._sleeper = sleeper or time.sleep
        self._clock = clock or time.monotonic

    def wait_before_api(self, *, enabled: bool, event_stop: Event | None = None) -> float:
        """Wait since the previous API call. The first call never sleeps."""
        with self._lock:
            now = self._clock()
            slept = 0.0
            if enabled and self._last_call_mono is not None:
                gap = random.SystemRandom().uniform(self.delay_min, self.delay_max)
                remaining = gap - (now - self._last_call_mono)
                if remaining > 0:
                    self._sleep(remaining, event_stop)
                    slept = remaining
            self._last_call_mono = self._clock()
            return slept

    def note_429(self, retry_after_sec: float | None = None) -> float:
        """Widen adaptive delay and return seconds to honor now (Retry-After wins)."""
        with self._lock:
            self.rate_limit_hits += 1
            self.successful_since_limit = 0
            self.delay_min = min(self.delay_min * 2, _MAX_DELAY_SEC)
            self.delay_max = min(self.delay_max * 2, _MAX_DELAY_SEC)
            if retry_after_sec is not None:
                return max(0.0, float(retry_after_sec))
            return self.delay_max

    def note_success(self, baseline_min: float, baseline_max: float) -> tuple[float, float, bool]:
        """Count a successful track on the process-wide window.

        After ``_RECOVERY_SUCCESS_COUNT`` successes following any 429, halve the
        shared delay (floored at *baseline_min* / *baseline_max*). Callers do
        not need to have seen the 429 themselves — a later GUI ``Download``
        can recover the window.

        Returns:
            tuple[float, float, bool]: Current ``(delay_min, delay_max)`` and
            whether this call relaxed the window.
        """
        with self._lock:
            self.successful_since_limit += 1
            relaxed = False
            if self.rate_limit_hits > 0 and self.successful_since_limit >= _RECOVERY_SUCCESS_COUNT:
                self.successful_since_limit = 0
                self.delay_min = max(self.delay_min / 2, float(baseline_min))
                self.delay_max = max(self.delay_max / 2, float(baseline_max))
                relaxed = True
            return self.delay_min, self.delay_max, relaxed

    def _sleep(self, seconds: float, event_stop: Event | None) -> None:
        if event_stop is not None:
            event_stop.wait(seconds)
            return
        self._sleeper(seconds)


def shared_pacer() -> TidalApiPacer:
    """Process-wide pacer so GUI workers share one API gate."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = TidalApiPacer()
        return _shared


def reset_shared_pacer_for_tests() -> None:
    """Drop the process-wide pacer. Tests only."""
    global _shared
    with _shared_lock:
        _shared = None
