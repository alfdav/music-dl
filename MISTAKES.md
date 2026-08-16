# Mistakes

## 2026-08-16 — Local scan indexed Synology `#recycle` as an artist

**What happened:** Artists view showed a `#recycle` heading with deleted NAS files (WAV titles like `08 Menu Groove Edit`) as if they were a real library artist.

**Root cause:** The local folder walk used `rglob("*")` with no directory-name skip. Recycle and system dirs (`#recycle`, `@eaDir`, `$RECYCLE.BIN`, `.Trash`, `lost+found`, …) were treated as music. When tags were missing, the first relative path part became the artist, so `#recycle` appeared as an artist. Duplicate scoring already penalized `#recycle` paths; the indexer did not skip them.

**Prevention:** Skip those directory names at the walk (whole component, case-insensitive). Do not match the word recycle in a track title. Drop already-indexed rows whose path contains a skipped dir so a rescan does not keep them. Hidden-dot albums stay indexed unless the name is an explicit skip.

## 2026-08-15 — Progress SSE skipped the queue counts that clear the waiting card

**What happened:** Claiming a queued job emits `progress` (and that payload already includes `queued_count`). The Active list only re-snapshotted on non-`progress` events, so the “Waiting to start…” summary stayed beside the now-running track until a later terminal or queue event.

**Root cause:** The client treated `progress` as a per-card paint and ignored the queue envelope. Separately, Cancel All marked `running`/`retrying` rows cancelled, but `_update_job` / `_mark_retrying` wrote those statuses back and broadcast `progress`, which redrew the job in Active.

**Prevention:** Apply `queued_count` / `active_count` / `paused` from progress payloads. Do not write an active job status, or emit downloading/retrying progress, after cancel has been requested or the row is already `cancelled`. If `_update_job` refuses `retrying`, `_mark_retrying` must mark cancelled and the retry loop must return — do not sleep and continue.

## 2026-08-15 — Exact quality match rejected valid Blue Lossless

**What happened:** Settings default to `HI_RES_LOSSLESS`. Tracks that Tidal only publishes as Blue Lossless failed the download gate, sat on "Waiting to start...", and could not be requeued. The Downloads badge also stayed at 1 after Clear Done / Clear All.

**Root cause:** `_require_exact_quality` required the delivered tier to equal the setting. Tidal already returns the best available stream at or below the request, so LOSSLESS FLAC was treated as a mismatch. The nav badge was a local increment/decrement that double-counted `batch_queued` and never synced from queue state, so Clear History could not hide it.

**Prevention:** Treat lossless settings as a family + ceiling. Accept FLAC `LOSSLESS`/`HI_RES`/`HI_RES_LOSSLESS` when lossless was requested; still reject AAC/HIGH. The Downloads Active list and badge are projections of `/downloads/active/snapshot` and `/downloads/queue-state`. Do not accumulate SSE cards; `batch_queued.count` is remaining queued jobs, not the last enqueue size.

## 2026-08-15 — Treated local playback as the core hello-world

**What happened:** During Cloud Agent environment setup, the first end-to-end demo indexed a synthetic local FLAC and played it in the GUI. That path works without Tidal. Catalog search, stream, and download do not.

**Root cause:** `/api/auth/status` was `not_configured` (`token.json` has null tokens). `/api/search` returns `401 Not logged in to Tidal` in that state. The UI still indexes and searches the local library, so it looks like “search works” while Tidal actions do nothing.

**Prevention:** Before claiming the product works end to end, call `GET /api/auth/status` and require `logged_in: true`. Then exercise a Tidal catalog search and a download. Local scan/playback is only a fallback when Tidal is intentionally out of scope.

## 2026-08-15 — Treated HIGH/M4A as a successful download

**What happened:** After Tidal login, `HI_RES_LOSSLESS` downloads failed with a quality mismatch. I switched `quality_audio` to `HIGH` so an M4A file landed. The user needs FLAC.

**Root cause:** This account is Hi-Res Premium (`highestSoundQuality: HI_RES`), but every OAuth client this app can use (`playbackinfopostpaywall`) still returns `HIGH` / `MP4A`. The exact-quality gate then errors, or a HIGH setting “succeeds” as lossy M4A. Public Hi-Fi API instances (the FLAC path) were all down.

**Prevention:** Do not lower quality to make a download succeed. Check subscription + raw `audioQuality`/`codecs`. FLAC requires a lossless delivery (`LOSSLESS`/`HI_RES_LOSSLESS` + `flac`), not a completed HIGH job.

## 2026-08-15 — Treated a live Tidal login as a gray "credentials saved" chip

**What happened:** After a real login, the sidebar Tidal chip stayed gray. `/api/auth/status` returns `logged_in: true` with `auth_state: credentials_ready`. The UI treated `credentials_ready` as a saved-but-offline state before the connected/green case.

**Root cause:** The presentation helper assumed `credentials_ready` meant "token on disk, session not verified." The local-only status endpoint now uses that state for a valid unexpired token.

**Prevention:** A saved unexpired token is connected. Use the default green `.connection-dot` for `logged_in` / `credentials_ready`. Keep gray only for an explicit saved-but-unverified state, which this API no longer has.
