# Tidal Playlist Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `music-dl sync` command that fetches the user's Tidal playlists, diffs track ISRCs against the local index, and downloads only the missing tracks.

**Architecture:** New `sync` command in `cli.py` that uses OAuth for playlist enumeration and delegates to the existing `_download()` pipeline for track downloads (which uses Hi-Fi API by default). No new modules — ~200 lines of new code.

**Tech Stack:** tidalapi (OAuth + playlist API), Rich (table + prompt), Typer (CLI command), IsrcIndex (ISRC dedup)

**Spec:** `docs/superpowers/specs/2026-03-20-tidal-playlist-sync-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `TIDALDL-PY/tidal_dl/cli.py` | Modify (~lines 530+) | Add `sync` command + `_sync_diff_playlists()` helper |
| `TIDALDL-PY/tests/test_sync.py` | Create | Tests for sync diffing logic |

---

### Task 1: Playlist fetch + ISRC diff helper

The core logic: fetch all user playlists from Tidal, get their tracks, diff ISRCs against local index. This is a pure function that returns data — no UI, no downloads.

**Files:**
- Modify: `TIDALDL-PY/tidal_dl/cli.py` (add helper after `_download()` at ~line 348)
- Test: `TIDALDL-PY/tests/test_sync.py`

- [ ] **Step 1: Write the failing test for `_sync_diff_playlists()`**

Create `TIDALDL-PY/tests/test_sync.py`:

```python
"""Tests for the sync command's playlist diff logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from tidal_dl.cli import _sync_diff_playlists


@dataclass
class FakeTrack:
    isrc: str | None = None
    name: str = "Track"


@dataclass
class FakePlaylist:
    name: str = "My Playlist"
    id: str = "123"
    share_url: str = "https://tidal.com/playlist/123"
    _tracks: list[FakeTrack] = field(default_factory=list)

    def tracks(self, limit: int = 100, offset: int = 0) -> list[FakeTrack]:
        return self._tracks[offset : offset + limit]


def _make_isrc_index(known_isrcs: set[str]) -> MagicMock:
    idx = MagicMock()
    idx.contains.side_effect = lambda isrc: isrc in known_isrcs
    idx.load.return_value = None
    return idx


def test_diff_finds_missing_tracks():
    playlist = FakePlaylist(
        name="Chill",
        _tracks=[FakeTrack(isrc="US1234"), FakeTrack(isrc="US5678"), FakeTrack(isrc="US9999")],
    )
    idx = _make_isrc_index({"US1234"})

    result = _sync_diff_playlists([playlist], idx)

    assert len(result) == 1
    assert result[0]["name"] == "Chill"
    assert result[0]["total"] == 3
    assert result[0]["local"] == 1
    assert result[0]["missing"] == 2
    assert result[0]["share_url"] == "https://tidal.com/playlist/123"


def test_diff_all_local():
    playlist = FakePlaylist(
        name="Done",
        _tracks=[FakeTrack(isrc="US1111"), FakeTrack(isrc="US2222")],
    )
    idx = _make_isrc_index({"US1111", "US2222"})

    result = _sync_diff_playlists([playlist], idx)

    assert result[0]["missing"] == 0


def test_diff_tracks_without_isrc_count_as_missing():
    playlist = FakePlaylist(
        name="Odd",
        _tracks=[FakeTrack(isrc=None), FakeTrack(isrc="US1111")],
    )
    idx = _make_isrc_index({"US1111"})

    result = _sync_diff_playlists([playlist], idx)

    assert result[0]["missing"] == 1
    assert result[0]["total"] == 2


def test_diff_empty_playlist():
    playlist = FakePlaylist(name="Empty", _tracks=[])
    idx = _make_isrc_index(set())

    result = _sync_diff_playlists([playlist], idx)

    assert result[0]["total"] == 0
    assert result[0]["missing"] == 0


def test_diff_paginates_large_playlist():
    """Verify the pagination loop fetches tracks beyond the first page."""
    tracks = [FakeTrack(isrc=f"US{i:04d}") for i in range(150)]
    playlist = FakePlaylist(name="Big", _tracks=tracks)
    idx = _make_isrc_index(set())

    result = _sync_diff_playlists([playlist], idx)

    assert result[0]["total"] == 150
    assert result[0]["missing"] == 150
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd TIDALDL-PY && uv run pytest tests/test_sync.py -v`
Expected: ImportError — `_sync_diff_playlists` does not exist yet.

- [ ] **Step 3: Implement `_sync_diff_playlists()` in `cli.py`**

Add after `_download()` (around line 348 in `cli.py`):

```python
def _sync_diff_playlists(
    playlists: list[Any],
    isrc_index: "IsrcIndex",
) -> list[dict[str, Any]]:
    """Compare Tidal playlists against the local ISRC index.

    Args:
        playlists: List of tidalapi Playlist objects (or duck-typed equivalents).
        isrc_index: Loaded IsrcIndex instance.

    Returns:
        List of dicts with keys: name, total, local, missing, share_url.
    """
    results: list[dict[str, Any]] = []

    for pl in playlists:
        tracks: list[Any] = []
        offset = 0
        while True:
            page = pl.tracks(limit=100, offset=offset)
            if not page:
                break
            tracks.extend(page)
            if len(page) < 100:
                break
            offset += 100

        total = len(tracks)
        local = 0
        for track in tracks:
            isrc = getattr(track, "isrc", None)
            if isrc and isrc_index.contains(isrc):
                local += 1

        results.append({
            "name": pl.name,
            "total": total,
            "local": local,
            "missing": total - local,
            "share_url": pl.share_url,
        })

    return results
```

No top-level import needed for `IsrcIndex` — follow the codebase convention of local imports (see `_run_scan` at line 914). The type hint uses string-quoted `"IsrcIndex"` so no import is required at module level.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd TIDALDL-PY && uv run pytest tests/test_sync.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add TIDALDL-PY/tidal_dl/cli.py TIDALDL-PY/tests/test_sync.py
git commit -m "feat(sync): add playlist ISRC diff helper with tests"
```

---

### Task 2: Rich summary table renderer

A helper that takes the diff results and prints a Rich table. Separated from Task 1 so the diff logic stays testable without UI concerns.

**Files:**
- Modify: `TIDALDL-PY/tidal_dl/cli.py`
- Test: `TIDALDL-PY/tests/test_sync.py`

- [ ] **Step 1: Write the failing test for `_sync_print_summary()`**

Append to `TIDALDL-PY/tests/test_sync.py`:

```python
from io import StringIO

from rich.console import Console

from tidal_dl.cli import _sync_print_summary


def test_summary_table_renders():
    diff = [
        {"name": "Chill", "total": 42, "local": 38, "missing": 4, "share_url": ""},
        {"name": "Done", "total": 10, "local": 10, "missing": 0, "share_url": ""},
    ]
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=80)

    _sync_print_summary(diff, console)

    output = buf.getvalue()
    assert "Chill" in output
    assert "42" in output
    assert "4" in output
    assert "Done" in output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd TIDALDL-PY && uv run pytest tests/test_sync.py::test_summary_table_renders -v`
Expected: ImportError — `_sync_print_summary` does not exist yet.

- [ ] **Step 3: Implement `_sync_print_summary()` in `cli.py`**

Add after `_sync_diff_playlists()`:

```python
def _sync_print_summary(diff: list[dict[str, Any]], console: Console) -> None:
    """Print a Rich table summarising the sync diff.

    Args:
        diff: Output of _sync_diff_playlists().
        console: Rich Console to print to.
    """
    table = Table(title="Playlist Sync Summary", show_lines=False)
    table.add_column("Playlist", style="cyan", no_wrap=True)
    table.add_column("Total", justify="right")
    table.add_column("Local", justify="right")
    table.add_column("Missing", justify="right")

    for row in diff:
        missing_style = "red bold" if row["missing"] > 0 else "green"
        table.add_row(
            row["name"],
            str(row["total"]),
            str(row["local"]),
            f"[{missing_style}]{row['missing']}[/{missing_style}]",
        )

    console.print(table)
```

Note: `Table` and `Console` are already imported in `cli.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd TIDALDL-PY && uv run pytest tests/test_sync.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add TIDALDL-PY/tidal_dl/cli.py TIDALDL-PY/tests/test_sync.py
git commit -m "feat(sync): add Rich summary table renderer"
```

---

### Task 3: Per-playlist prompt logic

Interactive prompt that iterates over playlists with missing tracks and asks the user which ones to download. Returns a list of playlist URLs to pass to `_download()`.

**Files:**
- Modify: `TIDALDL-PY/tidal_dl/cli.py`
- Test: `TIDALDL-PY/tests/test_sync.py`

- [ ] **Step 1: Write the failing test for `_sync_prompt_playlists()`**

Append to `TIDALDL-PY/tests/test_sync.py`:

```python
from unittest.mock import patch

from tidal_dl.cli import _sync_prompt_playlists


def test_prompt_yes_selects_playlist():
    diff = [{"name": "Chill", "total": 10, "local": 6, "missing": 4, "share_url": "https://tidal.com/playlist/123"}]
    with patch("builtins.input", return_value="y"):
        urls = _sync_prompt_playlists(diff)
    assert urls == ["https://tidal.com/playlist/123"]


def test_prompt_no_skips_playlist():
    diff = [{"name": "Chill", "total": 10, "local": 6, "missing": 4, "share_url": "https://tidal.com/playlist/123"}]
    with patch("builtins.input", return_value="n"):
        urls = _sync_prompt_playlists(diff)
    assert urls == []


def test_prompt_all_selects_remaining():
    diff = [
        {"name": "A", "total": 5, "local": 0, "missing": 5, "share_url": "https://tidal.com/playlist/1"},
        {"name": "B", "total": 3, "local": 0, "missing": 3, "share_url": "https://tidal.com/playlist/2"},
    ]
    with patch("builtins.input", return_value="a"):
        urls = _sync_prompt_playlists(diff)
    assert urls == ["https://tidal.com/playlist/1", "https://tidal.com/playlist/2"]


def test_prompt_quit_stops_early():
    diff = [
        {"name": "A", "total": 5, "local": 0, "missing": 5, "share_url": "https://tidal.com/playlist/1"},
        {"name": "B", "total": 3, "local": 0, "missing": 3, "share_url": "https://tidal.com/playlist/2"},
    ]
    with patch("builtins.input", return_value="q"):
        urls = _sync_prompt_playlists(diff)
    assert urls == []


def test_prompt_skips_zero_missing():
    diff = [
        {"name": "Done", "total": 10, "local": 10, "missing": 0, "share_url": "https://tidal.com/playlist/1"},
        {"name": "Has Missing", "total": 5, "local": 2, "missing": 3, "share_url": "https://tidal.com/playlist/2"},
    ]
    with patch("builtins.input", return_value="y"):
        urls = _sync_prompt_playlists(diff)
    # Only the one with missing tracks should be prompted and selected
    assert urls == ["https://tidal.com/playlist/2"]


def test_prompt_empty_input_defaults_to_yes():
    diff = [{"name": "Chill", "total": 10, "local": 6, "missing": 4, "share_url": "https://tidal.com/playlist/123"}]
    with patch("builtins.input", return_value=""):
        urls = _sync_prompt_playlists(diff)
    assert urls == ["https://tidal.com/playlist/123"]


def test_prompt_all_on_second_playlist():
    diff = [
        {"name": "A", "total": 5, "local": 0, "missing": 5, "share_url": "https://tidal.com/playlist/1"},
        {"name": "B", "total": 3, "local": 0, "missing": 3, "share_url": "https://tidal.com/playlist/2"},
        {"name": "C", "total": 4, "local": 1, "missing": 3, "share_url": "https://tidal.com/playlist/3"},
    ]
    with patch("builtins.input", side_effect=["n", "a"]):
        urls = _sync_prompt_playlists(diff)
    # Skipped A, then "all" on B includes B + C
    assert urls == ["https://tidal.com/playlist/2", "https://tidal.com/playlist/3"]


def test_prompt_yes_flag_selects_all():
    diff = [
        {"name": "A", "total": 5, "local": 0, "missing": 5, "share_url": "https://tidal.com/playlist/1"},
        {"name": "B", "total": 3, "local": 1, "missing": 2, "share_url": "https://tidal.com/playlist/2"},
        {"name": "Done", "total": 10, "local": 10, "missing": 0, "share_url": "https://tidal.com/playlist/3"},
    ]
    urls = _sync_prompt_playlists(diff, auto_yes=True)
    # Only playlists with missing tracks
    assert urls == ["https://tidal.com/playlist/1", "https://tidal.com/playlist/2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd TIDALDL-PY && uv run pytest tests/test_sync.py -k "prompt" -v`
Expected: ImportError — `_sync_prompt_playlists` does not exist yet.

- [ ] **Step 3: Implement `_sync_prompt_playlists()` in `cli.py`**

Add after `_sync_print_summary()`:

```python
def _sync_prompt_playlists(
    diff: list[dict[str, Any]],
    auto_yes: bool = False,
) -> list[str]:
    """Prompt the user to choose which playlists to sync.

    Args:
        diff: Output of _sync_diff_playlists().
        auto_yes: If True, select all playlists with missing tracks without prompting.

    Returns:
        List of playlist share_urls selected for download.
    """
    selected: list[str] = []
    pending = [row for row in diff if row["missing"] > 0]

    if not pending:
        return selected

    if auto_yes:
        return [row["share_url"] for row in pending]

    for row in pending:
        answer = input(
            f"  Sync '{row['name']}' ({row['missing']} missing)? [Y]es / [n]o / [a]ll / [q]uit: "
        ).strip().lower()

        if answer in ("q", "quit"):
            break
        elif answer in ("a", "all"):
            selected.append(row["share_url"])
            # Add all remaining without prompting
            remaining = pending[pending.index(row) + 1 :]
            selected.extend(r["share_url"] for r in remaining)
            break
        elif answer in ("n", "no"):
            continue
        else:
            # Default is yes (empty input or "y")
            selected.append(row["share_url"])

    return selected
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd TIDALDL-PY && uv run pytest tests/test_sync.py -v`
Expected: All 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add TIDALDL-PY/tidal_dl/cli.py TIDALDL-PY/tests/test_sync.py
git commit -m "feat(sync): add per-playlist interactive prompt"
```

---

### Task 4: Wire up the `sync` command

Connect all helpers into the Typer command: login, fetch playlists with pagination, diff, display, prompt, download.

**Files:**
- Modify: `TIDALDL-PY/tidal_dl/cli.py` (add `sync` command near `dl` command at ~line 533)

- [ ] **Step 1: Implement the `sync` command**

Add before the `dl` command (around line 533 in `cli.py`):

```python
@app.command(name="sync")
def sync(
    ctx: typer.Context,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip per-playlist prompt and download all missing tracks.",
        ),
    ] = False,
) -> None:
    """Sync local library with your Tidal playlists.

    Fetches all playlists in your Tidal collection, compares track ISRCs
    against the local index, and downloads missing tracks.
    """
    # Login required for playlist enumeration
    if not ctx.invoke(login, ctx):
        raise typer.Exit(code=1)

    tidal = _ctx_tidal(ctx)
    console = Console()

    # Fetch all user playlists (paginated, 50 per page)
    console.print("[cyan]Fetching your playlists...[/cyan]")
    user = cast(Any, tidal.session.user)
    all_playlists: list[Any] = []
    offset = 0
    while True:
        page = user.favorites.playlists(limit=50, offset=offset)
        if not page:
            break
        all_playlists.extend(page)
        if len(page) < 50:
            break
        offset += 50

    if not all_playlists:
        console.print("[yellow]No playlists found in your collection.[/yellow]")
        raise typer.Exit()

    console.print(f"[cyan]Found {len(all_playlists)} playlists. Checking tracks...[/cyan]")

    # Load ISRC index
    from tidal_dl.helper.isrc_index import IsrcIndex
    _index_path = pathlib.Path(path_config_base()) / "isrc_index.json"
    isrc_index = IsrcIndex(_index_path)
    isrc_index.load()

    # Diff
    diff = _sync_diff_playlists(all_playlists, isrc_index)

    # Summary
    _sync_print_summary(diff, console)

    total_missing = sum(row["missing"] for row in diff)
    if total_missing == 0:
        console.print("\n[green]All playlists up to date.[/green]")
        raise typer.Exit()

    console.print(f"\n[cyan]{total_missing} total missing tracks across all playlists.[/cyan]\n")

    # Prompt
    urls = _sync_prompt_playlists(diff, auto_yes=yes)

    if not urls:
        console.print("[yellow]No playlists selected. Nothing to do.[/yellow]")
        raise typer.Exit()

    # Download — reuse existing pipeline (Hi-Fi API default, full dedup + M3U rebuild)
    result = _download(ctx, urls, try_login=False)
    if not result:
        raise typer.Exit(code=1)
```

**Import fix required:** `path_config_base` is used at line 919 in `cli.py` but imported inline there. Add it to the existing top-level import at line 35. Change:

```python
from tidal_dl.helper.path import get_format_template, path_file_settings
```

to:

```python
from tidal_dl.helper.path import get_format_template, path_config_base, path_file_settings
```

Then update the `sync` command code above to use `_pathlib` (already imported at line 2) instead of `pathlib`:

```python
_index_path = _pathlib.Path(path_config_base()) / "isrc_index.json"
```

- [ ] **Step 2: Verify the command registers**

Run: `cd TIDALDL-PY && uv run python -m tidal_dl.cli sync --help`
Expected: Shows help text for sync command with `--yes` / `-y` option.

- [ ] **Step 3: Commit**

```bash
git add TIDALDL-PY/tidal_dl/cli.py
git commit -m "feat(sync): wire up sync command with login, diff, prompt, download"
```

---

### Task 5: Run full test suite + manual smoke test

Verify nothing is broken and the sync command works end-to-end.

**Files:**
- No changes — verification only.

- [ ] **Step 1: Run full test suite**

Run: `cd TIDALDL-PY && uv run pytest tests/ -v`
Expected: All tests pass (existing + new sync tests).

- [ ] **Step 2: Verify CLI help includes sync**

Run: `cd TIDALDL-PY && uv run python -m tidal_dl.cli --help`
Expected: `sync` appears in the commands list.

- [ ] **Step 3: Commit (if any lint/format fixes needed)**

```bash
git add TIDALDL-PY/tidal_dl/cli.py TIDALDL-PY/tests/test_sync.py && git commit -m "chore: lint fixes for sync command"
```

Only commit if there were changes. Skip if clean.

---

### Task 6: Update README with sync command

Document the new `sync` command in the project README.

**Files:**
- Modify: `TIDALDL-PY/README.md` (or project root README — whichever documents CLI usage)

- [ ] **Step 1: Find and read the README**

Locate the README that documents CLI commands. Add a section for `sync` in the existing commands list.

- [ ] **Step 2: Add sync documentation**

Add to the CLI commands section:

```markdown
### Sync

Compare your Tidal playlists against your local library and download missing tracks.

```bash
music-dl sync           # Interactive — prompts per playlist
music-dl sync --yes     # Download all missing tracks without prompting
```

Requires OAuth login (for playlist enumeration). Downloads use Hi-Fi API by default.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add sync command to README"
```
