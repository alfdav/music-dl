"""playlist_import.py

Cross-platform playlist import for tidal-dl.

Accepts a file containing tracks exported from any platform (Spotify,
Apple Music, etc.) and matches each entry to a TIDAL track using:

1. **ISRC** (exact) — if an ``isrc`` column / field is present.
2. **Title + Artist fuzzy search** — fallback via ``session.search()``.

Supported input formats
-----------------------
CSV / TSV
    A header row must contain at least ``title`` and ``artist`` columns.
    An optional ``isrc`` column enables exact matching.  Column order is
    flexible; the dialect (comma vs. tab) is auto-detected.

Plain text
    One entry per line in the format ``Artist - Title``.  The split is
    performed on the *first* occurrence of `` - ``, so titles that
    contain the separator are preserved correctly.

    Lines that are blank or start with ``#`` are skipped.

Example CSV::

    title,artist,isrc
    Bohemian Rhapsody,Queen,GBUM71029604
    Hotel California,Eagles,

Example plain text::

    Queen - Bohemian Rhapsody
    Eagles - Hotel California
"""

from __future__ import annotations

import csv
import pathlib
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from tidalapi import Session
    from tidalapi.media import Track

    from tidal_dl.download import Download

_console = Console()


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class TrackEntry:
    """A single track entry parsed from an import file.

    Attributes:
        title (str): Track title.
        artist (str): Artist name (primary).
        isrc (str): ISRC identifier, empty string if not provided.
        raw (str): Original line / row as read from the file (for diagnostics).
    """

    __slots__ = ("title", "artist", "isrc", "raw")

    def __init__(self, title: str, artist: str, isrc: str = "", raw: str = "") -> None:
        self.title = title.strip()
        self.artist = artist.strip()
        self.isrc = isrc.strip().upper()
        self.raw = raw

    def __repr__(self) -> str:
        return f"TrackEntry(artist={self.artist!r}, title={self.title!r}, isrc={self.isrc!r})"


# ---------------------------------------------------------------------------
# PlaylistImporter
# ---------------------------------------------------------------------------

