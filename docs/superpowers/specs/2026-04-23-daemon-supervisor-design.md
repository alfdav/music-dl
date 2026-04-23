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
- Metadata records `starting` while the process is booting.
- HTTP health is expected to become reachable only after uvicorn and the FastAPI lifespan startup are ready.
- Health reports `ready` after startup has finished.
- On clean shutdown, metadata is removed.
- On startup, stale metadata is ignored and removed when the PID is dead or the health endpoint does not respond as `music-dl`.

## Port Selection

Default behavior:

- prefer `8765`
- if `8765` is free, use it
- if `8765` has a healthy `music-dl` daemon, reuse it when the caller wants discovery
- if `8765` is occupied by another process, choose a free localhost port

The daemon never binds outside localhost unless existing Docker/browser-mode behavior explicitly requests it through `MUSIC_DL_BIND_ALL`.

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

- spawn sidecar
- wait for `daemon.json` to appear or for sidecar stdout to print the selected base URL
- poll the reported `/api/server/health`
- require `status == "ready"` and `app == "music-dl"`
- navigate to the reported `base_url`
- show a startup error that includes the last observed metadata or health state if health never becomes ready

The sidecar should still be killed when the Tauri window exits.

## Browser CLI Startup

`music-dl gui` keeps its current user behavior:

- default port remains `8765`
- `--port` still works
- `--no-browser` still works

Internally, it uses `daemon.py` to create the server config and runtime metadata. If the selected port differs from the requested port because the requested port is occupied, the CLI prints the actual URL before opening the browser.

## Server Restart

`POST /api/server/restart` should continue to work in browser mode.

In Tauri mode, restart remains managed by the desktop shell. The health payload must make that mode visible so frontend code can choose the right restart path.

## Error Handling

Startup errors must be explicit:

- port occupied by non-`music-dl` process
- metadata exists but PID is dead
- metadata exists but health reports the wrong app
- health timed out
- sidecar exited before readiness

Tauri loading UI should show a useful error instead of leaving the user on a blank or endless loading page.

## Testing

Add focused tests for:

- metadata path generation
- metadata write/read/remove
- stale metadata cleanup when PID is dead
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
- Existing `music-dl gui --no-browser` behavior still works.
- Existing local-only security assumptions remain intact.
