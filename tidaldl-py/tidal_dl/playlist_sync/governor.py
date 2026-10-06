"""One download at a time, with per-cycle and per-day caps."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

from tidal_dl.download.api_pacing import TidalApiPacer
from tidal_dl.playlist_sync.ledger import Ledger
from tidal_dl.playlist_sync.models import DownloadResult

T = TypeVar("T")

_HALT_STATUSES = {401, 429}


def status_code_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    if type(exc).__name__ == "TooManyRequests":
        return 429
    return None


class Governor:
    def __init__(
        self,
        *,
        ledger: Ledger,
        day: str,
        max_per_cycle: int,
        max_per_day: int,
        gap_sec_min: float,
        gap_sec_max: float,
        auth_state: Callable[[], str],
        sleep: Callable[[float], None] | None = None,
        rng: random.Random | None = None,
        pacer: TidalApiPacer | None = None,
        clock: Callable[[], float] | None = None,
        persist_counts: bool = True,
    ) -> None:
        self.ledger = ledger
        self.day = day
        self.max_per_cycle = max_per_cycle
        self.max_per_day = max_per_day
        self.gap_sec_min = gap_sec_min
        self.gap_sec_max = gap_sec_max
        self._auth_state = auth_state
        self._sleep = sleep or time.sleep
        self._rng = rng or random.Random()
        self._clock = clock or time.monotonic
        self.pacer = pacer or TidalApiPacer(sleeper=self._sleep, clock=self._clock)
        self.persist_counts = persist_counts
        self.cycle_count = 0
        self.halted_reason: str | None = None
        self._in_flight = False

    def halt(self, reason: str) -> None:
        if self.halted_reason is None:
            self.halted_reason = reason

    def auth_ok(self) -> bool:
        if self.halted_reason:
            return False
        state = self._auth_state()
        if state != "credentials_ready":
            self.halt(f"auth_state={state}")
            return False
        return True

    def can_download(self) -> bool:
        if self.halted_reason:
            return False
        if self.cycle_count >= self.max_per_cycle:
            return False
        used = self.ledger.downloads_on(self.day)
        if not self.persist_counts:
            used += self.cycle_count
        return used < self.max_per_day

    def note_http(self, status: int | None) -> None:
        if status in _HALT_STATUSES:
            self.halt(str(status))

    def _account(self) -> None:
        self.cycle_count += 1
        if self.persist_counts:
            self.ledger.increment_downloads(self.day)

    def download(self, fn: Callable[[], DownloadResult]) -> DownloadResult | None:
        """Run one download. Applies the gap, then the API pacer, then fn."""
        if not self.auth_ok() or not self.can_download():
            return None
        if self._in_flight:
            raise RuntimeError("playlist sync already has a download in flight")
        if self.cycle_count > 0:
            self._sleep(self._rng.uniform(self.gap_sec_min, self.gap_sec_max))
        self.pacer.wait_before_api(enabled=True)
        if self.halted_reason:
            return None
        self._in_flight = True
        try:
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 — download errors become a result; 401 and 429 halt
                code = status_code_of(exc)
                self.note_http(code)
                self._account()
                return DownloadResult(status="failed", http_status=code, error=type(exc).__name__)
        finally:
            self._in_flight = False
        self.note_http(result.http_status)
        self._account()
        return result