class PlaylistImporter:
    """Parse a foreign-platform track list and match entries to TIDAL tracks.

    Args:
        session (Session): An authenticated ``tidalapi.Session``.
    """

    def __init__(self, session: "Session") -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_file(self, path: str | pathlib.Path) -> list[TrackEntry]:
        """Parse *path* into a list of :class:`TrackEntry` objects.

        Auto-detects whether the file is CSV/TSV (has a recognisable header)
        or plain text (``Artist - Title`` per line).

        Args:
            path (str | pathlib.Path): Path to the import file.

        Returns:
            list[TrackEntry]: Parsed track entries.

        Raises:
            ValueError: If the file cannot be parsed (empty, unreadable header, etc.).
        """
        path = pathlib.Path(path)
        text = path.read_text(encoding="utf-8", errors="replace")

        # Detect format: if the first non-blank/non-comment line contains a
        # comma or tab AND looks like CSV headers, treat as CSV/TSV.
        first_line = next(
            (ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")),
            "",
        )

        lower = first_line.lower()
        has_delimiter = "," in first_line or "\t" in first_line
        has_title_col = "title" in lower or "track" in lower or "song" in lower
        has_artist_col = "artist" in lower or "performer" in lower
        if has_delimiter and (has_title_col or has_artist_col):
            return self._parse_csv(text)

        return self._parse_plain(text)

    def _parse_csv(self, text: str) -> list[TrackEntry]:
        """Parse CSV/TSV content.

        Args:
            text (str): Raw file content.

        Returns:
            list[TrackEntry]: Parsed entries.

        Raises:
            ValueError: If required columns are missing.
        """
        # Sniff dialect from first 2 KB
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        except csv.Error:
            dialect = csv.excel  # fall back to standard CSV

        reader = csv.DictReader(text.splitlines(), dialect=dialect)

        # Normalise header names to lowercase and strip whitespace
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row.")

        fieldnames_lower = [f.lower().strip() for f in reader.fieldnames]
        reader.fieldnames = fieldnames_lower

        # Identify required columns (support common synonyms)
        title_col = _find_col(fieldnames_lower, ("title", "track", "song", "track name", "song name"))
        artist_col = _find_col(fieldnames_lower, ("artist", "artist name", "artists", "performer"))
        isrc_col = _find_col(fieldnames_lower, ("isrc",))

        if title_col is None or artist_col is None:
            raise ValueError(
                f"CSV must have 'title' and 'artist' columns. Found: {fieldnames_lower}"
            )

        entries: list[TrackEntry] = []
        for row in reader:
            title = row.get(title_col, "").strip()
            artist = row.get(artist_col, "").strip()
            isrc = row.get(isrc_col, "").strip() if isrc_col else ""

            if not title or not artist:
                continue

            entries.append(TrackEntry(title=title, artist=artist, isrc=isrc, raw=str(row)))

        return entries

    def _parse_plain(self, text: str) -> list[TrackEntry]:
        """Parse plain-text ``Artist - Title`` lines.

        Args:
            text (str): Raw file content.

        Returns:
            list[TrackEntry]: Parsed entries.
        """
        entries: list[TrackEntry] = []

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if " - " not in line:
                # Can't split cleanly — skip with a warning
                _console.print(f"[yellow]Skipping unparseable line:[/yellow] {line!r}")
                continue

            # Split on the FIRST occurrence only
            artist, title = line.split(" - ", 1)
            entries.append(TrackEntry(title=title.strip(), artist=artist.strip(), raw=line))

        return entries

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match_track(self, entry: TrackEntry) -> "Track | None":
        """Find the best TIDAL :class:`~tidalapi.media.Track` for *entry*.

        Strategy:
          1. If ``entry.isrc`` is non-empty, search TIDAL by ISRC and verify.
          2. Otherwise (or if ISRC search yields nothing), fall back to a
             ``"{artist} {title}"`` free-text search and return the top hit.

        Args:
            entry (TrackEntry): Track entry to match.

        Returns:
            Track | None: Matched TIDAL track, or ``None`` if no match found.
        """
        import tidalapi  # local import to avoid circular dependency at module level

        # --- ISRC-first ---
        if entry.isrc:
            try:
                results = self._session.search(
                    entry.isrc,
                    models=[tidalapi.Track],
                    limit=5,
                )
                for track in results.get("tracks", []):
                    if getattr(track, "isrc", "").upper() == entry.isrc:
                        return track
            except Exception:
                pass  # fall through to text search

        # --- Text search fallback ---
        query = f"{entry.artist} {entry.title}"
        try:
            results = self._session.search(
                query,
                models=[tidalapi.Track],
                limit=5,
            )
            tracks = results.get("tracks", [])
            if tracks:
                return tracks[0]
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def import_and_download(
        self,
        path: str | pathlib.Path,
        dl: "Download",
        file_template: str,
    ) -> None:
        """Parse *path*, match each entry to TIDAL, and download matched tracks.

        A Rich summary panel is printed at the end showing matched and
        unmatched entries.

        Args:
            path (str | pathlib.Path): Import file path.
            dl (Download): Configured :class:`~tidal_dl.download.Download` instance.
            file_template (str): File naming template (e.g. ``settings.data.format_track``).
        """
        _console.print(f"[cyan]Parsing import file:[/cyan] {path}")

        try:
            entries = self.parse_file(path)
        except (ValueError, OSError) as exc:
            _console.print(f"[red]Failed to parse import file:[/red] {exc}")
            return

        _console.print(f"[cyan]Parsed {len(entries)} entries. Matching to TIDAL...[/cyan]")

        matched: list[tuple[TrackEntry, "Track"]] = []
        unmatched: list[TrackEntry] = []

        for entry in entries:
            track = self.match_track(entry)
            if track:
                matched.append((entry, track))
            else:
                unmatched.append(entry)

        _console.print(
            f"[green]{len(matched)} matched[/green], "
            f"[yellow]{len(unmatched)} unmatched[/yellow] out of {len(entries)} entries."
        )

        # Download matched tracks
        for _entry, track in matched:
            dl.item(
                media=track,
                file_template=file_template,
            )

        # Report unmatched entries
        if unmatched:
            table = Table(title="Unmatched Tracks", show_header=True, header_style="bold red")
            table.add_column("Artist", style="cyan")
            table.add_column("Title", style="magenta")
            table.add_column("ISRC", style="yellow")

            for entry in unmatched:
                table.add_row(entry.artist, entry.title, entry.isrc or "-")

            import sys
            err_console = Console(stderr=True)
            err_console.print(table)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_col(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    """Return the first fieldname that matches any candidate (case-insensitive).

    Args:
        fieldnames (list[str]): Available column names (already lowercased).
        candidates (tuple[str, ...]): Acceptable column name variants.

    Returns:
        str | None: Matched fieldname, or ``None``.
    """
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
    return None
