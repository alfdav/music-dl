# music-dl changelog

## Current naming note

The project is now called `music-dl`.

Migration details:

- primary CLI name: `music-dl`
- compatibility CLI alias: `tidal-dl`
- current config directory: `~/.config/music-dl/`
- legacy config directory: `~/.config/tidal-dl/`
- legacy config is migrated automatically on first run

Recommended install command:

```shell
uv tool install --from git+https://github.com/alfdav/music-dl.git#subdirectory=tidaldl-py music-dl
```

---

## v3.1.0 (2026)

### Behavior changes

- `duplicate_action` now defaults to `copy` for configs that do not already define the setting, so duplicate ISRC hits prefer copying from an existing local source instead of prompting.

### Playlist M3U generation

- Playlist downloads now always generate a UTF-8 `.m3u8` file with relative paths
- Playlist metadata preservation was tightened so album name, album artist, and artwork survive playlist downloads
- Albums and mixes still respect `playlist_create`
- Existing configs that still use the untouched legacy `- Playlists/...` default are migrated automatically to `Playlists/...` for cleaner library ingestion

### Download correctness fixes

- Fixed live playlist downloads that were saved as `.flac` even when the downloaded container was actually MP4/M4A
- Fixed re-download path handling so canonical filenames are reused instead of drifting into `_01` duplicates when the resolved stream extension changes

### Library scanning

- Added `music-dl scan`
- Added persistent `scan_paths` management through `scan add`, `scan remove`, and `scan show`
- Added `--dry-run`, `--all`, and `--verbose`
- Added ISRC extraction for FLAC, MP3, MP4/M4A, and OGG through `mutagen`
- Added Rich progress and summary output for scan runs
- Added existence checks in `scan show`

### Documentation

- README updated for the current command surface
- Docker documentation added and aligned with the renamed app
- changelog refreshed for the `music-dl` rename

---

## v3.0.0 (2025)

Full CLI rewrite based on the current Typer engine, ported from [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng).

### Core

- Replaced the old CLI with a Typer-based command tree
- Added bare URL shorthand so `music-dl <URL>` works without an explicit `dl` subcommand
- Standardized the package entrypoint around the `music-dl` CLI
- Moved packaging to `pyproject.toml`
- Dropped legacy Python support and now require Python 3.12+

### Authentication

- Added browser-based OAuth login
- Added clickable fallback links when auto-launch is unavailable
- Added token persistence with automatic refresh

### Downloads

- Added `dl --list` for URL files
- Added `dl --output` for a one-off destination override
- Added `dl_fav tracks|albums|artists|videos`
- Added `dl_fav ... --since` for date-filtered favourites
- Added richer summary output after collection downloads
- Added configurable concurrency and randomized delay controls

### Duplicate handling

- Added persistent ISRC duplicate tracking across sessions
- Added duplicate actions such as `copy`, `ask`, `redownload`, and `skip`
- Added index pruning and safer duplicate-state handling

### Paths and templates

- Replaced legacy placeholder formatting with `{token}` templates
- Added multi-disc path helpers such as `{track_volume_num_optional_CD}`
- Added more metadata-aware path tokens for IDs, dates, durations, and explicit flags

### Metadata and media handling

- Expanded metadata writing across FLAC, MP3, and MP4
- Improved lyrics handling
- Improved album artist, disc number, replay gain, and URL tagging
- Added FFmpeg auto-discovery for FLAC extraction and MP4 remuxing

### Removed legacy surface

- Removed the GUI path
- Removed older setup scripts and legacy support modules that no longer matched the current architecture

---

## Legacy history

For older project history before the current rewrite, see the upstream repository:

- [yaronzz/Tidal-Media-Downloader](https://github.com/yaronzz/Tidal-Media-Downloader)
