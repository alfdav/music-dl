# music-dl

Package-local README for the published `music-dl` Python package.

The main user documentation lives in the repository root at `README.md`.

## Install

```shell
uv tool install --from git+https://github.com/alfdav/music-dl.git#subdirectory=TIDALDL-PY music-dl
```

## Run

```shell
music-dl gui
```

The web UI opens in your browser and serves the local music library, search, download, and playback flows.

Tidal sign-in and reconnect can be started directly from the GUI; terminal `music-dl login` remains available for CLI-first use.

## Development

From the repository root:

```shell
uv run --project TIDALDL-PY pytest
uv build --project TIDALDL-PY
```

For full project usage, Docker instructions, and screenshots, use the root `README.md`.
