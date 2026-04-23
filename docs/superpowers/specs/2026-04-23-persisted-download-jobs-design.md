# Persisted Download Jobs Design

Date: 2026-04-23

## Goal

Move normal downloads and quality upgrades onto one persisted backend job lifecycle.

The current backend works, but the queue state is spread across route modules. `downloads.py` owns HTTP handlers, in-memory active state, thread control, SSE clients, Tidal resolution, download execution, DB history writes, and library rescans. `upgrade.py` reaches into those internals and duplicates job execution behavior for upgrades. That makes restarts, cancellation, status reporting, and future fixes harder than they need to be.

The target is closer to Multica's backend pattern: thin HTTP handlers, a service that owns task lifecycle, storage that owns persistence, and a separate event publisher for realtime updates. This project should keep its current Python/FastAPI/SQLite stack.

## Non-Goals

- No Go rewrite.
- No Postgres, Redis, Celery, or external queue.
- No separate daemon process.
- No generic task framework for unrelated app work.
- No frontend redesign.
- No replacement of `download_history` in this pass.
- No hard kill of an in-flight `Download.item()` call.

## Architecture

Add a small service layer under `tidal_dl/gui/services/`:

| Module | Responsibility |
| --- | --- |
| `job_models.py` | Dataclasses/enums for job kind, status, and events |
| `job_store.py` | Thin wrapper around `LibraryDB` job persistence methods |
| `job_events.py` | SSE subscriber registry and thread-safe broadcasting |
| `download_job_service.py` | Enqueue, pause, resume, cancel, snapshot, startup recovery, worker loop |

Keep route modules in `tidal_dl/gui/api/`, but make queue-related handlers thin:

- `downloads.py` validates request/auth and calls the service.
- `upgrade.py` keeps scan/probe endpoints, but `/api/upgrade/start` enqueues upgrade jobs through the same service.
- `gui/__init__.py` creates the service in FastAPI lifespan, stores it on `app.state`, and starts the worker loop.

### Why Not Simpler?

This cannot be cleanly implemented by extending `downloads.py`. That file already mixes API contracts, queue state, worker execution, SSE delivery, DB writes, and history. Adding persistence there would store job rows while preserving the same tangled ownership.

The new service layer introduces a few small modules and one service boundary. That adds files, but it removes direct coupling between downloads and upgrades and gives one owner for job lifecycle. The rejected simpler alternative is to bolt a `download_jobs` table directly into the existing route file; it would be faster to write but harder to reason about and test.

## Data Model

Add one SQLite table through `LibraryDB.open()` migration:

```sql
CREATE TABLE IF NOT EXISTS download_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  track_id INTEGER NOT NULL,
  name TEXT,
  artist TEXT,
  album TEXT,
  cover_url TEXT,
  quality TEXT,
  progress REAL DEFAULT 0,
  error TEXT,
  old_path TEXT,
  new_path TEXT,
  metadata_json TEXT,
  created_at REAL NOT NULL,
  started_at REAL,
  finished_at REAL
);

CREATE INDEX IF NOT EXISTS idx_download_jobs_status_created
  ON download_jobs(status, created_at);

CREATE INDEX IF NOT EXISTS idx_download_jobs_track_id
  ON download_jobs(track_id);
```

Allowed `kind` values:

- `download`
- `upgrade`

Allowed `status` values:

- `queued`
- `running`
- `retrying`
- `paused`
- `done`
- `error`
- `cancelled`
- `interrupted`

`paused` is for a job that has already been claimed and is blocked at a safe worker checkpoint. Ordinary queued rows should stay `queued` while the global queue is paused so they can resume normally.

Upgrade-only fields:

- `old_path`: local file being replaced.
- `new_path`: replacement file after successful upgrade.
- `metadata_json`: small execution context for album-aware upgrade behavior. Keep it narrow; do not turn it into an unstructured dumping ground.

Keep `download_history` as the existing frontend history contract. Terminal download and upgrade jobs still write `download_history`.

## Startup Recovery

On FastAPI startup:

- `queued` jobs remain `queued`.
- `running`, `retrying`, and `paused` jobs become `interrupted`.
- `done`, `error`, `cancelled`, and `interrupted` remain terminal.

Then the worker resumes queued jobs only. This gives persistence real value without surprise-resuming work that was already executing when the app stopped.

## Runtime Flow

### Startup

1. FastAPI lifespan creates `DownloadJobService`.
2. The service marks interrupted jobs.
3. The service starts one daemon worker thread.
4. The service receives the asyncio event loop for SSE broadcasting.

### Enqueue Downloads

