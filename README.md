<div align="center">
  <h1>music-dl</h1>
  <p>Your Tidal library, in your browser. Download, manage, and play — all from one place.</p>
  <a href="https://github.com/alfdav/music-dl/blob/master/LICENSE">
    <img src="https://img.shields.io/github/license/alfdav/music-dl.svg?style=flat-square" alt="License">
  </a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square" alt="Python 3.12+">
</div>

<br>

![Home](docs/screenshots/home.png)

## What is this?

A local-first music manager that connects to your Tidal account. Search the catalog, download tracks in lossless or hi-res quality, browse your local collection, and play everything directly in the browser. Your files, your NAS, your rules.

A **setup wizard** walks you through Tidal login and library configuration on first launch — no config files to edit.

## Get Started

### Option 1: Docker Compose (easiest)

```shell
git clone https://github.com/alfdav/music-dl.git
cd music-dl
docker compose up -d
```

Open [http://localhost:8765](http://localhost:8765). Done.

Your config is stored in `~/.config/music-dl` and downloads go to `./music` by default. Override with environment variables:

```shell
MUSIC_DL_CONFIG=~/.config/music-dl MUSIC_DIR=/path/to/music docker compose up -d
```

### Option 2: pip / uv

Requires Python 3.12+ and [ffmpeg](https://ffmpeg.org/).

```shell
uv tool install --from git+https://github.com/alfdav/music-dl.git#subdirectory=TIDALDL-PY music-dl
music-dl gui
```

Your browser opens automatically. The wizard handles the rest.

---

## Screenshots

<details>
<summary>Library — browse by artist with quality badges and instant search</summary>

![Library](docs/screenshots/library.png)
</details>

<details>
<summary>Search — find tracks on Tidal, see what you already own, download in one click</summary>

![Search](docs/screenshots/search.png)
</details>

---

## Features

- **Library browser** — your local collection organized by artist, with album art, quality badges (24-bit, lossless, MQA), and instant search
- **Tidal search & download** — search the full Tidal catalog, see which tracks you already own, download what you're missing
- **Quality upgrades** — re-download existing tracks at higher quality without duplicates
- **Duplicate cleanup** — ISRC-based deduplication finds exact copies across your collection
- **In-browser playback** — play anything in your library, bit-perfect to your DAC
- **Playlist sync** — point it at a Tidal playlist and it downloads only the tracks you don't have
- **Favorites** — mark tracks you love, access them from one place
- **Setup wizard** — first-run experience that walks you through Tidal login and library paths

## CLI

The GUI is the main experience, but everything works from the terminal too:

```shell
music-dl gui                    # launch the web UI
music-dl dl <URL>               # download a track, album, or playlist
music-dl dl <URL> <URL> ...     # download multiple URLs
music-dl cfg                    # view/edit settings
music-dl login                  # authenticate with Tidal
music-dl sync                   # sync library database
```

Run `music-dl --help` for the full list.

## Configuration

Settings are managed from the in-app **Settings** page. The config file lives at `~/.config/music-dl/settings.json`.

| Setting | Default | What it does |
| --- | --- | --- |
| `download_base_path` | `~/download` | Where downloaded files go |
| `quality_audio` | `HI_RES_LOSSLESS` | Preferred audio quality |
| `skip_existing` | `true` | Skip tracks you already have |
| `skip_duplicate_isrc` | `true` | Skip tracks with matching ISRC codes |

## Development

```shell
git clone git@github.com:alfdav/music-dl.git
cd music-dl/TIDALDL-PY
uv sync
music-dl gui
```

Run the test suite:

```shell
pytest
```

Run the release smoke gate from the repository root:

```shell
./scripts/release-smoke.sh
```

That gate covers the GUI command path, app factory/static assets, setup flow, token refresh, package branding, package build, and the published Docker build context.

## Security

The GUI binds to `localhost` only — it is not accessible from other machines. CSRF protection is enabled for all write operations. Do not expose port 8765 to untrusted networks.

## License

Apache-2.0. See [LICENSE](LICENSE).

## Disclaimer

Personal project for educational purposes and private use. Not affiliated with or endorsed by TIDAL. A valid TIDAL subscription is required. Downloaded files are for personal offline use in accordance with your subscription terms. You are responsible for compliance with applicable laws and TIDAL's Terms of Service.

## Credits

Built on [yaronzz/Tidal-Media-Downloader](https://github.com/yaronzz/Tidal-Media-Downloader) and [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng). Powered by [tidalapi](https://github.com/tamland/python-tidal), [mutagen](https://mutagen.readthedocs.io/), [FastAPI](https://fastapi.tiangolo.com/), [Rich](https://github.com/Textualize/rich), and [Typer](https://typer.tiangolo.com/).
