# music-dl Backend Orientation

> Start here for backend entry points and invariants. Source and tests remain
> authoritative for exhaustive modules, routes, and schema details.

## 1. System Overview

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│  CLI (Typer) │     │ GUI (FastAPI) │     │ Tidal API     │
│  cli.py      │     │ gui/         │     │ (tidalapi)    │
└──────┬───────┘     └──────┬───────┘     └───────┬───────┘
       │                    │                     │
       └────────┬───────────┘                     │
                │                                 │
        ┌───────▼────────┐               ┌────────▼────────┐
        │  config.py     │               │  download/      │
        │  Settings()    │◄──────────────│  Download class │
        │  Tidal()       │               └────────┬────────┘
        └───────┬────────┘                        │
                │                          ┌──────▼──────┐
        ┌───────▼────────┐                 │  mutagen    │
        │ library_db/    │                 │  (tagging)  │
        │  SQLite + WAL  │                 └─────────────┘
        └────────────────┘
```

**Two local entry points, one shared core.** CLI and GUI share `Settings` and
`Tidal` singleton state. Each `LibraryDB` instance owns one SQLite connection.
The optional Discord bot calls the GUI API instead of importing backend state.

---

## 2. File Map

| File | Purpose |
|------|---------|
| `cli.py` | Typer CLI — subcommands: `gui`, `dl`, `cfg`, `login`, `logout`, `sync`, `import`, `isrc-tag`, `source`, `scan`, `dl_fav` |
| `config.py` | Singleton config: `Settings`, `Tidal`, `HandlingApp`. Token management, key rotation |
| `download/` | Download pipeline: stream fetch → segment merge → decrypt → tag → register |
| `api.py` | Authenticated tidalapi client key handling |
| `dash.py` | DASH manifest parser for `dash+xml` stream manifests |
| `hifi_api.py` | Legacy stream-source client retained for compatibility; tracker discovery is cached for 60 seconds, status checks are passive, requests are serialized, and each host is tried once per operation |
| `metadata.py` | Mutagen-based metadata writer for FLAC, MP3, and MP4 |
| `constants.py` | Enums (`DownloadSource`, `MediaType`), quality maps, chunk sizes |
| `gui/__init__.py` | FastAPI app factory: middleware stack, static files, CSRF injection |
| `gui/daemon.py` | Local daemon metadata, port selection, stale metadata cleanup, structured readiness |
| `gui/server.py` | Uvicorn launcher. Defaults to `127.0.0.1`; Docker sets `MUSIC_DL_BIND_ALL=1` for container reachability |
| `gui/security.py` | CSRF, host validation, path validation, stream URL validation, bot bearer auth, signed bot stream tokens |
| `gui/api/` | API routers. Inspect `gui/api/__init__.py` or `/api/docs` for the current complete surface |
| `gui/bot_onboarding.py` | Canonical Discord bot config paths and shared-token discovery |
| `gui/services/` | Persisted download/upgrade job lifecycle primitives and worker service |
| `helper/library_db/` | SQLite connection lifecycle, schema migrations, and focused query mixins |
| `helper/path.py` | Config paths, download path templates, filename sanitization |
| `helper/cache.py` | `TTLCache` — thread-safe in-memory cache with TTL expiry |
| `helper/library_scanner.py` | Walk directories, extract ISRC from audio tags via mutagen |
| `helper/checkpoint.py` | `DownloadCheckpoint` — resume interrupted downloads |
| `helper/tidal.py` | Tidal URL parsing, media instantiation, name formatting |
| `helper/camelot.py` | Camelot wheel notation helpers for harmonic mixing |
| `helper/cli.py` | Helper functions for CLI operations (formatting, dates) |
| `helper/decryption.py` | AES decryption for encrypted TIDAL streams |
| `helper/exceptions.py` | Custom exception classes (`LoginError`, etc.) |
| `helper/playlist_import.py` | Cross-platform playlist import (CSV/JSON) |
| `model/cfg.py` | `ModelSettings`, `ModelToken` dataclasses |
| `model/downloader.py` | Download-related data models and state |
| `model/meta.py` | Metadata dataclasses for tag writing |

---

## 3. Singletons

Three process-wide objects implement their own locked `__new__` lifecycle. Call
the class and you get the same instance.

### Settings()

```python
from tidal_dl.config import Settings
s = Settings()
s.data.download_base_path   # "~/download"
s.data.quality_audio         # "HI_RES_LOSSLESS"
s.set_option("skip_existing", True)
s.save()
```

- Loads from `~/.config/music-dl/settings.json`
- `BaseConfig` generic: tolerant deserialization (ignores unknowns, uses defaults for missing)
- Falls back to `.bak` on corruption
- `save(config_to_compare)` skips write if unchanged

### Tidal()

```python
from tidal_dl.config import Tidal
t = Tidal()
t.session              # tidalapi.Session
t.is_atmos_session     # bool
t.active_source        # DownloadSource.HIFI_API or .OAUTH
t.api_cache            # TTLCache
t.stream_lock          # Lock — serializes stream ops during Atmos switching
```

- Loads token from `~/.config/music-dl/token.json`
- `login_token()` — restore from stored token
- `login_finalize()` — persist after new login
- `_ensure_token_fresh(refresh_window_sec=300)` — auto-refresh if expiring within 5 min
- `_try_login_with_key_rotation()` — keeps authenticated tidalapi login resilient across bundled client credentials
- Token expiry handles both `float` (timestamp) and `datetime` from tidalapi
- GUI startup marks the sidecar ready after `LibraryDB.open` + migrate and `recover_download_jobs`. It then restores Tidal in the background with `resolve_source(..., allow_interactive_login=False)` and starts a configured Discord bot after ready. First-run GUI still becomes ready for the user-initiated Connect Tidal flow instead of opening OAuth during lifespan startup. Hi-Fi, gist, and quality-probe calls used by restore are capped at `SOURCE_RESOLVE_TIMEOUT_SEC` (2s) so a dead network cannot eat the 30s Tauri spinner.
- `_probe_subscription_quality()` reports observed provider capability only. Lower or unknown delivery warns; it never mutates or persists configured/session quality.

### HandlingApp()

- Owns `abort` and `run` events for graceful shutdown
- Used by CLI download loops to check for Ctrl+C

---

## 4. Daemon Runtime

`gui/daemon.py` owns local daemon metadata, port selection, stale metadata cleanup,
and structured readiness. The canonical runtime file is
`~/.config/music-dl/daemon.json`.

Only one daemon is canonical per user config directory. Browser mode and the
Tauri sidecar both discover that daemon through `daemon.json` and confirm
readiness through `/api/server/health`.

`daemon.json` includes `base_url`, `health_url`, `pid`, `mode`, and `status`.
Tauri never assumes port `8765`; it reuses a ready browser or sidecar daemon
when the metadata health check passes, otherwise it starts its own sidecar and
waits for healthy metadata from the spawned process or the PyInstaller worker
child that publishes daemon readiness.

The desktop shell also handles `music-dl://` deep links. It parses the launch
URL into the same hash-route shapes used by the browser UI, waits for the
daemon to be ready, then navigates the Tauri webview to that route. Mounting or
installing the macOS DMG does not start the daemon; the daemon starts only when
the user launches `music-dl.app` or runs `music-dl gui`.

