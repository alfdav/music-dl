<div align="center">
  <h1>Tidal-Media-Downloader</h1>
  <p>A CLI-only fork of <a href="https://github.com/yaronzz/Tidal-Media-Downloader">yaronzz/Tidal-Media-Downloader</a>, rebuilt with a next-generation engine.<br>Download tracks, albums, playlists, mixes, and videos from Tidal. No GUI. Python 3.12+.</p>
  <a href="https://github.com/alfdav/Tidal-Media-Downloader/blob/master/LICENSE">
    <img src="https://img.shields.io/github/license/alfdav/Tidal-Media-Downloader.svg?style=flat-square" alt="License">
  </a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square" alt="Python 3.12+">
</div>

---

## I am learning how to code with this app, expect bugs

## Requirements

- Python 3.12 or 3.13
- FFmpeg (optional — auto-discovered via PATH; required for video conversion and FLAC extraction)
- A valid Tidal subscription (HiFi or HiFi Plus for lossless)

---

## Installation

### From GitHub (recommended)

```shell
pip install git+https://github.com/alfdav/Tidal-Media-Downloader.git#subdirectory=TIDALDL-PY
```

### Development install

```shell
git clone https://github.com/alfdav/Tidal-Media-Downloader.git
pip install -e Tidal-Media-Downloader/TIDALDL-PY
```

---

## Authentication

Use `tidal-dl login` to authenticate via OAuth. A browser window opens automatically. If the browser cannot be opened, a clickable link is printed in the terminal.

```shell
tidal-dl login    # OAuth login — auto-opens browser
tidal-dl logout   # clear saved credentials
```

Credentials are cached at `~/.config/tidal-dl/` and refresh automatically.

---

## Usage

### Quick download

Paste any Tidal URL directly — no subcommand needed:

```shell
tidal-dl https://tidal.com/browse/album/123456789
```

### All commands

```
tidal-dl <URL>                                      Download a Tidal URL (bare shorthand)
tidal-dl dl <URL>... [OPTIONS]                      Explicit download subcommand; accepts multiple URLs
tidal-dl dl -l/--list FILE                          Read URLs from a text file (one per line)
tidal-dl dl -o/--output DIR                         Override output directory for this run only
tidal-dl dl -d/--debug                              Enable verbose debug logging
tidal-dl dl_fav tracks                              Download favourite tracks
tidal-dl dl_fav albums                              Download favourite albums
tidal-dl dl_fav artists                             Download favourite artists' albums
tidal-dl dl_fav videos                              Download favourite videos
tidal-dl dl_fav tracks --since DATE                 Only items added after DATE (YYYY-MM-DD)
tidal-dl import FILE                                Import playlist from CSV/TSV or plain text and download
tidal-dl import FILE -o DIR                         Override output directory for import run
tidal-dl scan                                       Scan configured music directories and seed ISRC index
tidal-dl scan add PATH                              Add a directory to the scan path list
tidal-dl scan remove PATH                           Remove a directory from the scan path list
tidal-dl scan show                                  List configured scan directories (with existence check)
tidal-dl scan --dry-run                             Discover ISRCs without writing to the index
tidal-dl scan --all                                 Scan all configured paths without prompting
tidal-dl source                                     Show current download source configuration
tidal-dl source show                                Show current download source configuration
tidal-dl source set SOURCE                          Set preferred source: hifi_api or oauth
tidal-dl source instances                           List and probe all configured Hi-Fi API instances
tidal-dl source add URL                             Add a Hi-Fi API instance URL
tidal-dl source remove URL                          Remove a Hi-Fi API instance URL
tidal-dl login                                      OAuth login (auto-opens browser)
tidal-dl logout                                     Clear saved credentials
tidal-dl cfg                                        Show all settings
tidal-dl cfg KEY                                    Show one setting value
tidal-dl cfg KEY VALUE                              Change one setting
tidal-dl cfg -e/--editor                            Open config file in $EDITOR
tidal-dl cfg --reset                                Reset to defaults (backs up existing to .json.bak)
tidal-dl -v/--version                               Show version
```

---

## Download Sources

tidal-dl supports two audio download backends:

**Hi-Fi API** (`hifi_api`, default) — Uses public community proxy instances for both metadata resolution and audio streaming. Stateless and fast; does not put load on your personal Tidal credentials. Instances are auto-discovered from live uptime trackers and rotated automatically when one fails.

