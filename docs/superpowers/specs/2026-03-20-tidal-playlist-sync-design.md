# Tidal Playlist Sync — Design Spec

## Overview

A `music-dl sync` command that compares the user's Tidal playlists against the local ISRC index, reports what's missing, and downloads only the gaps.

## CLI Interface

```
music-dl sync [--yes]
```

- `--yes` / `-y`: Skip per-playlist prompt, download all missing tracks automatically.
- No other flags. Syncs all playlists in the user's Tidal collection (owned + favorited).

## Authentication & Download Source Split

- **Playlist enumeration** requires OAuth login — only an authenticated session can list the user's playlists and their track contents.
- **Track downloads** use the Hi-Fi API (existing default behavior). OAuth is only needed for the enumeration step, not for the heavy downloading.

This matches the existing app architecture: Hi-Fi API is preferred for downloads, OAuth is the fallback.

## Sync Flow

1. **Login** — invoke existing `login` command to ensure an OAuth session is active.
2. **Fetch playlists** — call `tidal.session.user.favorites.playlists()` via tidalapi. This endpoint returns playlists in the user's collection (owned + favorited). It is limited to 50 results per call, so the command must paginate explicitly (loop with `offset += 50` until fewer than 50 results return).
3. **Fetch tracks per playlist** — get the full track list for each playlist, extract ISRCs. Tracks without ISRCs (rare — some regional content, videos) are counted as "missing" in the summary since they cannot be matched. This means ISRC-less tracks may re-download on each sync; this is acceptable given their rarity.
4. **Diff against ISRC index** — load `IsrcIndex`, call `contains()` for each track's ISRC. This diff is **presentation-only** — it feeds the summary table so the user can make informed per-playlist decisions.
5. **Present summary** — Rich table showing playlist name, total track count, local count, and missing count.
6. **Prompt per playlist** — interactive prompt with options: `[Y]es / [n]o / [a]ll / [q]uit`. `[a]ll` means "download all remaining playlists without further prompting" (equivalent to `--yes` from this point on). Playlists with 0 missing tracks are shown in the table but not prompted for. Skipped entirely with `--yes`.
7. **Download** — pass selected playlist URLs to existing `_download()`. The full existing pipeline runs: Hi-Fi API downloads, ISRC dedup via `skip_duplicate_isrc`, `skip_existing` file checks, progress bars, checkpoints, and M3U playlist rebuild via `playlist_populate()`. The ISRC diff in step 4 is intentionally redundant with the pipeline's own skip logic — step 4 provides the user-facing summary, the pipeline provides the actual skip behavior. This means sync correctness does not depend on config flags; even if `skip_duplicate_isrc` is off, the worst case is re-downloading tracks that already exist (same as a normal playlist download).

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
- **~200 lines** of new code: the command function, pagination loop, a helper to fetch playlists + diff ISRCs, Rich table rendering, and interactive prompt logic.
- **Full reuse** of existing infrastructure: `_download()`, `Download.items()`, `IsrcIndex`, `playlist_populate()`, checkpoint system, rate-limit handling.

## Error Handling & Edge Cases

| Case | Behavior |
|---|---|
| Not logged in | Triggers existing login flow, stores token |
| Empty playlists | Shown in table with 0/0, skipped automatically |
| No missing tracks (all playlists) | Print "All playlists up to date", exit cleanly |
| ISRC index not seeded | All tracks show as missing (correct). User can run `music-dl scan` first to seed from existing library. |
| API rate limits during download | Handled by existing adaptive rate-limit logic in the download pipeline |
| API rate limits during enumeration | tidalapi calls during playlist/track fetching are not throttled by the app. For large collections (50+ playlists), a brief delay between pagination calls may be needed. Monitor during implementation. |
| Tracks without ISRCs | Counted as "missing" in summary since they can't be ISRC-matched. May re-download on each sync. Acceptable given rarity. |
| Interrupted sync | Existing checkpoint system handles resume for collection downloads |
| Collaborative / followed playlists | `favorites.playlists()` returns playlists in the user's collection (owned + favorited). Collaborative playlists not explicitly added to the collection may not appear. |

## Out of Scope

- **No removal sync** — tracks removed from Tidal playlists are not deleted locally.
- **No scheduled/automatic runs** — user runs `music-dl sync` manually (or via their own cron).
- **No playlist selection persistence** — no "remember which playlists I chose last time" config.
- **No new config settings** — sync reuses existing `skip_existing`, `skip_duplicate_isrc`, `format_playlist`, and download source settings.
- **No new module files** — everything lives in `cli.py`.
