<div align="center">
  <h1>music-dl</h1>
  <p><code>music-dl</code> is a CLI-only TIDAL downloader built on the current Typer-based engine. Download tracks, albums, playlists, mixes, favourites, and videos from the terminal.</p>
  <p>The project was renamed from <code>tidal-dl</code> to <code>music-dl</code>. The old command still exists as a temporary compatibility alias, but <code>music-dl</code> is the primary interface going forward.</p>
  <a href="https://github.com/alfdav/music-dl/blob/master/LICENSE">
    <img src="https://img.shields.io/github/license/alfdav/music-dl.svg?style=flat-square" alt="License">
  </a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square" alt="Python 3.12+">
</div>

---

## Requirements

- Python 3.12 or 3.13
- FFmpeg on `PATH` if you want video remuxing or FLAC extraction
- A valid TIDAL subscription

---

## Install

### Recommended: install with UV

```shell
uv tool install --from git+https://github.com/alfdav/music-dl.git#subdirectory=TIDALDL-PY music-dl
```

After installation, use:

```shell
music-dl --help
```

Compatibility note:

- `music-dl` is the supported command name.
- `tidal-dl` is still installed as a compatibility alias for existing users.

### Development setup

```shell
git clone git@github.com:alfdav/music-dl.git
cd music-dl/TIDALDL-PY
uv sync
uv run python -m tidal_dl.cli --help
```

Use the module entrypoint in development. It is the most reliable way to run the local checkout directly.

### Docker

If you do not want a local Python or FFmpeg install, use Docker instead. See [docker/README.md](docker/README.md).

---

## First Run

### Download something immediately

The app supports bare URL downloads. No subcommand is required.

```shell
music-dl https://tidal.com/browse/album/123456789
```

### Login

`music-dl` defaults to the Hi-Fi API source. That means direct URL downloads can often work without logging in first.

OAuth login is still important when you want:

- playlist sync (`music-dl sync`)
- favourites downloads
- OAuth fallback when the Hi-Fi API source is unavailable
- a stored personal session for broader metadata access

```shell
music-dl login
music-dl logout
```

Credentials and settings live in `~/.config/music-dl/`.

If you previously used `tidal-dl`, the old config directory at `~/.config/tidal-dl/` is migrated automatically on first run.

---

## Core Workflows

### Download one or more URLs

```shell
music-dl https://tidal.com/browse/track/123456789
music-dl dl https://tidal.com/browse/album/123456789 https://tidal.com/browse/playlist/abcdef
music-dl dl --list urls.txt
music-dl dl --output /tmp/music-import https://tidal.com/browse/album/123456789
```

### Download favourites

```shell
music-dl dl_fav tracks
music-dl dl_fav albums
music-dl dl_fav artists
music-dl dl_fav videos
music-dl dl_fav tracks --since 2026-01-01
music-dl dl_fav tracks --since 2026-01-01T12:30:00
```

`--since` accepts:

- `YYYY-MM-DD`
- `YYYY-MM-DDTHH:MM:SS`
- Unix timestamps

### Import a playlist from another platform

Accepted formats:

- CSV or TSV with `title`, `artist`, and optional `isrc`
- Plain text with one `Artist - Title` entry per line

Examples:

```text
title,artist,isrc
Bohemian Rhapsody,Queen,GBUM71029604
Hotel California,Eagles,
```

```text
Queen - Bohemian Rhapsody
Eagles - Hotel California
```

Run it:

```shell
music-dl import my_playlist.csv
music-dl import my_playlist.txt --output /tmp/import
```

Matching order:

1. ISRC exact match
2. Title + artist search fallback

### Manage download sources

`music-dl` supports two download backends:

- `hifi_api` - default, public community proxy instances
- `oauth` - your personal TIDAL OAuth session

```shell
music-dl source show
music-dl source set hifi_api
music-dl source set oauth
music-dl source instances
music-dl source add https://my.instance.example
music-dl source remove https://my.instance.example
```

Important behavior:

- `download_source = hifi_api` is the default
- `download_source_fallback = true` is enabled by default
- when the preferred source fails, the app can fall back automatically
- an OAuth login is still useful even when Hi-Fi API is your preferred source

### Sync Tidal playlists

Compare your Tidal playlists against your local library and download missing tracks.

```shell
music-dl sync           # Interactive — prompts per playlist
music-dl sync --yes     # Download all missing tracks without prompting
```

Requires OAuth login for playlist enumeration. Downloads use the Hi-Fi API by default.

Tip: run `music-dl scan add /path/to/library` first to seed the duplicate index from your existing collection, so sync only downloads what you're truly missing.

### Seed the duplicate index from an existing library

The persistent duplicate index lives at `~/.config/music-dl/isrc_index.json`.

Use `scan` to seed it from an existing library so the downloader can skip tracks you already own.

```shell
music-dl scan add /Volumes/Music
music-dl scan
music-dl scan --all
music-dl scan --dry-run
music-dl scan show
music-dl scan remove /Volumes/Music
```

Key behavior:

- if exactly one scan path is configured, `music-dl scan` uses it directly
- if multiple scan paths are configured, `music-dl scan` prompts for a selection unless `--all` is used
- `scan add` scans immediately unless you pass `--no-scan`

Supported audio containers for scanning include FLAC, MP3, M4A, MP4, and OGG.

---

