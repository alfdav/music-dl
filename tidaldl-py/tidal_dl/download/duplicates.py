"""Download duplicates helpers."""

from tidal_dl.download._common import *


def track_file_is_in_output(
    downloader,
    media,
    file_template: str | None,
    list_position: int = 0,
    list_total: int = 0,
) -> bool:
    """True when this job's dest already has the track, even if skip_existing is off.

    The path is checked directly. Do not flip the shared skip_existing flag:
    other tracks are downloading on this same downloader.
    """
    prepare = getattr(downloader, "_prepare_file_paths_and_skip_logic", None)
    if not callable(prepare):
        return False
    try:
        result = prepare(
            media,
            file_template or "{track_title}",
            None,
            list_position,
            list_total,
            bypass_isrc=True,
        )
    except (TypeError, ValueError, OSError, AttributeError):
        return False
    if not isinstance(result, tuple) or not result:
        return False
    try:
        return check_file_exists(pathlib.Path(result[0]), extension_ignore=False)
    except (TypeError, ValueError, OSError):
        return False


def dest_already_present(
    downloader,
    media,
    source_path: str,
    file_template: str | None = None,
    list_position: int = 0,
    list_total: int = 0,
) -> bool:
    """True when a file exists at this job's dest (including legacy `_/`).

    Presence is path-only. An ISRC or library row at another location must not
    count as dest — playlists and mixes still copy into their own folder.
    """
    if getattr(downloader, "skip_existing", False) is not True:
        return False
    prepare = getattr(downloader, "_prepare_file_paths_and_skip_logic", None)
    if not callable(prepare):
        return False
    template = (
        file_template
        or getattr(getattr(downloader.settings, "data", None), "format_album", None)
        or "{track_title}"
    )
    try:
        result = prepare(media, template, None, list_position, list_total, bypass_isrc=True)
    except TypeError:
        return False
    if not isinstance(result, tuple) or len(result) < 3:
        return False
    dest, _ext, skip_file = result[0], result[1], result[2]
    if skip_file is True:
        return True
    try:
        return pathlib.Path(dest).resolve() == pathlib.Path(source_path).resolve()
    except (OSError, TypeError, ValueError):
        return False


