<div align="center">
  <h1>music-dl</h1>
  <p>Download and manage your Tidal music library — from your browser.</p>
  <a href="https://github.com/alfdav/music-dl/blob/master/LICENSE">
    <img src="https://img.shields.io/github/license/alfdav/music-dl.svg?style=flat-square" alt="License">
  </a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square" alt="Python 3.12+">
</div>

---

## Quick Start

### Docker (recommended)

```shell
docker build -f docker/Dockerfile -t music-dl .
docker run --rm -it -p 8765:8765 \
  -v "$HOME/.config/music-dl:/root/.config/music-dl" \
  -v "$HOME/music-downloads:/root/download" \
  music-dl gui --no-browser
```

Open [http://localhost:8765](http://localhost:8765) in your browser.

### pip / uv

```shell
uv tool install --from git+https://github.com/alfdav/music-dl.git#subdirectory=TIDALDL-PY music-dl
music-dl gui
```

---

## Screenshots

<!-- TODO: add screenshots -->

---

## Features

- **Library Browser** — paginated view of your local collection, backed by a SQLite cache for instant loads
- **Tidal Search & Download** — search Tidal's full catalog, see which tracks you already own, download with one click
- **Quality Upgrades** — re-download existing tracks at a higher quality (MQA, HiRes, lossless) without duplicating your library
- **Duplicate Cleanup** — ISRC-based deduplication surfaces exact copies across your collection so you can remove them
- **Playback** — stream tracks directly in the browser, bit-perfect to your DAC (no signal processing)
- **Smart Library** — Tidal playlists sync against your local files; only missing tracks are downloaded

---

## Configuration

Settings are managed from the in-app **Settings** page. The underlying file is `~/.config/music-dl/settings.json`.

Key defaults:

| Setting | Default |
| --- | --- |
| `download_base_path` | `~/download` |
| `quality_audio` | `HI_RES_LOSSLESS` |
| `download_source` | `hifi_api` |
| `skip_existing` | `true` |
| `skip_duplicate_isrc` | `true` |

---

## CLI Usage

For power users and scripting:

```shell
music-dl --help
music-dl dl <URL> [<URL> ...]   # download one or more Tidal URLs
music-dl search <query>         # search and download from the terminal
music-dl gui [--port PORT]      # launch the browser UI
```

Full command reference: `music-dl --help`.

---

## Development

```shell
git clone git@github.com:alfdav/music-dl.git
cd music-dl/TIDALDL-PY
uv sync
music-dl gui
```

Run tests:

```shell
pytest
```

---

## Security

The GUI server binds to `localhost` only. It does not use HTTPS. Do not expose port 8765 to untrusted networks.

---

## License

Apache-2.0. See [LICENSE](LICENSE).

---

## Disclaimer

This is a personal project for educational purposes and private use only. Not affiliated with or endorsed by TIDAL. A valid TIDAL subscription is required. Downloaded files are for personal offline use in accordance with your subscription terms. You are solely responsible for compliance with applicable laws and TIDAL's Terms of Service.

---

## Credits

Built on prior work from [yaronzz/Tidal-Media-Downloader](https://github.com/yaronzz/Tidal-Media-Downloader) and [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng). Core libraries: [tidalapi](https://github.com/tamland/python-tidal), [mutagen](https://mutagen.readthedocs.io/), [Rich](https://github.com/Textualize/rich), [Typer](https://typer.tiangolo.com/).
