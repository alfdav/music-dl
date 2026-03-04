# tidal-dl changelog

```
pip install git+https://github.com/alfdav/Tidal-Media-Downloader.git#subdirectory=TIDALDL-PY
```

#### v3.0.0 (2025)

Full rewrite of the CLI engine, ported from [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng). No GUI.

**Core**
- New CLI built with Typer; subcommands: `dl`, `dl_fav`, `login`, `logout`, `cfg`
- Bare URL shorthand: `tidal-dl <URL>` works directly without a subcommand
- Package entry point changed to `tidal_dl.cli:main`
- Requires Python 3.12 or 3.13; all legacy Python 2 / Python 3 < 3.12 code removed
- Migrated from `setup.py` to `pyproject.toml`; no more `setup-gui.py`

**Authentication**
- OAuth device flow: `tidal-dl login` auto-opens the browser
- Rich clickable fallback link printed if the browser cannot be opened
- Credentials cached at `~/.config/tidal-dl/` with automatic token refresh

**Downloads**
- `dl --output/-o DIR` — one-off output directory override per invocation
- `dl --list/-l FILE` — batch download URLs from a text file
- `dl_fav tracks|albums|artists|videos [--since DATE]` — download Tidal favourites
- Download summary Rich panel: downloaded / skipped / failed counts after each collection
- Configurable concurrency (`downloads_concurrent_max`, default 3)
- Optional random delay between downloads (`download_delay`)

**Duplicate detection**
- ISRC-based cross-session duplicate detection (`skip_duplicate_isrc = true`)
- Persistent index at `~/.config/tidal-dl/isrc_index.json`; stale entries pruned automatically; thread-safe

**Path templates**
- New `{token}` placeholder syntax (replaces old `{PascalCase}` tags)
- New tokens: `track_volume_num_optional_CD`, `album_artists`, `list_pos`, `isrc`, `album_duration_*`, `track_duration_*`, `track_explicit`, `album_explicit`, `media_type`, and more
- New default templates with artist/album/track hierarchy; players sort by embedded TRACKNUMBER/DISCNUMBER
- `{track_volume_num_optional_CD}` emits `CD1/`, `CD2/`, etc. only for multi-disc albums
- `uniquify = true` prevents filename collisions for same-title tracks

**Metadata**
- Writes full metadata to FLAC, MP3, and MP4: title, album, artist, albumartist, tracknumber/total, discnumber/total, date, ISRC, copyright, composer, cover art, BPM, initial key (Camelot), replay gain, UPC, share URL
- Synced and unsynced lyrics embedding (`lyrics_embed`); separate `.lrc` file (`lyrics_file`)
- MP3 fixes: `TPE2` (not `TOPE`) for album artist; `TPOS` for disc number; `WOAS` for Tidal share URL; `TRCK` as `N/total`

**M3U playlists**
- Single consolidated M3U at the album root using `rglob`; relative paths throughout
- Works correctly for multi-disc albums across subdirectories
- Optional symlink from playlist folder to track file (`symlink_to_track`)

**FFmpeg**
- Auto-discovered via `shutil.which` — no configuration needed if FFmpeg is on PATH
- `path_binary_ffmpeg` setting overrides auto-discovery
- Used for FLAC extraction from M4A (`extract_flac`) and video remux to MP4 (`video_convert_mp4`)

**Configuration**
- `tidal-dl cfg` — view/change settings; `--editor` to open in `$EDITOR`
- `tidal-dl cfg --reset` — backs up existing config to `.json.bak`, writes fresh defaults
- 40 settings in the `Settings` dataclass; stored at `~/.config/tidal-dl/settings.json`

**Removed**
- GUI (`tidal-gui`, `gui.py`)
- All multi-language `lang/` modules (21 files)
- Legacy `setup.py`, `setup-gui.py`, `apiKey.py`, `events.py`, `model.py`, `paths.py`, `printf.py`, `settings.py`, `tidal.py`, `enums.py`, `decryption.py`

---

<details>
<summary>Legacy changelog (v1.x / v2.x — yaronzz era)</summary>

See the original project history at [yaronzz/Tidal-Media-Downloader](https://github.com/yaronzz/Tidal-Media-Downloader).

</details>
