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
tidal-dl <URL>                         Download a Tidal URL (bare shorthand)
tidal-dl dl <URL>... [OPTIONS]         Explicit download subcommand; accepts multiple URLs
tidal-dl dl -l/--list FILE             Read URLs from a text file (one per line)
tidal-dl dl -o/--output DIR            Override output directory for this run only
tidal-dl dl -d/--debug                 Enable verbose debug logging
tidal-dl dl_fav tracks                 Download favourite tracks
tidal-dl dl_fav albums                 Download favourite albums
tidal-dl dl_fav artists                Download favourite artists' albums
tidal-dl dl_fav videos                 Download favourite videos
tidal-dl dl_fav tracks --since DATE    Only items added after DATE (YYYY-MM-DD)
tidal-dl login                         OAuth login (auto-opens browser)
tidal-dl logout                        Clear saved credentials
tidal-dl cfg                           Show all settings
tidal-dl cfg KEY                       Show one setting value
tidal-dl cfg KEY VALUE                 Change one setting
tidal-dl cfg -e/--editor               Open config file in $EDITOR
tidal-dl cfg --reset                   Reset to defaults (backs up existing to .json.bak)
tidal-dl -v/--version                  Show version
```

---

## Configuration

Config is stored at `~/.config/tidal-dl/settings.json`. Use `tidal-dl cfg` to view or change any setting.

| Setting | Default | Description |
| --- | --- | --- |
| `path` | `./` | Root download directory |
| `quality_audio` | `low_320k` | `low_96k` / `low_320k` / `high` / `lossless` / `hi_res_lossless` |
| `quality_video` | `480p` | `144p` / `240p` / `360p` / `480p` / `720p` / `1080p` |
| `skip_existing` | `true` | Skip if the output file already exists on disk |
| `skip_duplicate_isrc` | `true` | Skip tracks whose ISRC was already downloaded (cross-session) |
| `download_dolby_atmos` | `false` | Download Dolby Atmos variant when available |
| `extract_flac` | `true` | Extract FLAC from M4A container when possible |
| `video_convert_mp4` | `true` | Remux video to MP4 via FFmpeg |
| `lyrics_embed` | `false` | Embed synced lyrics in audio tags |
| `lyrics_file` | `false` | Save lyrics as a separate `.lrc` file |
| `playlist_create` | `false` | Generate M3U playlist files |
| `symlink_to_track` | `false` | Create a symlink to the track inside the playlist folder |
| `downloads_concurrent_max` | `3` | Maximum parallel downloads |
| `download_delay` | `true` | Add a small random delay between downloads |
| `path_binary_ffmpeg` | `""` | Path to FFmpeg binary; empty = auto-discover via PATH |
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
| Album | `Albums/{album_artist}/{album_title}/{track_volume_num_optional_CD}/{track_title}` |
| Playlist | `Playlists/{playlist_name}/{list_pos}. {artist_name} - {track_title}` |
| Mix | `Mix/{mix_name}/{artist_name} - {track_title}` |
| Track | `Tracks/{album_artist}/{album_title}/{track_title}` |
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

---

## Features

- **CLI-only** — no GUI, no interactive menus; every action is a typed command
- **Bare URL shorthand** — `tidal-dl <URL>` works without any subcommand
- **Concurrent downloads** — configurable parallelism (default: 3)
- **ISRC duplicate detection** — persistent cross-session index at `~/.config/tidal-dl/isrc_index.json`; stale entries pruned automatically; thread-safe
- **Skip existing** — skips files that already exist on disk
- **Multi-disc M3U** — when `playlist_create = true`, a single consolidated M3U is written at the album root with relative paths; works correctly across multi-disc albums
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

