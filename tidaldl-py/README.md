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

The web UI opens in your browser and serves the local music library, search, download, and playback flows. Album search can refine the current cached page of Tidal results by quality or content rating, with independent resolution, Atmos, and Explicit badges.

You need your own active Tidal account. music-dl does not provide access to
Tidal without sign-in.

Tidal sign-in and reconnect can be started directly from the GUI; terminal `music-dl login` remains available for CLI-first use.

The GUI keeps a static **Report bug** link in the app chrome and no-JavaScript fallback. It opens the GitHub bug report template directly without depending on local API calls.

The Home view shows recent additions, recently played items, top artists, genre stats, repeat listening, and a Continue Listening card when playback has a saved queue position. Home loads aggregate library statistics without rebuilding every grouped album card, and reports a visible error instead of presenting a failed request as an empty library. Library artist navigation renders page-sized batches, and album navigation uses an in-memory album cache with batched card rendering to keep large collections responsive. Recently Played supports Today, This Week, and Older filters plus clear-old/history controls. The player persists queue, volume, shuffle, repeat, and Smart Shuffle preferences across reloads.

Continue Listening ignores finished tracks and near-end positions so completed songs do not reappear as one-second resume cards.

Recently Added is a dedicated Library category instead of a repeated shelf on every Library sort tab.

Desktop builds use the same FastAPI static UI through the Tauri sidecar. The Tauri build now checks these QoL markers before bundling so a stale Mac app cannot be packaged silently. The macOS shell also accepts the PyInstaller worker PID as the ready sidecar process so packaged apps do not stall on the startup screen.

## CLI highlights

```shell
music-dl dl <URL> --output ~/Music/inbox
music-dl dl --list urls.txt
music-dl scan add ~/Music
music-dl scan --all
music-dl sync --yes
music-dl dl_fav tracks --since 2026-01-01
```

## DJAI

DJAI is the GUI home for automation modules (Discord Bot, Edition advice).
DJAI modules that use AI can make mistakes. Verify important actions yourself
before you confirm them. See [`docs/djai-modules.md`](docs/djai-modules.md).

## Discord bot (optional)

A companion Discord bot streams and downloads from your library over voice.
Open the GUI's DJAI view to save the bot config and start, restart, or shut
down the bot service from the browser. When the bot starts, it posts or
refreshes one DJAI remote panel in the allowed Discord channel so the allowed
user can search, pick playlists, control playback, and repeat playlists without
copying Tidal IDs. The compatibility flag only prints a reminder that setup
stays in the GUI:

```shell
music-dl gui --setup-bot
```

See [`docs/bot-onboarding.md`](docs/bot-onboarding.md) for the GUI setup flow
and [`../apps/discord-bot/README.md`](../apps/discord-bot/README.md) for the
bot itself.

## Edition advice (optional)

A DJAI module that shows TypeSafe Jev edition chips on Clean Up. Enable it
from **DJAI → Edition advice**, not Settings. AI suggestions can be wrong;
confirm paths yourself before Clean Up. See
[`docs/djai-edition-advice.md`](docs/djai-edition-advice.md) and the
[`DJAI overview`](docs/djai-modules.md).

## Development

From the repository root:

```shell
PYTHONNOUSERSITE=1 uv run --project tidaldl-py --extra test python -m pytest
uv build --project tidaldl-py
```

For full project usage, Docker instructions, and screenshots, use the root `README.md`.