The daemon opens `~/.config/music-dl/library.db` during startup for persisted
download and upgrade jobs. If SQLite reports the cache file is corrupt, the app
renames it to `library.db.corrupt-*`, moves matching WAL/SHM sidecars with it,
and creates a fresh schema so the desktop shell can still reach readiness.

---

## 5. Middleware Stack

Middleware executes in **reverse registration order** — last added runs first.

```python
# gui/__init__.py — registration order
app.add_middleware(HostValidationMiddleware, ...)    # 1st registered → runs last
app.add_middleware(CSRFMiddleware, ...)               # 2nd
app.add_middleware(CORSMiddleware, ...)               # 3rd
app.add_middleware(TokenRefreshMiddleware)             # 4th registered → runs first
```

**Execution order per request:**

| Order | Middleware | What it does |
|-------|-----------|-------------|
| 1 | `TokenRefreshMiddleware` | Calls `Tidal()._ensure_token_fresh()` on Tidal-facing paths (`/api/search`, `/api/download`, `/api/playlists`). Fails silently. |
| 2 | `CORSMiddleware` | Allows `http://localhost:{port}` and `http://127.0.0.1:{port}` only |
| 3 | `CSRFMiddleware` | Validates `X-CSRF-Token` header on POST/PATCH/DELETE. Uses `secrets.compare_digest()`. Exempts GET/HEAD/OPTIONS. |
| 4 | `HostValidationMiddleware` | Rejects requests with Host header not in `{localhost, 127.0.0.1}:{port}`. DNS rebinding defense. |

---

## 6. Security Model

All security logic in `gui/security.py`.

### CSRF

- Token: 32-byte URL-safe random, generated at server startup
- Injected into `index.html` via `<meta name="csrf-token" content="__CSRF_TOKEN__">` replacement
- Frontend sends as `X-CSRF-Token` header on all mutations
- Timing-safe comparison via `secrets.compare_digest()`
- `/api/bot/*` is exempt from browser CSRF and instead requires bearer auth.

### Host Validation

Whitelist: `localhost:{port}`, `127.0.0.1:{port}`, bare `localhost`, bare `127.0.0.1`. Everything else → 403.

### Path Validation

| Function | Purpose | Rules |
|----------|---------|-------|
| `validate_audio_path(path)` | Playback requests | Resolves symlinks, checks file exists, extension in `AUDIO_EXTENSIONS` |
| `validate_download_path(path)` | Settings/wizard | Rejects `FORBIDDEN_PATHS` (`/etc`, `/usr`, `/System`, `~/.ssh`, `~/.gnupg`, `~/.config`, etc.) |
| `validate_stream_url(url)` | Download proxy | HTTPS only, host must be `*.tidal.com` — prevents SSRF |

GUI file endpoints keep CodeQL `py/path-injection` suppressions next to validated
filesystem calls. Those suppressions are only valid when the path came from
`validate_audio_path` or `validate_download_path`.

### Constants

```python
AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac", ".wma"}
FORBIDDEN_PATHS  = {"/etc", "/usr", "/bin", "/sbin", "/var", "/System", ...}
TIDAL_CDN_HOSTS  = {"audio.tidal.com", "sp-ad-cf.audio.tidal.com", ...}
```

