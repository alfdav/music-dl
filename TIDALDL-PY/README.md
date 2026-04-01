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

Recently Added in Library — A Library-first shelf and sidebar shortcut for the newest local albums, preferring successful downloads over plain scan recency.

## Development

From the repository root:

```shell
uv run --project TIDALDL-PY pytest
uv build --project TIDALDL-PY
```

For full project usage, Docker instructions, and screenshots, use the root `README.md`.
