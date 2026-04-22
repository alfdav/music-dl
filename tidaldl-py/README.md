# music-dl

Package-local README for the published `music-dl` Python package.

The main user documentation lives in the repository root at `README.md`.

## Install

```shell
uv tool install --from git+https://github.com/alfdav/music-dl.git#subdirectory=tidaldl-py music-dl
```

## Run

```shell
music-dl gui
```

The web UI opens in your browser and serves the local music library, search, download, and playback flows.

Tidal sign-in and reconnect can be started directly from the GUI; terminal `music-dl login` remains available for CLI-first use.

Recently Added in Library — A Library-first shelf and sidebar shortcut for the newest local albums, preferring successful downloads over plain scan recency.

## Discord bot (optional)

A companion Discord bot streams and downloads from your library over voice.
Set up in one command from the same terminal:

```shell
music-dl gui --setup-bot
```

See [`docs/bot-onboarding.md`](docs/bot-onboarding.md) for the wizard flow
and [`../apps/discord-bot/README.md`](../apps/discord-bot/README.md) for the
bot itself.

## Development

From the repository root:

```shell
uv run --project tidaldl-py pytest
uv build --project tidaldl-py
```

For full project usage, Docker instructions, and screenshots, use the root `README.md`.
