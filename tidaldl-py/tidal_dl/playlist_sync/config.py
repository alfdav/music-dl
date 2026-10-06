"""Playlist sync settings, read from the local Settings object."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from tidal_dl.playlist_sync.unicode_norm import nfc, nfc_path


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
    download_base_path: str = "~/download"
    plex_url: str = ""
    plex_section_id: str = ""
    plex_local_prefix: str = ""
    plex_server_prefix: str = ""
    plex_scan_timeout_sec: int = 600


def _allowlist(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)
    return tuple(nfc(str(part)).strip() for part in parts if nfc(str(part)).strip())


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
        download_base_path=_download_base(getattr(data, "download_base_path", "~/download")),
        plex_url=_text(getattr(data, "playlist_sync_plex_url", "")),
        plex_section_id=_text(getattr(data, "playlist_sync_plex_section_id", "")),
        plex_local_prefix=_prefix(getattr(data, "playlist_sync_plex_local_prefix", "")),
        plex_server_prefix=_prefix(getattr(data, "playlist_sync_plex_server_prefix", "")),
        plex_scan_timeout_sec=_timeout(getattr(data, "playlist_sync_plex_scan_timeout_sec", 600)),
    )


def _download_base(value: Any) -> str:
    raw = "~/download" if value is None or value == "" else str(value)
    return nfc_path(os.path.expanduser(raw))


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _prefix(value: Any) -> str:
    return nfc_path(_text(value))


def _timeout(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 600
    if parsed <= 0:
        return 600
    return parsed


def name_allowed(name: str, allowlist: tuple[str, ...]) -> bool:
    """Empty allowlist includes every playlist. Otherwise match trimmed casefold."""
    if not allowlist:
        return True
    folded = nfc(name).strip().casefold()
    return folded in {nfc(item).strip().casefold() for item in allowlist}
