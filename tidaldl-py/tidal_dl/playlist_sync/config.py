"""Playlist sync settings, read from the local Settings object."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlaylistSyncConfig:
    enabled: bool = False
    dry_run: bool = True
    poll_minutes: int = 15
    max_per_cycle: int = 5
    max_per_day: int = 30
    gap_sec_min: float = 30
    gap_sec_max: float = 60
    allowlist: tuple[str, ...] = ()


def _allowlist(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)
    return tuple(str(part).strip() for part in parts if str(part).strip())


def load_config(settings: Any | None = None) -> PlaylistSyncConfig:
    """Read sync settings from a Settings wrapper, its data object, or a config."""
    if isinstance(settings, PlaylistSyncConfig):
        return settings
    if settings is None:
        from tidal_dl.config import Settings

        settings = Settings()
    data = getattr(settings, "data", settings)
    low = float(getattr(data, "playlist_sync_gap_sec_min", 30))
    high = float(getattr(data, "playlist_sync_gap_sec_max", 60))
    if low > high:
        low, high = high, low
    return PlaylistSyncConfig(
        enabled=bool(getattr(data, "playlist_sync_enabled", False)),
        dry_run=bool(getattr(data, "playlist_sync_dry_run", True)),
        poll_minutes=int(getattr(data, "playlist_sync_poll_minutes", 15)),
        max_per_cycle=int(getattr(data, "playlist_sync_max_per_cycle", 5)),
        max_per_day=int(getattr(data, "playlist_sync_max_per_day", 30)),
        gap_sec_min=low,
        gap_sec_max=high,
        allowlist=_allowlist(getattr(data, "playlist_sync_allowlist", ())),
    )


def name_allowed(name: str, allowlist: tuple[str, ...]) -> bool:
    """Empty allowlist includes every playlist. Otherwise match trimmed casefold."""
    if not allowlist:
        return True
    folded = (name or "").strip().casefold()
    return folded in {item.strip().casefold() for item in allowlist}
