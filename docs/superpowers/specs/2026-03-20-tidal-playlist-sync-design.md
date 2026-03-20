# Tidal Playlist Sync — Design Spec

## Overview

A `music-dl sync` command that compares the user's Tidal playlists against the local ISRC index, reports what's missing, and downloads only the gaps.

## CLI Interface

```
music-dl sync [--yes]
```

- `--yes` / `-y`: Skip per-playlist prompt, download all missing tracks automatically.
- No other flags. Syncs all user-created and followed playlists.

## Authentication & Download Source Split

- **Playlist enumeration** requires OAuth login — only an authenticated session can list the user's playlists and their track contents.
- **Track downloads** use the Hi-Fi API (existing default behavior). OAuth is only needed for the enumeration step, not for the heavy downloading.

This matches the existing app architecture: Hi-Fi API is preferred for downloads, OAuth is the fallback.

## Sync Flow

1. **Login** — invoke existing `login` command to ensure an OAuth session is active.
2. **Fetch playlists** — call `tidal.session.user.playlists()` via tidalapi (paginated).
3. **Fetch tracks per playlist** — get the full track list for each playlist, extract ISRCs.
4. **Diff against ISRC index** — load `IsrcIndex`, call `contains()` for each track's ISRC.
5. **Present summary** — Rich table showing playlist name, total track count, local count, and missing count.
6. **Prompt per playlist** — interactive prompt with options: `[Y]es / [n]o / [a]ll / [q]uit`. Playlists with 0 missing tracks are shown in the table but not prompted for. Skipped entirely with `--yes`.
7. **Download** — call existing `_download()` with the selected playlist URLs. This reuses the full existing pipeline: Hi-Fi API downloads, ISRC dedup, `skip_existing`, progress bars, checkpoints, and M3U playlist rebuild via `playlist_populate()`.

### Summary Table Example

```
Playlist              Total   Local   Missing
──────────────────────────────────────────────
Chill Vibes             42      38        4
Workout Mix             67      67        0
New Discoveries         23       9       14
```

## Implementation Approach

- **No new modules.** The sync command is added to `cli.py` as `app.command(name="sync")`.
- **~150 lines** of new code: the command function, a helper to fetch playlists + diff ISRCs, and the Rich table/prompt logic.
- **Full reuse** of existing infrastructure: `_download()`, `Download.items()`, `IsrcIndex`, `playlist_populate()`, checkpoint system, rate-limit handling.

## Error Handling & Edge Cases

| Case | Behavior |
|---|---|
| Not logged in | Triggers existing login flow, stores token |
| Empty playlists | Shown in table with 0/0, skipped automatically |
| No missing tracks (all playlists) | Print "All playlists up to date", exit cleanly |
| ISRC index not seeded | All tracks show as missing (correct). User can run `music-dl scan` first to seed from existing library. |
| API rate limits | Handled by existing adaptive rate-limit logic in the download pipeline |
| Interrupted sync | Existing checkpoint system handles resume for collection downloads |
| Collaborative / followed playlists | Included — `user.playlists()` returns owned + followed playlists |

## Out of Scope

- **No removal sync** — tracks removed from Tidal playlists are not deleted locally.
- **No scheduled/automatic runs** — user runs `music-dl sync` manually (or via their own cron).
- **No playlist selection persistence** — no "remember which playlists I chose last time" config.
- **No new config settings** — sync reuses existing `skip_existing`, `skip_duplicate_isrc`, `format_playlist`, and download source settings.
- **No new module files** — everything lives in `cli.py`.