### Discord Bot Auth

- Bot endpoints live under `/api/bot/*`.
- Every route requires `Authorization: Bearer <shared-token>`.
- Token resolution order: non-empty `MUSIC_DL_BOT_TOKEN`, then the wizard-written `bot-shared-token` file.
- `POST /api/bot/playable` returns a short-lived signed stream handle; it does not expose raw filesystem paths or raw Tidal stream URLs.

---

## 7. Database Schema

SQLite at `~/.config/music-dl/library.db`. Schema version 9, WAL mode, and a
5-second busy timeout.

### Tables

**`scanned`** — local file metadata cache

| Column | Type | Notes |
|--------|------|-------|
| `path` | TEXT PK | Absolute file path |
| `isrc` | TEXT | For cross-context dedup |
| `status` | TEXT NOT NULL | `tagged`, `needs_isrc`, `unreadable` |
| `artist` | TEXT | |
| `title` | TEXT | |
| `album` | TEXT | |
| `album_artist` | TEXT | Embedded album artist used for release grouping |
| `release_date` | TEXT | Embedded release date or year |
| `track_number`, `track_total` | INTEGER | Embedded track position and trusted release total |
| `disc_number`, `disc_total` | INTEGER | Embedded disc position and trusted release total |
| `musicbrainz_release_id` | TEXT | Embedded MusicBrainz Release identity |
| `musicbrainz_release_group_id` | TEXT | Embedded MusicBrainz Release Group identity |
| `provider_namespace`, `provider_album_id` | TEXT | Embedded source identity such as `tidal` plus album ID |
| `barcode` | TEXT | Embedded UPC, EAN, or barcode |
| `duration` | INTEGER | Seconds |
| `quality` | TEXT | `HI_RES_LOSSLESS`, `LOSSLESS`, etc. |
| `format` | TEXT | `FLAC`, `MP3`, etc. |
| `codec` | TEXT | Normalized inspected codec: `aac`, `alac`, `flac`, `mp3`, `ogg`, `opus`, `vorbis`, `pcm`, or `unknown` |
| `metadata_complete` | INTEGER | `1` after scan-time metadata resolution has run; `NULL`/`0` marks a legacy row needing one repair pass |
| `play_count` | INTEGER | Default 0 |
| `last_played` | INTEGER | Unix timestamp |
| `genre` | TEXT | |
| `waveform` | TEXT | Cached standard-resolution waveform JSON |
| `waveform_hires` | TEXT | Cached high-resolution waveform JSON |
| `art_available` | INTEGER | Local artwork availability; `NULL` until checked |
| `release_id` | TEXT | Current grouped release card id; stamped during album-card builds. NULL after v9 migrate until a full regroup or a scoped card build writes it. A stamp miss recovers with one full regroup, then later lookups stay index-only. The albums gallery (`GET /library/albums`) uses these stamps when complete and must not regroup the whole library on every paint. |
| `scanned_at` | INTEGER | Unix timestamp |

Indexes: `idx_scanned_status`, `idx_scanned_isrc`, `idx_scanned_release_id`

**`album_grouping_assessments`** — explainable release-card decisions

| Column | Type | Notes |
|--------|------|-------|
| `pair_key` | TEXT PK | SHA-256 over the sorted current group signatures |
| `left_signature`, `right_signature` | TEXT | Versioned local group identities |
| `score`, `outcome` | INTEGER, TEXT | Current rubric result |
| `evidence_json`, `vetoes_json`, `contradictions_json` | TEXT | Explainable assessment payloads |
| `user_decision`, `canonical_title` | TEXT | Optional current local choice |
| `catalog_json` | TEXT | Independent TIDAL/MusicBrainz attempt and result state |
| `evaluated_at` | REAL | Unix timestamp |

The album API groups only complete accepted cliques. Review and rejected pairs stay as separate cards. Optional catalog work runs after scanning; TIDAL is used only with existing credentials and MusicBrainz requests use an identifying User-Agent with a process-wide one-request-per-second limit.

**`play_events`** — time-series for activity charts

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `path` | TEXT | |
| `artist` | TEXT | |
| `genre` | TEXT | |
| `duration` | INTEGER | |
| `played_at` | INTEGER | Unix timestamp |

Index: `idx_play_events_at`

**`download_history`** — completed/failed downloads

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `track_id` | INTEGER | Tidal track ID |
| `name` | TEXT | Track title |
| `artist` | TEXT | |
| `album` | TEXT | |
| `status` | TEXT NOT NULL | `completed`, `failed` |
| `error` | TEXT | Error message if failed |
| `started_at` | REAL | |
| `finished_at` | REAL | |
| `cover_url` | TEXT | Album art URL |
| `quality` | TEXT | Download quality |

