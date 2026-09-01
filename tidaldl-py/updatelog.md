# music-dl changelog

## Current naming note

The project is now called `music-dl`.

Migration details:

- primary CLI name: `music-dl`
- compatibility CLI alias: `tidal-dl`
- current config directory: `~/.config/music-dl/`
- legacy config directory: `~/.config/tidal-dl/`
- legacy config is migrated automatically on first run

Recommended install command:

```shell
uv tool install --from git+https://github.com/alfdav/music-dl.git#subdirectory=tidaldl-py music-dl
```

---

## Unreleased
- Give track-row source labels (`tidal` / `local`) breathing room before the download icon so they no longer sit flush.
- Local library search matches accented titles (`Fria` finds `fría`) and keeps tagged remaster titles, albums, and Hz/bit quality in the list.

## v1.7.8 (2026-08-31)
- Search accepts a pasted Tidal track, album, artist, or playlist URL (or a bare id) and resolves it for add/download instead of sending the URL to catalog search ([#154](https://github.com/alfdav/music-dl/pull/154)).
- Track search falls back to a close album-title match when Tidal returns no tracks (Clásicos de la Provincia 30 Años); artist-name queries on the Tracks pill keep their track hits.
- Artist drill-in is hybrid: local library albums plus Tidal discography.
- Albums pill search no longer regroups the whole library; local and Tidal album sections stay visually separated.
- Recent-search chips truncate the query so the dismiss control stays visible.
- Search keeps the skeleton while Tidal is still in flight, and host parsing cannot 500 on titles like `100% Pure Love`.
- Home insight cards fill the empty middle from unused `/api/home` facts (streak, most replayed, this-week genre, artist genre/counts, week vs all-time) instead of a hero-only void ([#155](https://github.com/alfdav/music-dl/pull/155)).

## v1.7.7 (2026-08-31)
- Hi-Res downloads write real 24-bit/96 kHz audio when Tidal lists the track as HiRes, instead of falling back to 16-bit/44.1 ([#149](https://github.com/alfdav/music-dl/pull/149), [#148](https://github.com/alfdav/music-dl/issues/148)).
- Hi-Res / lossless streams write a real `.flac` container instead of FLAC stuffed in `.m4a` ([#150](https://github.com/alfdav/music-dl/pull/150)).
- Keep a Tidal session alive from one machine login: tokens live outside the app; `token.json` is never wiped except Reset/logout; a new device-code OAuth is never started while a `refresh_token` can still revive; keepalive refresh plus one refresh+retry on Tidal 401 ([#152](https://github.com/alfdav/music-dl/pull/152)).
- Show now-playing lyrics from Tidal when local files have none, and allow saving a sidecar ([#143](https://github.com/alfdav/music-dl/pull/143)).
- Keep a single Home Continue Listening tile when `/home` retries while the music volume is offline ([#142](https://github.com/alfdav/music-dl/pull/142)).
- Center library sort pill labels and keep chips off the search rail ([#144](https://github.com/alfdav/music-dl/pull/144)).
- Add a quiet back arrow on drill-in views ([#145](https://github.com/alfdav/music-dl/pull/145)).
- Serve the albums gallery from release stamps instead of regrouping the whole library ([#146](https://github.com/alfdav/music-dl/pull/146)).
- Home data tiles open a local insight fan overlay ([#147](https://github.com/alfdav/music-dl/pull/147)).

## v1.7.6 (2026-08-18)
- Skip NAS trash dirs (`#recycle` and similar) from the local library scan ([#131](https://github.com/alfdav/music-dl/pull/131)).
- Stop full-library album grouping on artist and release reads ([#133](https://github.com/alfdav/music-dl/pull/133)).
- Stop post-download scans from walking library trash ([#134](https://github.com/alfdav/music-dl/pull/134)).
- Recently Added shows a loading hint and stays under 250ms warmed ([#137](https://github.com/alfdav/music-dl/pull/137)).
- Library writes no longer lock the download worker ([#135](https://github.com/alfdav/music-dl/pull/135)).
- Keep the library cache intact until Sync Library walk succeeds; skip tag repair on already-complete rows ([#136](https://github.com/alfdav/music-dl/pull/136)).
- Cold boot: sidecar ready before Tidal restore and bot start ([#138](https://github.com/alfdav/music-dl/pull/138)).
- Show artist names on search tiles ([#139](https://github.com/alfdav/music-dl/pull/139)).
- Hide now-playing Download when the track is already local, and name Local vs Tidal on the now-playing bar ([#140](https://github.com/alfdav/music-dl/pull/140)).

## v1.7.5 (2026-08-16)
- Accept Blue Lossless (LOSSLESS FLAC) when Hi-Res is requested but Tidal only publishes the track at a lower lossless tier; lossy AAC is still rejected ([#128](https://github.com/alfdav/music-dl/pull/128)).
- Drive the Downloads Active list and badge from the queue snapshot so a missed SSE event no longer leaves a stale active card.
- Remove the queued Downloads card on Cancel All, including running, retrying, and paused jobs.
- Apply remaining queue counts on progress so the waiting card drops when a job is claimed, and stop cancelled jobs from being rewritten as running or retrying.
- Cancel the job immediately when a retry status cannot be written, instead of leaving it Active through backoff.

## v1.7.4 (2026-08-15)
- Restored Tidal catalog playback and downloads at LOSSLESS / FLAC by preferring the Tidal Web OAuth client, fixing the remaining provider-side failures in [#118](https://github.com/alfdav/music-dl/issues/118) and [#125](https://github.com/alfdav/music-dl/issues/125).
- Changed upgrade jobs to request the quality Tidal actually reports for each track, so CD-quality tracks can upgrade to LOSSLESS FLAC without being rejected for lacking Max quality.
- Updated the sidebar to show connected Tidal sessions in green and replace the server count with the account plan tier using the existing quality colors.
- Existing Tidal sessions created with the Android Auto client must reset their Tidal connection and complete device login again; old tokens remain capped at HIGH / AAC.

## v1.7.3 (2026-08-14)
- Fixed GUI downloads that could report success without creating a usable file, and now preserve the real failure reason across the worker, Downloads UI, and history ([#118](https://github.com/alfdav/music-dl/issues/118)).
- Enforced the selected audio quality as an exact tier and codec contract; mismatches fail before media output is created instead of silently saving lower-quality audio.
- Improved download reliability by isolating per-thread library database connections and committing successful track registration before other writers run.
- Added deterministic, explainable duplicate-album grouping with safety vetoes and persistent user review decisions.
- Fixed Home failing on duplicate tracks with unknown durations, removed an unused full-library grouping pass from Home loading, and made future Home failures visible instead of showing a false empty-library state.
- Added repository privacy checks for local hooks and protected-branch CI.

## v1.7.2 (2026-08-08)
- Fixed Reset Tidal connection in the desktop app by using its in-app confirmation dialog.
- Fixed Tidal token expiry persistence outside UTC and repaired valid affected credentials during reconnect ([#115](https://github.com/alfdav/music-dl/issues/115)).

## v1.7.1 (2026-08-05)
- Fixed local Search and Favorites playback so downloaded tracks use their local files instead of requiring a working Tidal session.
- Added clear local/Tidal source labels and made saved-but-unverified Tidal credentials display neutrally until remote playback is confirmed.
- Fixed Recently Played grouping when the server returns timestamps in seconds.
- Loaded visible artist album artwork immediately while keeping later rows lazy.
- Stopped packaged desktop sidecar descendants when music-dl quits or updates, and isolated tests from the real user library.

## v1.7.0 (2026-08-05)
- Added quality and content filters for the current cached page of Tidal album results, with independent Max, Atmos, and Explicit badges.

## v1.6.9 (2026-07-13)
- Fixed update checks incorrectly offering an older published release to newer
  local or source builds, and made the current version appear without requiring
  a manual update check.
- Added a Settings action to reset stale Tidal credentials locally without
  restarting the app or automatically starting another OAuth request.
- Removed browser-driven Tidal keepalive polling; token refresh now remains
  demand-driven before explicit Tidal-facing actions.
- Made startup and Settings account indicators use local token/expiry state
  instead of provider-backed login validation requests.
- Made Hi-Fi discovery and status checks passive, cached tracker results for 60
  seconds, and removed stale hard-coded fallback instances.
- Serialized Hi-Fi requests across clients, limited rotation to one attempt per
  host, and stopped immediately on authentication, authorization, or rate-limit
  responses.

## v1.6.8 (2026-06-05)

- Hardened upgrade queue handling by validating direct Tidal upgrade paths
  before jobs are enqueued.
- Made library database backups WAL-safe so committed scan/cache rows are
  included in the rolling `library.db.bak` disaster-recovery copy.
- Tightened download/library DB cleanup paths so connections close on mutation
  errors.
- Updated desktop updater, OAuth default behavior, Hi-Fi status probes, and
  Discord bot playback/playlist controls.
- Bumped dependency/security updates for Tauri, `tar`, `urllib3`, `idna`, and
  `starlette`.

## v1.6.7 (2026-05-12)

- Migrate older `library.db` cache schemas that are missing legacy scan columns
  instead of leaving desktop startup stuck at daemon readiness timeout.

## v1.6.5 (2026-05-09)

### Upgrade matching

- Fixed Upgrade fallback matching for tracks whose Tidal artist list includes collaborators or whose local metadata uses collaborator separators such as `feat.`, `ft.`, `featuring`, `with`, `&`, `+`, `/`, comma, or `x`.
- Kept full artist-part matching strict enough to reject shared-prefix wrong artists such as `Drake` versus `Drake Bell`.

### Release automation

- Updated GitHub Actions workflow dependencies to Node 24 runtime-compatible action majors to avoid Node 20 action deprecation warnings.

### Desktop startup recovery

- Quarantine corrupt `~/.config/music-dl/library.db` cache files as `library.db.corrupt-*` and rebuild the schema instead of leaving the desktop app stuck at daemon readiness timeout.

### Desktop updater

- Fixed disabled updater controls caused by false boolean attributes in the GUI helper.
- Open GitHub update actions through the desktop shell external-browser helper.
- Normalize desktop updater state in the GUI and report download progress while staging updates.

## v1.6.3 (2026-05-02)

### Desktop Discord bot fix

- Bundled Discord bot sources into the packaged desktop sidecar.
- Provisioned packaged bot sources into the music-dl config directory before starting the bot.
- Installed bot dependencies on first packaged bot start when `node_modules` is missing.
- Fixed the installed-app error: `Bot deploy failed: Discord bot sources not found`.

## v1.6.2 (2026-05-02)

### Desktop release automation

- Added rolling edge desktop builds from `master` for macOS, Linux, and Windows.
- Added stable release CI support for macOS DMG and updater archive assets.
- Replaced stale rolling edge assets before upload so installers do not pick old builds.
- Documented the stable-versus-edge install flow for internal release candidates.

### DJAI Discord controls

- Added GUI-owned Discord bot lifecycle controls with live PID reuse.
- Kept Discord bot setup and status in the DJAI surface instead of forcing CLI-only setup.

## v1.6.1 (2026-04-25)

### Desktop app fixes

- Replaced the DJAI placeholder with GUI controls to save Discord bot config and start, restart, or shut down the bot service from the browser.
- Hardened the DJAI Discord bot config path so bot tokens are handled as secrets and never returned by the GUI API.
- Clarified existing Discord bot configs in the DJAI view by reusing the same fields as ghost-filled saved fields so CLI-onboarded users do not have to re-enter secrets.
- Show saved non-secret Discord IDs in the DJAI bot config fields while keeping bot tokens hidden.
- Resolve Discord app, server, channel, and user names for human-readable DJAI bot config fields when Discord lookup is available.
- Use human saved-state labels instead of raw placeholder IDs when saved Discord IDs are not real snowflakes.
- Treat placeholder/non-snowflake Discord IDs as invalid so DJAI does not present broken bot configs as ready.
- Let DJAI discover valid legacy CLI `.env` bot configs when the canonical GUI config is missing or stale.
- Added an auto-refreshing DJAI Discord remote panel with search, playlist selection, playback controls, queue view, and repeat controls in the allowed channel.
- Let Discord playlist selection queue saved Tidal playlists without copying IDs and default playlist playback to repeat-all.
- Fixed packaged app startup and login handoff problems found after v1.6.0.
- Added desktop deep-link routing and playback/library quality-of-life fixes from the post-v1.6.0 release branch.
- Persisted recently played local tracks through the backend so the Home view can recover recent playback after relaunch.
- Restored local Tauri `cargo test` reliability by creating a debug-only sidecar placeholder when no packaged backend binary exists.

### Release and installer hardening

- Bumped Python and Tauri package metadata to v1.6.1.
- Hardened the macOS quick installer so it verifies the GitHub release DMG checksum before mounting.

## v1.6.0 (2026)

### Desktop app and daemon reliability

- Added Tauri-side daemon supervision so the desktop app can launch the Python backend, poll health, and report structured startup failures.
- Added daemon metadata endpoints used by the desktop shell to verify backend readiness.
- Documented the daemon runtime path and release behavior for local and packaged desktop builds.

### Download pipeline

- Added persistent download job storage for GUI-triggered work.
- Routed GUI downloads and quality upgrades through the job service instead of transient in-memory handling.
- Added job event publishing and status reads so the frontend and bot can observe real download progress.

### Discord bot

- Documented the private Discord bot command surface, setup flow, and verification commands.
- Documented the bot onboarding wizard, shared-token handoff, and `music-dl gui --setup-bot` flow.
- Clarified that `/play` queues only and `/download` is the explicit download action.

### Release and packaging

- Declared PyInstaller as an optional build extra for desktop packaging.
- Fixed the release manifest publishing job so it checks out the repository before updating release assets.

---

## v3.1.0 (2026)

### Behavior changes

- `duplicate_action` now defaults to `copy` for configs that do not already define the setting, so duplicate ISRC hits prefer copying from an existing local source instead of prompting.

### Playlist M3U generation

- Playlist downloads now always generate a UTF-8 `.m3u8` file with relative paths
- Playlist metadata preservation was tightened so album name, album artist, and artwork survive playlist downloads
- Albums and mixes still respect `playlist_create`
- Existing configs that still use the untouched legacy `- Playlists/...` default are migrated automatically to `Playlists/...` for cleaner library ingestion

### Download correctness fixes

- Fixed live playlist downloads that were saved as `.flac` even when the downloaded container was actually MP4/M4A
- Fixed re-download path handling so canonical filenames are reused instead of drifting into `_01` duplicates when the resolved stream extension changes

### Library scanning

- Added `music-dl scan`
- Added persistent `scan_paths` management through `scan add`, `scan remove`, and `scan show`
- Added `--dry-run`, `--all`, and `--verbose`
- Added ISRC extraction for FLAC, MP3, MP4/M4A, and OGG through `mutagen`
- Added Rich progress and summary output for scan runs
- Added existence checks in `scan show`

### Documentation

- README updated for the current command surface
- Docker documentation added and aligned with the renamed app
- changelog refreshed for the `music-dl` rename

---

## v3.0.0 (2025)

Full CLI rewrite based on the current Typer engine, ported from [tidal-dl-ng](https://github.com/exislow/tidal-dl-ng).

### Core

- Replaced the old CLI with a Typer-based command tree
- Added bare URL shorthand so `music-dl <URL>` works without an explicit `dl` subcommand
- Standardized the package entrypoint around the `music-dl` CLI
- Moved packaging to `pyproject.toml`
- Dropped legacy Python support and now require Python 3.12+

### Authentication

- Added browser-based OAuth login
- Added clickable fallback links when auto-launch is unavailable
- Added token persistence with automatic refresh

### Downloads

- Added `dl --list` for URL files
- Added `dl --output` for a one-off destination override
- Added `dl_fav tracks|albums|artists|videos`
- Added `dl_fav ... --since` for date-filtered favourites
- Added richer summary output after collection downloads
- Added configurable concurrency and randomized delay controls

### Duplicate handling

- Added persistent ISRC duplicate tracking across sessions
- Added duplicate actions such as `copy`, `ask`, `redownload`, and `skip`
- Added index pruning and safer duplicate-state handling

### Paths and templates

- Replaced legacy placeholder formatting with `{token}` templates
- Added multi-disc path helpers such as `{track_volume_num_optional_CD}`
- Added more metadata-aware path tokens for IDs, dates, durations, and explicit flags

### Metadata and media handling

- Expanded metadata writing across FLAC, MP3, and MP4
- Improved lyrics handling
- Improved album artist, disc number, replay gain, and URL tagging
- Added FFmpeg auto-discovery for FLAC extraction and MP4 remuxing

### Removed legacy surface

- Removed the GUI path
- Removed older setup scripts and legacy support modules that no longer matched the current architecture

---

## Legacy history

For older project history before the current rewrite, see the upstream repository:

- [yaronzz/Tidal-Media-Downloader](https://github.com/yaronzz/Tidal-Media-Downloader)
