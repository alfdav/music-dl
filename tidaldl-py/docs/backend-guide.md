# music-dl Backend Reference

> Single source of truth for backend architecture. Every module, pattern, and data flow lives here.
> If it's not in this document, it's not a decision — it's a bug.

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
        │  config.py     │               │  download.py    │
        │  Settings()    │◄──────────────│  Download class │
        │  Tidal()       │               └────────┬────────┘
        └───────┬────────┘                        │
                │                          ┌──────▼──────┐
        ┌───────▼────────┐                 │  mutagen    │
        │  library_db.py │                 │  (tagging)  │
        │  SQLite + WAL  │                 └─────────────┘
        └────────────────┘
```

**Three entry points, one shared core.** CLI and GUI both use the same `Settings`, `Tidal`, and `LibraryDB` singletons. The download pipeline is identical regardless of entry point.

---

## 2. File Map

| File | Purpose |
|------|---------|
| `cli.py` | Typer CLI — subcommands: `gui`, `dl`, `cfg`, `login`, `logout`, `sync`, `import`, `isrc-tag` |
| `config.py` | Singleton config: `Settings`, `Tidal`, `HandlingApp`. Token management, key rotation |
| `download.py` | Download orchestrator: stream fetch → segment merge → decrypt → tag → register |
| `api.py` | TIDAL API key management with remote gist fallback |
| `dash.py` | DASH manifest parser for `dash+xml` stream manifests |
| `hifi_api.py` | Hi-Fi API client for direct stream access (non-OAuth path) |
| `metadata.py` | Mutagen-based metadata writer for FLAC, MP3, and MP4 |
| `constants.py` | Enums (`DownloadSource`, `MediaType`), quality maps, API keys, chunk sizes |
| `gui/__init__.py` | FastAPI app factory: middleware stack, static files, CSRF injection |
| `gui/daemon.py` | Local daemon metadata, port selection, stale metadata cleanup, structured readiness |
| `gui/server.py` | Uvicorn launcher. Binds `127.0.0.1` only |
| `gui/security.py` | CSRF, host validation, path validation, stream URL validation |
| `gui/api/` | API routers: home, search, library, downloads, playlists, settings, setup, duplicates, upgrade, albums, playback |
| `gui/services/` | Persisted download/upgrade job lifecycle primitives and worker service |
| `helper/library_db.py` | SQLite wrapper: schema, migrations, CRUD, WAL mode |
| `helper/path.py` | Config paths, download path templates, filename sanitization |
| `helper/cache.py` | `TTLCache` — thread-safe in-memory cache with TTL expiry |
| `helper/library_scanner.py` | Walk directories, extract ISRC from audio tags via mutagen |
| `helper/checkpoint.py` | `DownloadCheckpoint` — resume interrupted downloads |
| `helper/decorator.py` | `SingletonMeta` metaclass |
| `helper/tidal.py` | Tidal URL parsing, media instantiation, name formatting |
| `helper/camelot.py` | Camelot wheel notation helpers for harmonic mixing |
| `helper/cli.py` | Helper functions for CLI operations (formatting, dates) |
| `helper/decryption.py` | AES decryption for encrypted TIDAL streams |
| `helper/exceptions.py` | Custom exception classes (`LoginError`, etc.) |
| `helper/isrc_index.py` | Persistent thread-safe ISRC-to-path index for deduplication |
| `helper/playlist_import.py` | Cross-platform playlist import (CSV/JSON) |
| `helper/wrapper.py` | Logger wrapper with optional debug traceback output |
| `model/cfg.py` | `ModelSettings`, `ModelToken` dataclasses |
| `model/downloader.py` | Download-related data models and state |
| `model/meta.py` | Metadata dataclasses for tag writing |

---

## 3. Singletons

Three singletons via `SingletonMeta`. Call the class — you always get the same instance.

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
- `_try_login_with_key_rotation()` — tries all managed API keys before tidalapi defaults
- Token expiry handles both `float` (timestamp) and `datetime` from tidalapi

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
Tauri never assumes port `8765`; it reuses a ready browser daemon when the
metadata health check passes, otherwise it starts its own sidecar and waits
for metadata from that exact child process.

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

### Host Validation

Whitelist: `localhost:{port}`, `127.0.0.1:{port}`, bare `localhost`, bare `127.0.0.1`. Everything else → 403.

### Path Validation

| Function | Purpose | Rules |
|----------|---------|-------|
| `validate_audio_path(path)` | Playback requests | Resolves symlinks, checks file exists, extension in `AUDIO_EXTENSIONS` |
| `validate_download_path(path)` | Settings/wizard | Rejects `FORBIDDEN_PATHS` (`/etc`, `/usr`, `/System`, `~/.ssh`, `~/.gnupg`, `~/.config`, etc.) |
| `validate_stream_url(url)` | Download proxy | HTTPS only, host must be `*.tidal.com` — prevents SSRF |

### Constants

```python
AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac", ".wma"}
FORBIDDEN_PATHS  = {"/etc", "/usr", "/bin", "/sbin", "/var", "/System", ...}
TIDAL_CDN_HOSTS  = {"audio.tidal.com", "sp-ad-cf.audio.tidal.com", ...}
```

---

## 7. Database Schema

SQLite at `~/.config/music-dl/library.db`. WAL mode. 5-second busy timeout.

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
| `duration` | INTEGER | Seconds |
| `quality` | TEXT | `HI_RES_LOSSLESS`, `LOSSLESS`, etc. |
| `format` | TEXT | `FLAC`, `MP3`, etc. |
| `play_count` | INTEGER | Default 0 |
| `last_played` | INTEGER | Unix timestamp |
| `genre` | TEXT | |
| `scanned_at` | INTEGER | Unix timestamp |

Indexes: `idx_scanned_status`, `idx_scanned_isrc`

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
| `status` | TEXT NOT NULL | `queued`, `running`, `retrying`, `paused`, `done`, `error`, `cancelled`, `interrupted` |
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

Job creation uses an atomic `BEGIN IMMEDIATE` transaction so two requests cannot enqueue active duplicate work for the same `track_id`. Queue claiming also uses `BEGIN IMMEDIATE` and updates only a still-queued row before returning it to the worker.

Startup recovery rule: queued jobs stay queued. `running`, `retrying`, and `paused` jobs become `interrupted`. Terminal jobs stay terminal.

Pause rule: global queue pause does not rewrite queued backlog rows to `paused`; queued jobs remain `queued` so they can resume after restart.

FastAPI lifespan creates `DownloadJobService`, stores it on `app.state.download_jobs`, registers the service event hub with the running event loop, starts the persisted-job worker, and stops that worker during lifespan shutdown. Tests pass `job_db_path` to `create_app()` so API smoke tests use an isolated temporary job database instead of the user's real `library.db`.

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

**Caches:**

| Table | PK | Cached Data | TTL field |
|-------|----|------------|-----------|
| `artist_images` | `artist` | Tidal artist photo URLs | `fetched_at` |
| `playlist_covers` | `playlist_id` | Tidal playlist cover URLs | `fetched_at` |
| `quality_probes` | `isrc` | Tidal max quality per ISRC | `probed_at` |
| `library_meta` | `key` | Scan fingerprints, app state | — |

### Migrations

Additive only. Runs on every `open()`:

1. **v1 → v2**: Add `album`, `duration`, `quality`, `format` columns to `scanned`
2. **v2 → v3**: Add `play_count`, `last_played`, `genre` to `scanned`
3. **Late additions**: `cover_url`, `quality` columns on `download_history`
4. **Download jobs**: Add `download_jobs` table and job lookup indexes

Pattern: check `PRAGMA table_info()`, `ALTER TABLE ADD COLUMN` if missing. Never destructive.

### Connection Patterns

**LibraryDB class** (`helper/library_db.py`):
```python
db = LibraryDB(path)
db.open()                    # PRAGMA journal_mode=WAL, busy_timeout=5000
db.upsert_track(...)         # INSERT OR REPLACE
db.commit()
db.close()
```

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
  │    ├─ Get stream manifest (Hi-Fi API or OAuth)
  │    ├─ Download segments (parallel, up to N)
  │    ├─ Merge segments → single file
  │    ├─ Decrypt if encrypted
  │    ├─ Write metadata via mutagen (tags, cover, lyrics)
  │    ├─ Scan new downloads into LibraryDB
  │    ├─ Record in download_history
  │    ├─ Mark job "done"
  │    └─ Broadcast SSE: {"type": "complete", "status": "done"}
  │
  │  On error:
  │    ├─ Log exception
  │    ├─ Record error in download_history (nested try/except — never breaks broadcast)
  │    ├─ Mark job "error"
  │    └─ Broadcast SSE: {"type": "error", "message": "..."}
```