1. `POST /api/download` validates `track_ids`.
2. The route checks Tidal login.
3. The route calls `job_service.enqueue_download(track_ids)`.
4. The service suppresses duplicate active/queued `track_id` jobs.
5. The service inserts `download_jobs` rows with `kind='download'` and `status='queued'`.
6. The service broadcasts the existing `batch_queued` event.

### Enqueue Upgrades

1. `POST /api/upgrade/start` keeps its current validation against selected paths/probes.
2. It builds one upgrade item per Tidal track ID.
3. It calls `job_service.enqueue_upgrade(items)`.
4. The service suppresses duplicate active/queued `track_id` jobs.
5. The service inserts `download_jobs` rows with `kind='upgrade'`, `old_path`, and narrow metadata.

### Worker

One worker claims the oldest queued job, one job at a time:

1. Change `queued` to `running`.
2. Resolve Tidal track metadata.
3. Update display fields: name, artist, album, cover URL, quality.
4. Execute by kind:
   - `download`: current `Download.item(...)` behavior with retry handling.
   - `upgrade`: album-aware template/download/swap/cleanup behavior currently in `_trigger_upgrade_downloads`.
5. Write terminal status to `download_jobs`.
6. Write existing `download_history`.
7. Broadcast existing SSE event shapes.

The worker should not own scan/probe discovery. Those stay in `upgrade.py` for now.

## API Compatibility

Preserve existing endpoint behavior:

- `POST /api/download`
- `POST /api/downloads/pause`
- `POST /api/downloads/resume`
- `POST /api/downloads/cancel`
- `GET /api/downloads/queue-state`
- `GET /api/downloads/active/snapshot`
- `GET /api/downloads/active`
- `GET /api/downloads/history`
- `POST /api/upgrade/start`

Preserve existing SSE event names the frontend already consumes:

- `batch_queued`
- `progress`
- `complete`
- `error`
- `queue_paused`
- `queue_resumed`
- `queue_cancelled`
- `cancelled`
- `upgrade_progress`
- `upgrade_complete`
- `upgrade_error`
- `ping`

New events may include `job_id` and `kind`, but existing fields such as `track_id`, `name`, `artist`, `album`, `cover_url`, `quality`, `status`, `progress`, `old_path`, and `new_path` must remain.

## Pause, Resume, Cancel

Pause:

- Sets service state to paused.
- The current job may finish.
- The worker does not claim another queued job until resumed.
- Queued rows stay `queued`; do not rewrite the whole backlog to `paused`.
- Broadcast `queue_paused`.

Resume:

- Clears pause state.
- Worker continues claiming queued jobs.
- Broadcast `queue_resumed`.

Cancel queued jobs:

- Mark matching queued rows `cancelled`.
- Broadcast `cancelled` for individual jobs or `queue_cancelled` for all.

Cancel current running job:

- Mark cancellation requested in memory.
- Terminalize at the next safe checkpoint.
- Do not attempt to kill `Download.item()` mid-call in this pass.

## Testing

Add focused coverage:

- `LibraryDB` creates `download_jobs` and indexes.
- Job CRUD: insert, claim oldest queued, update display fields, terminalize.
- Startup recovery changes `running`, `retrying`, and `paused` to `interrupted`.
- Queued jobs survive recovery and can be claimed afterward.
- Duplicate suppression prevents active/queued duplicate `track_id` jobs.
- Service pause/resume blocks and resumes queue claiming.
- Service cancel marks queued jobs terminal.
- API enqueue keeps existing response shapes.
- Upgrade start enqueues `kind='upgrade'` jobs through the shared queue.

Existing API smoke tests must keep passing.

## Acceptance Criteria

- Restart while queued jobs exist: queued jobs resume.
- Restart while a job is running: that job becomes `interrupted`; remaining queued jobs resume.
- Downloads and upgrades cannot double-queue the same active/queued `track_id`.
- Pause, resume, cancel, snapshot, SSE, and history routes work through the service.
- `/api/downloads/active`, `/api/downloads/active/snapshot`, and `/api/downloads/history` keep existing frontend behavior.
- Upgrade downloads use the same persisted lifecycle as normal downloads.
- Route modules no longer own queue state or SSE client registries.

## Rollout

Phase 1: persistence and normal download service

1. Add `download_jobs` schema and `LibraryDB` methods.
2. Add service/event/model modules.
3. Wire FastAPI lifespan to create and start the service.
4. Move normal download queue state and SSE into the service.
5. Keep normal download execution behavior equivalent.

Phase 2: shared upgrade execution

1. Change `/api/upgrade/start` to enqueue `kind='upgrade'` jobs.
2. Move upgrade execution behind the shared worker.
3. Preserve upgrade scan/probe endpoints.
4. Preserve frontend SSE event names and API response shapes.
