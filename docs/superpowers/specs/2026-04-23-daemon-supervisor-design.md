# Daemon Supervisor Design

Date: 2026-04-23
Status: Approved for implementation planning

## Goal

Improve the local `music-dl` daemon without rewriting the backend stack.

The current daemon behavior is too brittle:

- Tauri hardcodes `http://localhost:8765`.
- Tauri treats a TCP connection as readiness, even when HTTP health is not ready.
- Browser mode and Tauri sidecar mode have separate lifecycle paths.
- A stale sidecar can hold the port and leave the app on a loading page.
- There is no runtime metadata file that tells clients which daemon is owned by `music-dl`.

The first improvement is a small supervisor layer around the existing FastAPI app. It keeps the current Python/FastAPI backend and focuses only on process ownership, discovery, health, startup, restart, and cleanup.

## Non-Goals

This design does not:

- rewrite the backend in Go
- replace FastAPI
- replace SQLite
- refactor all API route business logic into services
- make the daemon a persistent system service after app exit
- change Discord bot behavior beyond allowing it to discover the daemon later
- add multi-user auth, remote access, or cloud behavior

## Why Not Simpler?

### Why not extend `tidal_dl/gui/server.py` only?

Daemon behavior is already split across:

- `tidal_dl/gui/server.py`
- `sidecar_entry.py`
- `src-tauri/src/lib.rs`
- `tidal_dl/gui/api/server_control.py`

Extending only `server.py` would leave Tauri on separate hardcoded readiness and restart rules. The current bug came from that split: the sidecar process existed, but the app still could not reliably prove HTTP readiness.

### What complexity does the new module introduce?

It introduces:

- one focused Python module, `tidal_dl/gui/daemon.py`
- one runtime metadata file, `daemon.json`
- one structured health response contract

That is acceptable because it removes duplicated lifecycle assumptions.

### What becomes harder?

Startup changes will require understanding `daemon.py`. That is a real cost. It is still easier than tracking launch behavior across Python CLI, PyInstaller sidecar entry, Tauri Rust code, and health routes independently.

### What simpler alternative was rejected?

Only increasing the Tauri timeout or changing TCP polling to HTTP polling was rejected. It would reduce the visible loading failure but would not solve stale process ownership, port conflicts, or client daemon discovery.

## Architecture

Add `tidal_dl/gui/daemon.py` as the single owner of local daemon runtime behavior.

Responsibilities:

- choose the daemon port
- validate whether an existing daemon belongs to this app
- write runtime metadata
- remove stale metadata
- create the uvicorn config for the existing `tidal_dl.gui:create_app`
- expose data used by `/api/server/health`

Existing FastAPI app creation remains in `tidal_dl/gui/__init__.py`.

Existing browser-mode launch remains available through `music-dl gui`.

Existing Tauri sidecar binary remains Python/PyInstaller.

## Runtime Metadata

Write metadata to:

```text
~/.config/music-dl/daemon.json
```

Shape:

```json
{
  "app": "music-dl",
  "version": "1.5.1",
  "status": "starting",
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 8765,
  "base_url": "http://127.0.0.1:8765",
  "health_url": "http://127.0.0.1:8765/api/server/health",
  "mode": "tauri-sidecar",
  "started_at": 1776986400.0
}
```

Rules:

- Metadata is written before uvicorn starts accepting traffic.
- Metadata includes `status`.
- Metadata records `starting` while the process is booting.
- Metadata records `ready` after FastAPI lifespan startup has completed.
- Metadata records `stopping` during graceful shutdown when practical; abrupt process death may leave stale `ready` metadata, which startup cleanup must handle.
- HTTP health is expected to become reachable only after uvicorn and the FastAPI lifespan startup are ready.
- Health reports `ready` after startup has finished.
- On clean shutdown, metadata is removed.
- On startup, stale metadata is ignored and removed when the PID is dead or the recorded health endpoint does not respond as a ready `music-dl` daemon.
- Stale metadata cleanup is a normal recovery path. Startup fails only if stale metadata cannot be removed or no usable port can be found.
- Metadata cleanup is validation-checked. A process may remove `daemon.json` only when the file's `pid` matches its own PID, when stale validation proves the recorded PID is dead, or when the recorded health endpoint fails the ready-`music-dl` check.
- The ready-`music-dl` check is one HTTP GET to the recorded `health_url` with a 2-second timeout. It passes only when the response has `app == "music-dl"` and `status == "ready"`. Connection failure, timeout, invalid JSON, non-2xx response, wrong app, or non-ready status all fail the check.
- If metadata points at a live PID whose health check fails, startup removes only `daemon.json`; it must not kill that live process.
- `daemon.json` describes one canonical daemon. This design does not support multiple concurrently discoverable `music-dl` daemons for the same user config directory.

Allowed modes:

- `browser` for `music-dl gui`
- `tauri-sidecar` for the bundled desktop sidecar

## Port Selection

Default behavior:

- first check `daemon.json`
- if it points to a healthy `music-dl` daemon, reuse that daemon and report its URL
- if metadata is stale, clean it up and continue startup
- prefer `8765`
- if `8765` is free, use it
- if `8765` is occupied by another process, choose a free localhost port and report the actual URL
- the same fallback behavior applies when the user explicitly passes `--port`, but only when no healthy canonical daemon already exists
- if a healthy canonical daemon already exists on a different port, `music-dl gui --port <port>` reuses it and prints the actual existing URL instead of starting a second daemon