**OAuth** (`oauth`) — Uses your personal Tidal OAuth session directly for metadata and streaming. When Hi-Fi API is the active source, OAuth serves only as a fallback — it is not required for normal operation.

When `download_source_fallback = true` (default) the app automatically falls back to OAuth if a Hi-Fi API request fails.

```shell
tidal-dl source set hifi_api        # switch to Hi-Fi API (default)
tidal-dl source set oauth           # switch to personal session
tidal-dl source instances           # probe all known instances
tidal-dl source add https://my.instance.example
tidal-dl source remove https://my.instance.example
```

---

## Library Scanning

The ISRC duplicate index (`~/.config/tidal-dl/isrc_index.json`) normally only knows about tracks downloaded by tidal-dl itself. The `scan` command walks your existing music library, reads ISRCs from audio file metadata, and seeds the index — so tidal-dl will skip re-downloading tracks you already own on disk.

Run the scan once after initial setup. Every subsequent download by tidal-dl keeps the index up to date automatically.

Supported formats: FLAC, MP3, M4A, MP4, OGG.

### Setup (single library directory)

```shell
tidal-dl scan add M:\Music      # save the path (auto-defaults when only one is configured)
tidal-dl scan                   # runs immediately, no prompt needed
```

### Multiple directories

```shell
tidal-dl scan add M:\Music
tidal-dl scan add D:\Archive
tidal-dl scan                   # shows a numbered selection prompt
tidal-dl scan --all             # scan all at once without prompting
```

### Other options

```shell
tidal-dl scan --dry-run         # discover ISRCs without writing to the index
tidal-dl scan show              # list configured directories with existence check
tidal-dl scan remove D:\Archive # remove a directory from the list
```

---

## Playlist Import

Import a track list exported from any platform (Spotify, Apple Music, etc.) and download all matched tracks from Tidal.

**Accepted formats:**

CSV / TSV — a header row with at least `title` and `artist` columns; optional `isrc` column for exact matching:

```
title,artist,isrc
Bohemian Rhapsody,Queen,GBUM71029604
Hotel California,Eagles,
```

Plain text — one `Artist - Title` entry per line (lines starting with `#` are ignored):

```
Queen - Bohemian Rhapsody
Eagles - Hotel California
```

Each entry is matched via ISRC (exact) first, then falls back to title + artist search.

```shell
tidal-dl import my_playlist.csv
tidal-dl import my_playlist.txt -o /tmp/import
```

---

## Configuration

Config is stored at `~/.config/tidal-dl/settings.json`. Use `tidal-dl cfg` to view or change any setting.