class DuplicateMixin:
    def _preflight_isrc_scan(
        self,
        items: list,
        checkpoint: "DownloadCheckpoint | None" = None,
        ensure_complete: bool = False,
        file_template: str | None = None,
    ) -> dict[str, str]:
        """Scan items for duplicate ISRCs before downloads start.

        Returns a dict mapping str(track.id) -> action ('copy', 'redownload', 'skip').
        Empty dict means no duplicates were found or ISRC dedup is disabled.

        When *ensure_complete* is True (collections: albums, playlists, mixes),
        duplicates are copied or re-downloaded unless dest already exists.
        """
        if not self.settings.data.skip_duplicate_isrc:
            return {}

        hits_with_source: list[tuple] = []  # (Track, path_str) — source file exists
        hits_missing_source: list[tuple] = []  # (Track, path_str) — source file gone
        list_total = len(items)
        positions = {
            str(item_media.id): index
            for index, item_media in enumerate(items, start=1)
            if isinstance(item_media, Track) and getattr(item_media, "id", None) is not None
        }

        for item_media in items:
            if not isinstance(item_media, Track):
                continue
            # Skip tracks already completed in this output dir.
            if (
                checkpoint is not None
                and checkpoint.status_of(str(item_media.id)) == STATUS_DOWNLOADED
                and track_file_is_in_output(
                    self,
                    item_media,
                    file_template,
                    list_position=positions.get(str(item_media.id), 0),
                    list_total=list_total,
                )
            ):
                continue
            isrc = getattr(item_media, "isrc", None)
            if not isrc:
                continue
            path_str = self._library_db_for_current_thread().primary_path_for_isrc(isrc)
            if path_str is None:
                continue
            if pathlib.Path(path_str).is_file():
                hits_with_source.append((item_media, path_str))
            else:
                hits_missing_source.append((item_media, path_str))

        if not hits_with_source and not hits_missing_source:
            return {}

        # Collections must always be complete: copy if source exists, re-download if not.
        # Dest already present (including v1.7 `Artist/Album/_/Track`) is skip, not copy.
        if ensure_complete:
            resolved = {}
            skip_n = 0
            copy_n = 0
            for track, path_str in hits_with_source:
                if dest_already_present(
                    self,
                    track,
                    path_str,
                    file_template=file_template,
                    list_position=positions.get(str(track.id), 0),
                    list_total=list_total,
                ):
                    resolved[str(track.id)] = "skip"
                    skip_n += 1
                else:
                    resolved[str(track.id)] = "copy"
                    copy_n += 1
            for track, _ in hits_missing_source:
                resolved[str(track.id)] = "redownload"
            if resolved:
                parts: list[str] = []
                if skip_n:
                    parts.append(f"{skip_n} track(s) already in library will be skipped")
                if copy_n:
                    parts.append(f"{copy_n} track(s) will be copied from existing library")
                if hits_missing_source:
                    parts.append(f"{len(hits_missing_source)} will be re-downloaded")
                self.fn_logger.info(", ".join(parts) + ".")
            return resolved

        saved_action = getattr(self.settings.data, "duplicate_action", "ask")

        if saved_action != "ask":
            # Apply saved preference silently
            resolved = {}
            if saved_action == "copy":
                for track, _ in hits_with_source:
                    resolved[str(track.id)] = "copy"
                for track, _ in hits_missing_source:
                    self.fn_logger.warning(f"Copy source missing for '{name_builder_item(track)}'; will re-download.")
                    resolved[str(track.id)] = "redownload"
            elif saved_action == "redownload":
                for track, _ in hits_with_source + hits_missing_source:
                    resolved[str(track.id)] = "redownload"
            else:  # skip
                for track, _ in hits_with_source + hits_missing_source:
                    resolved[str(track.id)] = "skip"
            self.fn_logger.info(
                f"Duplicate action '{saved_action}': "
                f"{len(hits_with_source)} copyable, "
                f"{len(hits_missing_source)} source-missing tracks resolved."
            )
            return resolved

        return self._prompt_duplicate_action(hits_with_source, hits_missing_source)

    def _prompt_duplicate_action(
        self,
        hits_with_source: list[tuple],
        hits_missing_source: list[tuple],
    ) -> dict[str, str]:
        """Interactively prompt the user about duplicate ISRCs.

        Returns a dict mapping str(track.id) -> action ('copy', 'redownload', 'skip').
        """
        console = Console()

        if not sys.stdin.isatty():
            self.fn_logger.warning("Non-interactive terminal: defaulting to skip for all duplicates.")
            return {str(t.id): "skip" for t, _ in hits_with_source + hits_missing_source}

        # Build display table
        table = Table(
            title="Duplicate tracks detected (already in ISRC index)",
            style="cyan",
            show_lines=True,
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("Artist \u2013 Title", style="white")
        table.add_column("Source path", style="dim")
        table.add_column("Source", width=8)

        for i, (track, path_str) in enumerate(hits_with_source, start=1):
            table.add_row(
                str(i),
                name_builder_item(track),
                path_str,
                "[green]EXISTS[/green]",
            )
        for i, (track, path_str) in enumerate(hits_missing_source, start=len(hits_with_source) + 1):
            table.add_row(
                str(i),
                name_builder_item(track),
                path_str,
                "[red]MISSING[/red]",
            )

        console.print(table)

        total = len(hits_with_source) + len(hits_missing_source)
        console.print(f"\n[bold]{total} duplicate(s) found.[/bold]")
        if hits_missing_source:
            console.print(f"  [yellow]{len(hits_missing_source)} source file(s) are missing from disk.[/yellow]")

        # Prompt for blanket action
        action_map = {"C": "copy", "R": "redownload", "S": "skip"}
        while True:
            console.print("[bold]What would you like to do?[/bold]  [C]opy  [R]e-download  [S]kip all")
            raw = input("Choice [C/R/S]: ").strip().upper()
            if raw in action_map:
                selected_action = action_map[raw]
                break
            console.print("[red]Invalid choice. Enter C, R, or S.[/red]")

        resolved = {}

        if selected_action == "copy":
            for track, _ in hits_with_source:
                resolved[str(track.id)] = "copy"
            if hits_missing_source:
                console.print(
                    f"  [yellow]{len(hits_missing_source)} track(s) cannot be copied (source missing).[/yellow]"
                )
                sub = input("Re-download missing-source tracks instead? [Y/n]: ").strip().upper()
                missing_action = "redownload" if sub in ("", "Y") else "skip"
                for track, _ in hits_missing_source:
                    resolved[str(track.id)] = missing_action
        elif selected_action == "redownload":
            for track, _ in hits_with_source + hits_missing_source:
                resolved[str(track.id)] = "redownload"
        else:  # skip
            for track, _ in hits_with_source + hits_missing_source:
                resolved[str(track.id)] = "skip"

        # Offer to save preference
        save_raw = input("Save this as your default preference for future runs? [y/N]: ").strip().upper()
        if save_raw == "Y":
            self.settings.data.duplicate_action = selected_action
            if hasattr(self.settings, "save"):
                self.settings.save()
            console.print(f"  [green]Preference '{selected_action}' saved.[/green]")

        return resolved