## Command Summary

```text
music-dl <URL>
music-dl dl [URLS]... [--list FILE] [--output DIR] [--debug]
music-dl dl_fav tracks|albums|artists|videos [--since TIMESTAMP]
music-dl import FILE [--output DIR] [--debug]
music-dl sync [--yes]
music-dl login
music-dl logout
music-dl cfg [KEY] [VALUE]
music-dl cfg --editor
music-dl cfg --reset
music-dl source show
music-dl source set {hifi_api|oauth}
music-dl source instances
music-dl source add URL
music-dl source remove URL
music-dl scan [--dry-run] [--all] [--verbose]
music-dl scan add PATH [--no-scan]
music-dl scan remove PATH
music-dl scan show
music-dl --version
```

---

## Configuration

Main settings file:

- `~/.config/music-dl/settings.json`

Useful config commands:

```shell
music-dl cfg
music-dl cfg download_base_path
music-dl cfg download_base_path /Volumes/Music/Incoming
music-dl cfg download_source oauth
music-dl cfg --editor
music-dl cfg --reset
```

### Important defaults

| Setting | Default | Notes |
| --- | --- | --- |
| `download_base_path` | `~/download` | Root download destination |
| `quality_audio` | `HI_RES_LOSSLESS` | TIDAL degrades automatically based on subscription |
| `quality_video` | `1080` | Video quality setting |
| `download_source` | `hifi_api` | Preferred audio source |
| `download_source_fallback` | `true` | Fall back automatically when needed |
| `hifi_api_instances` | `""` | Empty means auto-discover instances |
| `skip_existing` | `true` | Skip files already present on disk |
| `skip_duplicate_isrc` | `true` | Skip tracks already seen in the persistent ISRC index |
| `duplicate_action` | `copy` | Copy, ask, redownload, or skip on duplicate detection |
| `scan_paths` | `""` | Managed through `scan add/remove/show` |
| `extract_flac` | `true` | Uses FFmpeg when applicable |
| `video_convert_mp4` | `true` | Remuxes video output to MP4 |
| `playlist_create` | `false` | Albums and mixes only; playlists always generate M3U |
| `symlink_to_track` | `false` | Symlink playlist items to track storage |
| `downloads_concurrent_max` | `3` | Maximum parallel downloads |
| `downloads_simultaneous_per_track_max` | `20` | Chunk concurrency per track |
| `api_cache_enabled` | `true` | In-memory API response cache |
| `api_cache_ttl_sec` | `300` | Cache TTL in seconds |

### Path templates

Default path templates:

| Context | Template |
| --- | --- |
| Album | `{album_artist}/{album_title}/{track_volume_num_optional_CD}/{track_title}` |
| Playlist | `Playlists/{playlist_name}/{list_pos}. {artist_name} - {track_title}` |
| Mix | `Mix/{mix_name}/{artist_name} - {track_title}` |
| Track | `{album_artist}/{album_title}/{track_title}` |
| Video | `Videos/{artist_name}/{track_title}` |

Common template tokens:

| Token | Meaning |
| --- | --- |
| `{artist_name}` | Track or video artist |
| `{album_artist}` | Primary album artist |
| `{album_artists}` | All album artists joined by the configured delimiter |
| `{track_title}` | Track title |
| `{album_title}` | Album title |
| `{playlist_name}` | Playlist name |
| `{mix_name}` | Mix name |
| `{list_pos}` | Playlist or collection position |
| `{track_volume_num_optional_CD}` | `CD1/`, `CD2/`, etc. for multi-disc albums |
| `{isrc}` | Track ISRC |
| `{album_year}` | Album release year |
| `{track_explicit}` | Explicit marker or empty string |

---

## Metadata and Output Behavior

The downloader writes rich metadata to supported files, including:

- title, album, artist, album artist
- track and disc numbering
- release date and ISRC
- cover art
- lyrics when enabled
- replay gain and initial key when available
- TIDAL share URL
- album barcode / UPC target metadata

Other behavior worth knowing:

- playlists always produce a UTF-8 `.m3u8` file with relative paths
- albums and mixes produce an M3U when `playlist_create = true`
- duplicate detection is cross-session, not just per run
- interrupted collection downloads can resume from checkpoints
- FFmpeg is auto-discovered on `PATH`
- existing configs that still use the untouched legacy `- Playlists/...` default are migrated automatically to `Playlists/...`

---

## Docker

Docker instructions live in [docker/README.md](docker/README.md).

Use Docker when you want:

- no local Python install
- no host FFmpeg install
- a clean portable runtime for servers, NAS boxes, or containers

---

## Disclaimer

- Personal use only
- Requires a valid TIDAL subscription
- Do not redistribute copyrighted content
- You are responsible for complying with local law and TIDAL's terms

---

## Credits

This project builds on prior work from:

- [yaronzz/Tidal-Media-Downloader](https://github.com/yaronzz/Tidal-Media-Downloader)
- [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng)

Primary libraries:

- [tidalapi](https://github.com/tamland/python-tidal)
- [mutagen](https://mutagen.readthedocs.io/)
- [Rich](https://github.com/Textualize/rich)
- [Typer](https://typer.tiangolo.com/)
- [python-ffmpeg](https://github.com/jonghwanhyeon/python-ffmpeg)
- [pycryptodome](https://www.pycryptodome.org/)