Upgrade jobs follow the same persisted lifecycle. `/api/upgrade/start` writes `kind='upgrade'` jobs with `old_path` and target quality, the worker downloads with `duplicate_action_override='redownload'`, applies the artist-mismatch safety gate before cleanup, removes stale same-album copies through `upgrade_jobs.cleanup_replaced_track_files()`, records `new_path`, and broadcasts `complete` plus `upgrade_complete`.

The worker lazy-loads Tidal config/download dependencies only when it actually executes a claimed job. That keeps API startup and service tests from triggering network-backed API-key refresh work.

### SSE Broadcasting

- Client connects: `GET /api/downloads/active` → `text/event-stream`
- `DownloadJobService.events` owns the `JobEventHub`
- Max 5 simultaneous clients by default
- Each client gets an `asyncio.Queue`
- On connect, `DownloadJobService.initial_events()` emits running job `progress` events and one `batch_queued` summary
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

### Stream Sources

| Source | When | How |
|--------|------|-----|
| Hi-Fi API | `active_source == HIFI_API` | Custom API client → `HiFiStreamManifest` (URLs, encryption) |
| OAuth | `active_source == OAUTH` | `tidalapi.Track.get_stream()` → BTS (JSON) or DASH (XML) manifest |

---

## 9. API Routes