**`download_jobs`** — persisted queue for normal downloads and quality upgrades

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment job ID |
| `kind` | TEXT NOT NULL | `download` or `upgrade` |
| `status` | TEXT NOT NULL | `queued`, `running`, `indexing`, `retrying`, `paused`, `done`, `error`, `cancelled`, `interrupted` |
| `track_id` | INTEGER NOT NULL | Tidal track ID |
| `name` | TEXT | Display title |
| `artist` | TEXT | Display artist |
| `album` | TEXT | Display album |
| `cover_url` | TEXT | Album art URL |
| `quality` | TEXT | Requested or resolved quality |
| `progress` | REAL | Percent progress, default `0` |
| `error` | TEXT | Terminal error message |
| `old_path` | TEXT | Upgrade source path |
| `new_path` | TEXT | Upgrade replacement path |
| `metadata_json` | TEXT | Narrow upgrade execution context |
| `created_at` | REAL NOT NULL | Unix timestamp |
| `started_at` | REAL | Unix timestamp |
| `finished_at` | REAL | Unix timestamp |

Indexes: `idx_download_jobs_status_created`, `idx_download_jobs_track_id`

Job creation uses an atomic `BEGIN IMMEDIATE` transaction so two requests cannot enqueue active duplicate work for the same `track_id`. Queue claiming also uses `BEGIN IMMEDIATE` and updates only a still-queued row before returning it to the worker. Every `BEGIN IMMEDIATE` site goes through `LibraryDB.write_transaction(immediate=True)`, which holds a per-database process lock for that short SQL burst. A transient lock is retried *outside* that process lock with a 50ms acquire timeout so a foreign reserved writer cannot pin every other writer behind the 5s `busy_timeout`. The download worker treats a remaining lock error as a deferred claim and keeps running; it does not die.

Startup recovery rule: queued jobs stay queued. `running`, `indexing`, `retrying`, and `paused` jobs become `interrupted`. Terminal jobs stay terminal.

Pause rule: global queue pause does not rewrite queued backlog rows to `paused`; queued jobs remain `queued` so they can resume after restart.

FastAPI lifespan creates `DownloadJobService`, stores it on `app.state.download_jobs`, registers the service event hub with the running event loop, starts the persisted-job worker after recovery commits, and stops that worker during lifespan shutdown. Tests pass `job_db_path` to `create_app()` so API smoke tests use an isolated temporary job database instead of the user's real `library.db`.

**Boot-path rule:** mark `ready` / health 200 after migrate + `recover_download_jobs`. Restore Tidal and start the Discord bot after ready. Never group albums, walk `scan_new_downloads`, or start a library scan during lifespan. The worker must not claim a job before recovery commits.

Lifespan constructs `Tidal(Settings())` after ready and uses `resolve_source(..., allow_interactive_login=False)` on a background thread. This preserves the existing Hi-Fi selection and fallback policy while preventing a browser OAuth flow or a hung Hi-Fi/gist/quality probe from blocking server readiness. Failed restore surfaces the existing auth status; it does not fake a signed-in session.

Normal downloads, playlist sync, bot download requests, and upgrade requests all enqueue through `DownloadJobService`, so active duplicate suppression is shared across job kinds and enforced by the `download_jobs` table instead of route-local in-memory state. The worker claims both normal download jobs and upgrade jobs. Upgrade cleanup, quality ranking, album resolution, and trash helpers live in `tidal_dl.gui.services.upgrade_jobs`; route modules do not own download or upgrade execution.

**`favorites`** — user-starred tracks

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `path` | TEXT | Local file path (if owned) |
| `tidal_id` | INTEGER | Tidal track ID (if from search) |
| `artist` | TEXT | |
| `title` | TEXT | |
| `album` | TEXT | |
| `isrc` | TEXT | Recording identifier |
| `cover_url` | TEXT | Artwork URL |
| `favorited_at` | INTEGER NOT NULL | Unix timestamp |

**Caches:**

| Table | PK | Cached Data | TTL field |
|-------|----|------------|-----------|
| `artist_images` | `artist` | Tidal artist photo URLs | `fetched_at` |
| `playlist_covers` | `playlist_id` | Tidal playlist cover URLs | `fetched_at` |
| `quality_probes` | `isrc` | Tidal max quality per ISRC | `probed_at` |
| `library_meta` | `key` | Scan fingerprints, app state | — |

### Migrations

Additive only. `open()` reads SQLite's native `PRAGMA user_version`: databases below version 9 run these migrations and record version 9 in the same commit; current-schema opens configure their existing pragmas without rerunning migration writes.

1. **v1 → v2**: Add `album`, `duration`, `quality`, `format` columns to `scanned`
2. **v2 → v3**: Add `play_count`, `last_played`, `genre` to `scanned`
3. **v3 → v4**: Add `waveform` and `waveform_hires` to `scanned`
4. **v4 → v5**: Add `art_available` to `scanned`
5. **v5 → v6**: Add `codec` and `metadata_complete` to `scanned`; backfill unambiguous native codecs and repair remaining legacy rows on the next scan
6. **v6 → v7**: Add nullable release identity, position, and total fields to `scanned`; queue existing readable rows for one metadata repair pass
7. **v7 → v8**: Add `album_grouping_assessments` for explainable scores, catalog state, and current user choices
8. **v8 → v9**: Add `release_id` on `scanned` so one-artist/one-release reads and the albums gallery can load those rows without regrouping the whole library
9. **Late additions**: Add `cover_url` and `quality` to `download_history`
10. **Download jobs and favorites**: Create their tables and lookup indexes when absent

Pattern: check `PRAGMA table_info()`, `ALTER TABLE ADD COLUMN` if missing. Never destructive.

### Local scan facts