| Setting | Default | Description |
| --- | --- | --- |
| `download_base_path` | `~/download` | Root download directory |
| `quality_audio` | `hi_res_lossless` | `low_96k` / `low_320k` / `high_lossless` / `hi_res_lossless`. Tidal auto-degrades based on subscription. |
| `quality_video` | `1080p` | `360p` / `480p` / `720p` / `1080p` |
| `skip_existing` | `true` | Skip if the output file already exists on disk |
| `skip_duplicate_isrc` | `true` | Skip tracks whose ISRC was already downloaded (cross-session persistent index) |
| `duplicate_action` | `ask` | Action on duplicate ISRC: `ask` / `copy` / `redownload` / `skip` |
| `download_source` | `hifi_api` | Preferred audio source: `hifi_api` or `oauth` |
| `download_source_fallback` | `true` | Automatically fall back to next source when preferred is unavailable |
| `hifi_api_instances` | `""` | Comma-separated Hi-Fi API instance URLs. Empty = auto-discover |
| `scan_paths` | `""` | Comma-separated directories for library scanning. Managed via `tidal-dl scan add/remove` |
| `download_dolby_atmos` | `false` | Download Dolby Atmos variant when available |
| `extract_flac` | `true` | Extract FLAC from M4A container when possible |
| `video_convert_mp4` | `true` | Remux video to MP4 via FFmpeg |
| `video_download` | `true` | Allow download of videos |
| `lyrics_embed` | `false` | Embed synced lyrics in audio tags |
| `lyrics_file` | `false` | Save lyrics as a separate `.lrc` file |
| `playlist_create` | `false` | Generate M3U playlist files for albums and mixes (playlists always generate an M3U automatically) |
| `symlink_to_track` | `false` | Create a symlink to the track inside the playlist folder |
| `downloads_concurrent_max` | `3` | Maximum parallel downloads |
| `downloads_simultaneous_per_track_max` | `20` | Maximum simultaneous chunk downloads per track |
| `download_delay` | `true` | Add a small random delay between downloads |
| `download_delay_sec_min` | `3.0` | Lower bound for random download delay (seconds) |
| `download_delay_sec_max` | `5.0` | Upper bound for random download delay (seconds) |
| `path_binary_ffmpeg` | `""` | Path to FFmpeg binary; empty = auto-discover via PATH |
| `metadata_cover_dimension` | `1280` | Square dimensions of embedded cover art: `80` / `160` / `320` / `640` / `1280` / `origin` |
| `metadata_cover_embed` | `true` | Embed album cover into downloaded file |
| `cover_album_file` | `true` | Save `cover.jpg` in the album folder |
| `mark_explicit` | `false` | Mark explicit tracks with 🅴 in title metadata |
| `metadata_replay_gain` | `false` | Write replay gain values to metadata |
| `metadata_write_url` | `true` | Write Tidal share URL to metadata |
| `metadata_delimiter_artist` | `", "` | Delimiter for multiple artists in metadata tags |
| `metadata_delimiter_album_artist` | `", "` | Delimiter for multiple album artists in metadata tags |
| `filename_delimiter_artist` | `", "` | Delimiter for multiple artists in filenames |
| `filename_delimiter_album_artist` | `", "` | Delimiter for multiple album artists in filenames |
| `metadata_target_upc` | `UPC` | Tag name for UPC/barcode: `UPC` / `BARCODE` / `EAN` |
| `use_primary_album_artist` | `false` | Use only the primary album artist for folder paths |
| `album_track_num_pad_min` | `1` | Minimum zero-pad width for track numbers (1 = no padding) |
| `api_rate_limit_batch_size` | `20` | Albums per batch before applying rate-limit delay |
| `api_rate_limit_delay_sec` | `3.0` | Delay in seconds between batches to avoid API rate limiting |
| `api_cache_enabled` | `true` | Cache Tidal API responses in-memory during a session |
| `api_cache_ttl_sec` | `300` | TTL in seconds for cached API responses (default: 5 minutes) |
| `initial_key_format` | `alphanumeric` | Format for Initial Key metadata tag: `alphanumeric` or `classic` |
| `format_album` | see below | Path template for album tracks |
| `format_playlist` | see below | Path template for playlist tracks |
| `format_mix` | see below | Path template for mix tracks |
| `format_track` | see below | Path template for standalone tracks |
| `format_video` | see below | Path template for videos |

---

## Path Format Templates

Download paths are built from template strings using `{token}` placeholders.

### Default templates

| Context | Default |
| --- | --- |
| Album | `{album_artist}/{album_title}/{track_volume_num_optional_CD}/{track_title}` |
| Playlist | `Playlists/{playlist_name}/{list_pos}. {artist_name} - {track_title}` |
| Mix | `Mix/{mix_name}/{artist_name} - {track_title}` |
| Track | `{album_artist}/{album_title}/{track_title}` |
| Video | `Videos/{artist_name}/{track_title}` |

### Available tokens

**Names**

| Token | Description |
| --- | --- |
| `{artist_name}` | Primary artist name |
| `{album_artist}` | Album artist |
| `{album_artists}` | All album artists (joined) |
| `{track_title}` | Track title |
| `{mix_name}` | Mix name |
| `{playlist_name}` | Playlist name |
| `{album_title}` | Album title |

**Numbers**

| Token | Description |
| --- | --- |
| `{album_track_num}` | Track number (zero-padded) |
| `{album_num_tracks}` | Total tracks in album |
| `{list_pos}` | Position in playlist or collection |
| `{album_num_volumes}` | Number of discs/volumes |
| `{track_volume_num}` | Disc/volume number |
| `{track_volume_num_optional}` | Disc number; empty string for single-disc albums |
| `{track_volume_num_optional_CD}` | `CD1/`, `CD2/`, … — empty for single-disc (use as a path segment) |

**IDs**

| Token | Description |
| --- | --- |
| `{track_id}` | Tidal track ID |
| `{playlist_id}` | Tidal playlist ID |
| `{video_id}` | Tidal video ID |
| `{album_id}` | Tidal album ID |
| `{isrc}` | ISRC code |

**Durations**