All routes prefixed `/api`.

### Core

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/setup/status` | Wizard trigger: `{logged_in, scan_paths_configured, setup_complete}` |
| `POST` | `/setup/validate-path` | Check if path is safe and writable |
| `GET` | `/settings` | Current settings as JSON |
| `PATCH` | `/settings` | Update settings |
| `POST` | `/settings/login` | Start OAuth device-code flow |
| `GET` | `/settings/login-status` | Poll login progress |

### Library

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/library` | Paginated local tracks, grouped by artist |
| `POST` | `/library/scan` | Trigger background library scan |
| `GET` | `/library/scan-status` | Poll scan progress |

### Search & Download

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/search` | Search Tidal catalog, cross-ref local ISRCs |
| `POST` | `/download` | Queue track downloads |
| `GET` | `/downloads/active` | SSE stream for progress |
| `GET` | `/downloads/active/snapshot` | Current active jobs and queued count |
| `GET` | `/downloads/history` | Past downloads |
| `DELETE` | `/downloads/history` | Clear history |

### Playback

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/playback/stream` | Stream audio file to browser |
| `POST` | `/home/play` | Record play event |

### Collections

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/playlists` | Tidal playlists with local match info |
| `GET` | `/albums/{id}` | Album detail with track list |
| `GET` | `/home` | Dashboard stats (top artists, genres, play counts) |
| `GET` | `/duplicates/preview` | Find ISRC-based duplicates |
| `POST` | `/duplicates/clean` | Remove duplicate files |
| `GET` | `/upgrade/scan` | Find tracks upgradable to higher quality |
| `POST` | `/upgrade/start` | Queue upgrade jobs through the persisted job service |

---

## 10. Config System

### File Locations

| File | `MUSIC_DL_CONFIG_DIR` | Default |
|------|-----------------------|---------|
| `settings.json` | `$MUSIC_DL_CONFIG_DIR/settings.json` | `~/.config/music-dl/settings.json` |
| `token.json` | `$MUSIC_DL_CONFIG_DIR/token.json` | `~/.config/music-dl/token.json` |
| `library.db` | `$MUSIC_DL_CONFIG_DIR/library.db` | `~/.config/music-dl/library.db` |

`MUSIC_DL_CONFIG_DIR` is checked first in `path_config_base()`. This is how Docker overrides config location to `/config`.

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
| `downloads_simultaneous_per_track_max` | int | `3` | Parallel segment downloads |
| `format_album` | str | template | Download path template for albums |
| `format_track` | str | template | Download path template for tracks |

---

## 11. Thread Safety

| Resource | Guard | Pattern |
|----------|-------|---------|
| JobEventHub client list | `threading.Lock` | Acquired on add/remove/iterate |
| Rate limit counters | `threading.Lock` | Acquired on backoff decisions |
| LibraryDB | SQLite WAL + `busy_timeout=5000` | Concurrent reads, serialized writes with 5s retry |
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
- `busy_timeout=5000` handles NAS-induced SQLite lock contention

---

## 13. Sacred Rules

1. **Singletons are the API.** `Settings()`, `Tidal()`, `HandlingApp()` — call the class, get the instance. No dependency injection, no factories.
2. **SQLite is the cache, not the source.** The filesystem is truth. The DB is a fast index over it. If the DB is lost, a scan rebuilds it.
3. **Downloads never fail silently.** Every error broadcasts via SSE and logs. DB persistence failure must not prevent the broadcast.
4. **Token refresh is opportunistic.** Middleware tries before Tidal-facing requests. Failure is not fatal — the request will surface the real error.
5. **Localhost only.** Server binds `127.0.0.1`. Host validation rejects everything else. No exceptions.
6. **Migrations are additive.** `ALTER TABLE ADD COLUMN`. Never drop, rename, or restructure. Schema grows forward.
7. **Config corruption is recoverable.** `.bak` fallback, tolerant deserialization, defaults for missing fields.
8. **NAS mounts are unreliable.** Reconnect on staleness, run I/O off the event loop, use WAL + busy timeout.
9. **Audio path is sacred.** No Web Audio API, no signal processing. Files stream bit-perfect from disk to browser `<audio>` element.
10. **Rate limits are respected.** Exponential backoff on 429, recovery on sustained success. Never retry immediately.