The scanner is the authority for local display metadata and quality. Codec, not container extension or decoded bit depth, decides whether a local file is lossy or lossless. `M4A` may contain AAC or ALAC, so an uninspected M4A remains Unknown.

Library cache rows are not deleted until a scan traversal succeeds. Do not clear, age, or prune `scanned` rows at scan start. Mark-and-sweep skipped trash paths (`#recycle`, `.Trash`, and the shared skip list in `library_scanner.py`) and missing files only after a complete walk. An interrupted or failed scan must leave the previous good cache intact. Stage metadata outside a writer transaction and commit short batches; never hold a writer lock across filesystem walks or tag reads. Scan status must expose a named `phase` and increment `scanned` during discovery so the UI cannot sit on `scanned:0,total:0` with no explanation. Do not mutagen already-tagged rows that already have a real artist/title/album — a leftover `metadata_complete=0` from a schema migration is not a reason to re-read thousands of NAS files. Discover/walk first; leftover repair is a cheap DB filter plus placeholder rows only. Never open skipped-directory paths for repair.

Metadata resolution order is meaningful embedded tag, then a conservative path fallback relative to a configured root, then Unknown. Path fallback requires `artist/album/file`; it may strip an `<artist> - ` album-folder prefix and replace generic titles such as `Track 05` with a meaningful filename. The same pass reads release identity from Vorbis comments, ID3 frames, and MP4 atoms. Missing release fields stay null. Resolution updates only `library.db` and never writes audio files.

### Connection Patterns

**LibraryDB class** (`helper/library_db/`):
```python
db = LibraryDB(path)
db.open()                    # PRAGMA journal_mode=WAL, busy_timeout=5000
db.upsert_track(...)         # INSERT OR REPLACE
db.commit()
db.close()

# Writers: compute first, then one short transaction. Never hold the
# reserved lock across grouping, filesystem/network I/O, or callbacks.
with db.write_transaction(immediate=True):
    db.save_grouping_assessment(...)
    db.stamp_release_ids(cards)
```

API routes, the background scanner, album enrichment, and `DownloadJobService` each open their own connection. WAL readers stay concurrent. Writers serialize at `write_transaction` / `begin_immediate`, not by sharing one connection across threads. Lock retries release the process lock before sleeping.

**GUI singleton** (`gui/api/library.py`):
```python
_db: LibraryDB | None = None
_db_opened_at: float = 0
_DB_MAX_AGE = 300            # Force reconnect every 5 min

def _get_db() -> LibraryDB:
    # Reopens if stale (NAS mounts can drop)
    # Reopens if connection lost
```

---

## 8. Download Pipeline

### End-to-End Flow

```
POST /api/download {track_ids: [123, 456]}
  │
  ├─ DownloadJobService.enqueue_download()
  ├─ Create `download_jobs` rows with status "queued"
  ├─ Broadcast SSE: {"type": "batch_queued", ...}
  ├─ Worker thread claims oldest queued job atomically
  │
  │  [DownloadJobService worker]
  │  For each claimed job:
  │    ├─ Check cancellation at safe checkpoints
  │    ├─ Fetch track metadata from Tidal
  │    ├─ Update job display fields
  │    ├─ Broadcast SSE: {"type": "progress", "status": "downloading"}
  │    ├─ Get stream manifest through the authenticated Tidal session
  │    ├─ Treat explicit Dolby Atmos as separate opt-in lossy spatial audio using EC-3/EAC3, not an ordinary lossless tier
  │    ├─ Require delivered audio to stay in the selected family: lossless settings accept any FLAC `LOSSLESS`/`HI_RES`/`HI_RES_LOSSLESS` fallback, lossy settings stay exact
  │    ├─ If the track is listed Hi-Res and the setting is Hi-Res, do not keep a 16-bit/44.1 OAuth delivery when Hi-Fi can still supply Hi-Res
  │    ├─ Require AAC/MP4A for lossy tiers or FLAC for lossless tiers
  │    │  └─ Mismatch → error with requested/delivered/codec; URLs never reach segment consumers, and no bytes or output file
  │    ├─ Download segments (parallel, up to N)
  │    ├─ Merge segments → single file
  │    ├─ Decrypt if encrypted
  │    ├─ Write metadata via mutagen (tags, cover, lyrics)
  │    ├─ Use the calling download thread's LibraryDB connection for ISRC lookup/registration
  │    ├─ Commit successful track ISRC before any second LibraryDB writer
  │    ├─ Gate on `DownloadOutcome`
  │    │  ├─ `FAILED` → existing error path; never record completion
  │    │  └─ `DOWNLOADED`, `COPIED`, `SKIPPED` → index, then terminal success:
  │    │     ├─ Mark job "indexing" and broadcast progress status "indexing"
  │    │     ├─ Index the completed file path(s) into LibraryDB
  │    │     │  (no full-library `rglob`; fallback walks prune skipped trash dirs)
  │    │     ├─ Record in download_history
  │    │     ├─ Mark job "done"
  │    │     └─ Broadcast SSE: {"type": "complete", "status": "done"}
  │
  │  On error:
  │    ├─ Log the terminal reason once
  │    ├─ Record error in download_history (nested try/except — never breaks broadcast)
  │    ├─ Mark job "error"
  │    └─ Broadcast SSE: {"type": "error", "message": "..."}
```