| Token | Description |
| --- | --- |
| `{track_duration_seconds}` | Track duration in seconds |
| `{track_duration_minutes}` | Track duration as M:SS |
| `{album_duration_seconds}` | Album duration in seconds |
| `{album_duration_minutes}` | Album duration as M:SS |

**Dates**

| Token | Description |
| --- | --- |
| `{album_year}` | Album release year |
| `{album_date}` | Album release date (YYYY-MM-DD) |

**Metadata flags**

| Token | Description |
| --- | --- |
| `{video_quality}` | Video quality string |
| `{track_quality}` | Track quality / format string |
| `{track_explicit}` | `(Explicit)` or empty |
| `{album_explicit}` | `(Explicit)` or empty |
| `{media_type}` | `TRACK`, `VIDEO`, etc. |

---

## Embedded Metadata

Metadata written to all downloaded files (FLAC, MP3, MP4):

- Title, album, album artist, artist
- Track number / total, disc number / total
- Release date, ISRC, copyright, composer
- Cover art (embedded)
- Synced and unsynced lyrics (when `lyrics_embed = true`)
- BPM, initial key (Camelot notation), replay gain
- UPC (album barcode), Tidal share URL

MP3-specific tags: `TPE2` (album artist), `TPOS` (disc number), `WOAS` (share URL), `TRCK` written as `N/total`.

MP4-specific atoms: `aART` (album artist).

---

## Features

- **CLI-only** — no GUI, no interactive menus; every action is a typed command
- **Bare URL shorthand** — `tidal-dl <URL>` works without any subcommand
- **Concurrent downloads** — configurable parallelism (default: 3)
- **ISRC duplicate detection** — persistent cross-session index at `~/.config/tidal-dl/isrc_index.json`; stale entries pruned automatically; thread-safe
- **Library scanning** — seed the ISRC index from your existing music collection (FLAC/MP3/M4A/OGG) via `tidal-dl scan`; prevents re-downloading tracks already on disk
- **Skip existing** — skips files that already exist on disk
- **Dual download sources** — Hi-Fi API (public proxy, stateless) handles both metadata and streaming by default; OAuth serves as an automatic fallback
- **Hi-Fi API instance rotation** — auto-discovers live instances from uptime trackers; dead instances are quarantined and skipped automatically
- **Playlist import** — import from Spotify, Apple Music, or any platform via CSV/TSV or `Artist - Title` text files
- **Playlist M3U generation** — an M3U playlist file is always generated for playlist downloads so music players can recognize the folder as a playlist; original track metadata (album, artist, artwork) is preserved
- **Multi-disc M3U** — when `playlist_create = true`, a single consolidated M3U is written at the album root with relative paths; works correctly across multi-disc albums
- **Download checkpointing** — interrupted collection downloads can resume from where they left off
- **API response caching** — in-memory TTL cache reduces redundant HTTP calls during a session
- **FFmpeg auto-discovery** — finds FFmpeg via PATH automatically; no manual configuration needed
- **One-off output override** — `--output/-o` overrides the download root for a single invocation only
- **Download summary** — a Rich panel shows downloaded / skipped / failed counts after every collection download
- **Config reset** — `cfg --reset` backs up the existing config to `.json.bak` before writing fresh defaults
- **OAuth browser login** — `tidal-dl login` opens your browser automatically; Rich clickable fallback link if browser unavailable
- **Dolby Atmos** — optionally download Atmos variants (`download_dolby_atmos = true`)
- **Favourites** — `dl_fav` downloads your entire Tidal favourites library with optional `--since` date filter
- **Collision avoidance** — uniquify mode prevents filename collisions for same-title tracks in the same directory

---

## Disclaimer

- For private, personal use only.
- Requires a valid Tidal subscription.
- Do not use this tool to distribute or share copyrighted material.
- Usage may be subject to legal restrictions in your jurisdiction.

---

## Credits

Originally created by [yaronzz](https://github.com/yaronzz/Tidal-Media-Downloader). This fork ports the next-generation engine from [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng) into the original project structure.

**Libraries used:**
- [tidalapi](https://github.com/tamland/python-tidal) — Tidal API client
- [mutagen](https://mutagen.readthedocs.io/) — audio metadata
- [Rich](https://github.com/Textualize/rich) — terminal output
- [Typer](https://typer.tiangolo.com/) — CLI framework
- [python-ffmpeg](https://github.com/jonghwanhyeon/python-ffmpeg) — FFmpeg bindings
- [pycryptodome](https://www.pycryptodome.org/) — AES decryption
