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

The Home view shows recent additions, recently played items, top artists, genre stats, repeat listening, and a Continue Listening card when playback has a saved queue position. Library artist navigation renders page-sized batches, and album navigation uses an in-memory album cache with batched card rendering to keep large collections responsive. Recently Played supports Today, This Week, and Older filters plus clear-old/history controls. The player persists queue, volume, shuffle, repeat, and Smart Shuffle preferences across reloads.

Desktop builds use the same FastAPI static UI through the Tauri sidecar. The Tauri build now checks these QoL markers before bundling so a stale Mac app cannot be packaged silently.

## CLI highlights

```shell
music-dl dl <URL> --output ~/Music/inbox
music-dl dl --list urls.txt
music-dl source show
music-dl source instances
music-dl scan add ~/Music
music-dl scan --all
music-dl sync --yes
music-dl dl_fav tracks --since 2026-01-01
```

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
uv run --project tidaldl-py --extra test pytest
uv build --project tidaldl-py
```

For full project usage, Docker instructions, and screenshots, use the root `README.md`.