Upgrade jobs follow the same persisted lifecycle. `/api/upgrade/start` writes `kind='upgrade'` jobs with `old_path` and target quality, the worker downloads with `duplicate_action_override='redownload'`, applies the artist-mismatch safety gate before cleanup, removes stale same-album copies through `upgrade_jobs.cleanup_replaced_track_files()`, records `new_path`, and broadcasts `complete` plus `upgrade_complete`.

The worker lazy-loads Tidal config/download dependencies only when it actually executes a claimed job. That keeps API startup and service tests from triggering network-backed API-key refresh work.

The failed-history renderer shows the stored terminal reason beside `Failed` and Retry; legacy empty-error rows retain those controls without an invented reason. Each terminal worker error is logged once before it is persisted, so the same reason is available in logs, SSE, job state, history, and the card.

### SSE Broadcasting

- Client connects: `GET /api/downloads/active` → `text/event-stream`
- `DownloadJobService.events` owns the `JobEventHub`
- Max 5 simultaneous clients by default
- Each client gets an `asyncio.Queue`
- On connect, `DownloadJobService.initial_events()` emits running job `progress` events and one `batch_queued` summary whose `count` is the remaining queued jobs
- Queue events (`batch_queued`, `queue_paused`, `queue_resumed`, `queue_cancelled`) include `queued_count`, `active_count`, and `paused`
- Claim/retry `progress` events use the same `_queue_event` envelope so they carry fresh `queued_count` / `active_count` / `paused`. The client applies those counts immediately; it does not wait for a later non-progress event to drop the “Waiting to start…” card
- `_update_job` and `_mark_retrying` refuse to write `queued` / `running` / `indexing` / `retrying` / `paused` after cancel, so a later metadata or retry update cannot resurrect a Cancel All’d job. After indexing, the worker also refuses terminal `done` if cancel was requested or the row is already `cancelled`.
- If `_mark_retrying` cannot write `retrying`, it marks the job cancelled and returns false so the retry loop exits instead of sleeping through backoff
- The Downloads Active list is a snapshot of `/downloads/active/snapshot` plus `/downloads/queue-state`, not an accumulation of SSE cards
- Worker/service broadcasts push events through the hub; disconnect unsubscribes the queue
- Route modules do not keep their own download SSE client lists or in-memory active-download maps

### Rate Limiting

- On HTTP 429 from Tidal: exponential backoff (double delay, capped at 30s)
- After 50 consecutive successes: halve delay back toward baseline
- Per-session, not persisted

### Checkpoint / Resume

`DownloadCheckpoint` (in `helper/checkpoint.py`):
- Tracks per-track status: `pending` → `downloaded` | `failed`
- Persisted as JSON in temp directory
- On resume: skips already-completed tracks
- Thread-safe (lock-protected)
- Auto-cleanup on complete success

### Stream Access

User-facing docs and support should assume authenticated Tidal account access
only. Legacy alternate stream-source code may still exist for compatibility or
migration, but it is not a public product path and should not be advertised.

---

## 9. API Routes

All API routes are prefixed `/api`. This section lists primary product routes;
use FastAPI's `/api/docs` or `gui/api/__init__.py` for the complete current set.

### Core

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/setup/status` | Wizard trigger: `{logged_in, scan_paths_configured, setup_complete}` |
| `POST` | `/setup/validate-path` | Check if path is safe and writable |
| `GET` | `/settings` | Current settings as JSON |
| `PATCH` | `/settings` | Update settings |
| `GET` | `/auth/status` | Report connected, expired, unavailable, or not-configured state from local token data, including cached `account_quality` |
| `GET` | `/auth/account` | Refresh the cached Tidal account quality from the provider |
| `POST` | `/auth/login` | Start OAuth device-code flow |
| `GET` | `/auth/login/status` | Poll login progress |
| `POST` | `/auth/reset` | Delete local OAuth credentials and rebuild an unauthenticated session without contacting Tidal |

### Library

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/library` | Paginated local tracks, grouped by artist |
| `GET` | `/library/albums` | Full local album gallery from stamped release ids |
| `GET` | `/library/recent-albums` | First page of recently added releases |
| `POST` | `/library/scan` | Trigger background library scan |
| `GET` | `/library/scan/status` | Poll scan progress: `{scanning, scanned, total, done, phase, error}`. `phase` is `idle`, `preparing`, `repairing`, `discovering`, `indexing`, `sweeping`, `finalizing`, `done`, or `error`. During discovery `total` may be 0 while `scanned` increments. |