The daemon never binds outside localhost unless existing Docker/browser-mode behavior explicitly requests it through `MUSIC_DL_BIND_ALL`.

Canonical host for non-Docker local app URLs is `127.0.0.1`. `localhost` remains accepted by host validation for compatibility, but new metadata, health URLs, and Tauri navigation should use `127.0.0.1`.

## Health Contract

Replace the current minimal health payload:

```json
{"status":"running"}
```

with:

```json
{
  "status": "ready",
  "app": "music-dl",
  "version": "1.5.1",
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 8765,
  "mode": "tauri-sidecar",
  "started_at": 1776986400.0
}
```

Allowed statuses:

- `starting`
- `ready`
- `stopping`

Clients must treat only `ready` from the HTTP health endpoint as usable. `starting` may be observed from `daemon.json` before the HTTP endpoint is reachable.

## Tauri Startup

Tauri should stop using TCP connect as readiness.

Current behavior:

- spawn sidecar
- poll TCP `127.0.0.1:8765`
- navigate to hardcoded `http://localhost:8765`

New behavior:

- read `daemon.json`
- if it points to a healthy `music-dl` daemon, navigate to its `base_url` without spawning a sidecar
- if metadata is missing or stale, spawn sidecar
- wait for `daemon.json` to appear
- when a sidecar was spawned, require metadata `pid` to match the spawned sidecar child PID
- when a sidecar was spawned, require metadata `mode` to be `tauri-sidecar`
- poll the reported `/api/server/health`
- require `status == "ready"` and `app == "music-dl"`
- navigate to the reported `base_url`
- show a startup error that includes the last observed metadata or health state if health never becomes ready

The sidecar should be killed when the Tauri window exits only if Tauri spawned and owns that child process. If Tauri reused an existing browser-mode daemon, it must not kill that process on exit.

Tauri should not parse stdout for daemon discovery in this iteration. The metadata file is the single discovery contract.

Tauri should reuse an already-running healthy browser-mode daemon. This keeps `daemon.json` single-owner and avoids concurrent metadata races.

## Browser CLI Startup

`music-dl gui` keeps its current user behavior:

- default port remains `8765`
- `--port` still works
- `--no-browser` still works

Internally, it uses `daemon.py` to create the server config and runtime metadata. If the selected port differs from the requested port because the requested port is occupied, the CLI prints the actual URL before opening the browser.

If `music-dl gui` reuses an existing healthy daemon, it prints the existing URL, opens it unless `--no-browser` was passed, and exits without blocking. It does not attach to or supervise the existing process.

## Server Restart

`POST /api/server/restart` should continue to work in browser mode.

In Tauri mode, restart remains managed by the desktop shell. The health payload must make that mode visible so frontend code can choose the right restart path.

Tauri commands must stop assuming fixed port `8765`:

- `sidecar_status` checks the stored sidecar metadata and polls its `health_url`.
- `start_sidecar` waits for matching metadata and structured health before reporting success.
- `restart_sidecar` kills the tracked child, starts a new child, waits for matching metadata, and updates stored URL/port state.
- if Tauri is attached to a reused daemon it does not own, `stop_sidecar` and `restart_sidecar` must return a clear "daemon is external" error instead of killing it.

## Error Handling

Startup errors must be explicit:

- no free localhost port found
- stale metadata cleanup failed
- health timed out
- sidecar exited before readiness

Tauri loading UI should show a useful error instead of leaving the user on a blank or endless loading page.

## Testing

Add focused tests for:

- metadata path generation
- metadata write/read/remove
- stale metadata cleanup when PID is dead
- stale metadata cleanup removes metadata, but does not kill a live non-ready process owned by another PID
- Tauri startup reuses healthy browser-mode metadata without spawning
- port selection prefers `8765`
- port selection chooses another port when `8765` is occupied
- `/api/server/health` returns structured daemon state
- CLI still delegates with default port and `--no-browser`

Rust/Tauri behavior can be tested with unit-level helper functions where practical. Full desktop app startup can remain manual for this iteration.

## Implementation Order

1. Add `tidal_dl/gui/daemon.py` with pure helper functions and tests.
2. Wire structured daemon state into `create_app` and `/api/server/health`.
3. Update `gui/server.py` to use the daemon helpers.
4. Update `sidecar_entry.py` to use the same daemon helpers.
5. Update Tauri startup polling from TCP to HTTP health.
6. Update docs with the new daemon model.
7. Run Python tests for daemon/server behavior.
8. Run Tauri build or targeted Rust checks if available.

## Acceptance Criteria

- A healthy daemon can be discovered from `daemon.json`.
- Tauri no longer navigates based only on TCP readiness.
- Health returns structured readiness data.
- Port conflicts no longer leave the app stuck on `localhost:8765`.
- Stale daemon metadata is cleaned automatically.
- Live-PID metadata with non-ready or non-`music-dl` health is cleaned without killing that process.
- Existing `music-dl gui --no-browser` behavior still works.
- Existing local-only security assumptions remain intact.
