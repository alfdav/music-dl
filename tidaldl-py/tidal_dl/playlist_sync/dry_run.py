"""One playlist-sync cycle that does not download and does not write to Plex."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from tidal_dl.playlist_sync.config import load_config
from tidal_dl.playlist_sync.cycle import run_cycle
from tidal_dl.playlist_sync.models import CycleReport


def _label(entry: dict[str, Any]) -> str:
    source = entry.get("source_track") or {}
    artist = str(source.get("artist") or "").strip()
    title = str(source.get("title") or "").strip()
    if artist and title:
        return f"{artist} — {title}"
    return title or artist or "track"


def planned_lines(report: CycleReport) -> list[str]:
    """Lines a dry-run prints: would download, would add, would remove."""
    lines: list[str] = []
    for entry in report.removed_in_plex:
        lines.append(f"would remove: {_label(entry)}")
    for playlist in report.playlists:
        for entry in playlist.tracks:
            action = entry.get("action")
            if action == "download":
                lines.append(f"would download: {_label(entry)}")
            elif action == "append":
                lines.append(f"would add: {_label(entry)}")
    if report.halted_reason:
        lines.append(f"halted: {report.halted_reason}")
    return lines


def run_dry_cycle(now: datetime | None = None, **kwargs: Any) -> CycleReport:
    """Run one cycle. ``dry_run`` stays on even when settings say otherwise."""
    settings = kwargs.pop("settings", None)
    cfg = replace(load_config(settings), enabled=True, dry_run=True)
    return run_cycle(now, settings=cfg, force=True, **kwargs)


def main() -> int:
    from tidal_dl.config import Settings, Tidal

    settings = Settings()
    tidal = Tidal(settings)

    def _print(message: str) -> None:
        print(message)

    if not tidal.resolve_source(fn_print=_print, allow_interactive_login=False):
        print("Not logged in. Run 'music-dl login' to connect this device.")
        return 1
    report = run_dry_cycle(settings=settings, tidal=tidal)
    for line in planned_lines(report):
        print(line)
    return 0 if report.halted_reason is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