Home statistics use the aggregate database queries behind `GET /home`; grouped
album cards are built only by album-library routes, not during Home loading.
The Home client paints one `.home-wrap` in the view container. After `/home`
returns it adds at most one Continue Listening `.continue-card` from
`playerPosition` plus the current queue, then at most one
`.home-recent-section`. A second `renderHome` — including an overlapping
paint while a delayed `/home` is still in flight, or `volume_available:
false` after an unmounted `/music` volume — replaces those nodes; it must
not append a duplicate. The offline banner ("Your music drive is offline —
showing what we remember") plus one resume tile is correct; two resume
tiles is not. Footer `#now-playing` is the real Now Playing chrome and is
separate from the Home resume tile. `GET /home/recent` may resolve after
first paint; that path must reuse the same recent strip, not stack a
second one. First `/home` still must not `Path.is_dir()`/`stat` the NAS
on the ready path; the client must survive a slow or retried `/home`
without stacking tiles.

Home data tiles (genre, listening time, tracks, albums) open a local insight
fan from the already-loaded `/home` payload on `_homeData`. That overlay does
not call `/home` again, does not enable `extras=True`, and does not send play
history anywhere. `recent_albums` is extras-only and omitted from first paint;
the fan skips that card when the field is missing. Artist tiles still navigate
to `artist:` and are not an insight target. `_closeHomeInsightFan()` runs at
the start of `navigate(view, opts)` so a sidebar `{ jump: true }` dismisses
the overlay without replacing the nav stack.

`GET /library/albums` returns the full gallery. When every readable album
row already has a `release_id`, cards come from those stamp groups plus
stored `album_grouping_assessments` (possible_duplicate, review payloads,
members, Various Artists, cover URLs). It does not call `all_tracks()` or
`find_candidates` on the whole library, and it does not use a per-album
cover-art subquery. After v9 migrate, stamps are NULL: one full regroup
writes every stamp, then later paints stay on the stamp path. A grouping
decision restamps only that pair.

`GET /library/recent-albums` pages album recency in SQL (scan vs download,
Various Artists when a title has multiple artists) without a per-album
cover-art subquery. Cards are grouped from the current page titles plus any
already-stamped release members, so warmed IDs match a prior full or
artist-scoped stamp. It does not expand to every album by the page artists
and does not run full-library combinations. Cover URLs come from that page
subset. Review-pair badges appear when the sibling title is on the page or
already shares a stamp.

### Search & Download

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/search` | Search Tidal catalog, cross-ref local ISRCs |
| `POST` | `/download` | Queue track downloads |
| `GET` | `/downloads/active` | SSE stream for progress |
| `GET` | `/downloads/active/snapshot` | Current active jobs and queued count |
| `GET` | `/downloads/history` | Past downloads |
| `DELETE` | `/downloads/history` | Clear history |

Artist, album, and playlist search cards reuse `.album-card` / `.album-card-meta` /
`.album-card-title`. The API already sends `name`; the legend must stay visible
under the photo. Do not let `.album-card { overflow: hidden }` plus a sibling
`div.album-card-art { height: 100% }` clip the caption. Scope cover-fill
(`height: 100%; object-fit: cover`) to `img` inside `.album-card-art-wrap`, keep
art `aspect-ratio: 1`, and use `align-items: start` on `.album-grid` /
`.album-gallery`. Tidal search `img` alt is the item name.

### Playback

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/playback/local` | Stream a local audio file to browser |
| `GET` | `/playback/stream/{track_id}` | Proxy a Tidal stream to browser |
| `GET` | `/playback/bot-stream/{token}` | Stream a signed bot playback handle |
| `GET` | `/playback/waveform` | Return cached or generated waveform peaks |
| `POST` | `/home/play` | Record play event |

`GET /hifi/status` reports tracker-advertised streaming instances. It never
fetches a track as a health probe. An empty tracker result remains empty rather
than activating stale hard-coded fallback hosts.

### Collections

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/playlists` | Tidal playlists with local match info |
| `GET` | `/albums/{album_id}/tracks` | Album detail with track list |
| `GET` | `/albums/lookup` | Resolve album metadata by artist and album name. Marks `is_local` plus `path` / `local_path` from album-scoped title+artist on that release's library files, not ISRC |
| `GET` | `/home` | Dashboard stats (top artists, genres, play counts) |
| `GET` | `/duplicates/preview` | Find ISRC-based duplicates |
| `POST` | `/duplicates/clean` | Remove duplicate files |
| `GET` | `/upgrade/scan` | Find tracks upgradable to higher quality |
| `POST` | `/upgrade/start` | Queue upgrade jobs through the persisted job service |
| `GET` | `/lyrics/local` | Read sidecar or embedded lyrics for an allowed local file |
| `GET` | `/lyrics` | Now-playing lyrics: local sidecar/tags first, then Tidal `track.lyrics()` |
| `POST` | `/lyrics/save` | Write a sidecar `.lrc` next to a local file from the current panel payload |

### Bot

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/bot/play/resolve` | Resolve a Tidal track URL, Tidal playlist URL, local playlist name, or search text |
| `POST` | `/bot/playable` | Convert a resolved item ID into a signed playable URL |
| `POST` | `/bot/download` | Start an explicit download job for one resolved item |
| `GET` | `/bot/downloads/{job_id}` | Poll bot-triggered download status |

---

## 10. Config System

### File Locations

| File | `MUSIC_DL_CONFIG_DIR` | Default |
|------|-----------------------|---------|
| `settings.json` | `$MUSIC_DL_CONFIG_DIR/settings.json` | `~/.config/music-dl/settings.json` |
| `token.json` | `$MUSIC_DL_CONFIG_DIR/token.json` | `~/.config/music-dl/token.json` |
| `library.db` | `$MUSIC_DL_CONFIG_DIR/library.db` | `~/.config/music-dl/library.db` |
| `discord-bot.env` | `$MUSIC_DL_BOT_ENV_PATH` or config dir | `~/.config/music-dl/discord-bot.env` |
| `bot-shared-token` | `$MUSIC_DL_BOT_TOKEN_PATH` or config dir | `~/.config/music-dl/bot-shared-token` |

`MUSIC_DL_CONFIG_DIR` is checked first in `path_config_base()`. Docker sets it
to `/home/musicdl/.config/music-dl`.

### BaseConfig Pattern

```python
class BaseConfig(Generic[ConfigModelT]):
    data: ConfigModelT          # Current config state
    file_path: str              # Path to JSON file

    def save(config_to_compare)  # Skip write if unchanged
    def read(path)               # Load from JSON, fallback to .bak on corruption
    def set_option(key, value)   # Type coercion, auto-save
```

### Key Settings

| Setting | Type | Default | Notes |
|---------|------|---------|-------|
| `download_base_path` | str | `~/download` | Where files go |
| `scan_paths` | str | `""` | Comma-separated library roots |
| `quality_audio` | str | `HI_RES_LOSSLESS` | Preferred quality |
| `skip_existing` | bool | `true` | Skip if file exists at path |
| `skip_duplicate_isrc` | bool | `true` | Skip if ISRC already in library |
| `downloads_simultaneous_per_track_max` | int | `20` | Parallel segment downloads |
| `format_album` | str | template | Download path template for albums |
| `format_track` | str | template | Download path template for tracks |

---

## 11. Thread Safety

| Resource | Guard | Pattern |
|----------|-------|---------|
| JobEventHub client list | `threading.Lock` | Acquired on add/remove/iterate |
| Rate limit counters | `threading.Lock` | Acquired on backoff decisions |
| LibraryDB | WAL readers + `write_transaction` / `begin_immediate` | Concurrent reads; short reserved writes; per-db lock; bounded lock retry |
| TTLCache | `threading.Lock` | Acquired on get/set/invalidate |
| DownloadCheckpoint | `threading.Lock` | Acquired on status read/write |
| Tidal stream ops | `Tidal.stream_lock` | Serializes Atmos session switching |

---

## 12. Error Handling Patterns

### Download Errors

```python
# Broadcast ALWAYS fires, even if DB write fails
try:
    db.record_download(track_id, status="failed", error=str(e))
    db.commit()
except Exception:
    logger.exception("Failed to persist download error for track %s", tid)
_broadcast({"type": "error", ...})  # Outside the nested try — always runs
```

### Token Refresh Errors

```python
# TokenRefreshMiddleware — fail silently, let the actual request surface the 401
try:
    Tidal()._ensure_token_fresh()
except Exception:
    pass  # Request proceeds; if token is actually dead, the route will 401
```

### Config Corruption

```python
# BaseConfig.read() — fall back to .bak on corruption
try:
    data = json.loads(path.read_text())
except (json.JSONDecodeError, KeyError):
    bak = Path(str(path) + ".bak")
    if bak.exists():
        data = json.loads(bak.read_text())  # Try backup
```

### NAS Resilience

- DB reconnects every 5 minutes (`_DB_MAX_AGE = 300`)
- Duplicates endpoints run in `asyncio.to_thread()` so `os.path.exists()` on NAS doesn't block the event loop
- `busy_timeout=5000` is a last-resort wait, not a license to hold the writer lock. Grouping, scans, and post-download indexing compute first, then persist. The worker retries a transient lock instead of exiting.

---

## 13. Sacred Rules

1. **Singletons are the API.** `Settings()`, `Tidal()`, `HandlingApp()` — call the class, get the instance. No dependency injection, no factories.
2. **SQLite is the cache, not the source.** The filesystem is truth. The DB is a fast index over it. If the DB is lost, a scan rebuilds it.
3. **Downloads never fail silently.** Every error broadcasts via SSE and logs. DB persistence failure must not prevent the broadcast.
4. **Token refresh is opportunistic.** Middleware checks local expiry before explicit Tidal-facing requests. The browser does not run a background keepalive, and failure is not fatal — the request will surface the real error.
5. **Localhost request boundary.** Browser mode binds `127.0.0.1`. Docker binds
   the container listener to `0.0.0.0`, but Host and CORS validation still
   accept localhost origins only; direct LAN use is unsupported.
6. **Migrations are additive.** `ALTER TABLE ADD COLUMN`. Never drop, rename, or restructure. Schema grows forward.
7. **Config corruption is recoverable.** `.bak` fallback, tolerant deserialization, defaults for missing fields.
8. **NAS mounts are unreliable.** Reconnect on staleness, run I/O off the event loop, use WAL + short write transactions. Do not hold the SQLite writer lock across grouping, scans, or downloads; `busy_timeout` is only a last-resort wait.
9. **Audio path is sacred.** No Web Audio API, no signal processing. Files stream bit-perfect from disk to browser `<audio>` element.
10. **Rate limits are respected.** Exponential backoff on 429, recovery on sustained success. Never retry immediately.
11. **Library cache rows survive until a scan traversal succeeds.** Do not clear, age, or prune `scanned` rows at scan start. Sweep skipped or stale paths only after a complete walk. Interrupted or failed scans leave the previous good cache intact. Do not hold a writer transaction across filesystem walks or tag reads. Scan status must expose a named phase and increment `scanned` during discovery. Do not re-read tags for already-tagged rows with real identity; walk before leftover placeholder repair.
