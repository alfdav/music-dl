# GUI Release Readiness — Design Spec

**Goal:** Make the web GUI ready for external users to clone, install, and use — the CLI is already public; the GUI is the new primary experience.

**Target audience:** Music collectors of all technical levels. The GUI should be approachable for non-techies; CLI remains for power users.

**Scope:** First-run experience, error resilience, install/launch story, Docker, README, self-healing edge cases, and packaging cleanup. Does NOT include new features — this is about making what exists shippable.

---

## 1. First-Run Setup Wizard

### Trigger mechanism
On initial page load, the frontend calls `GET /api/setup/status`. This new endpoint returns:
```json
{"logged_in": true/false, "scan_paths_configured": true/false, "setup_complete": true/false}
```
If `setup_complete` is false, render the wizard instead of the home view.

### Trigger conditions
- **Auto:** Shows on launch when Tidal token is missing OR `scan_paths` is empty
- **Manual:** Settings page has a "Run Setup Wizard" button
- **Per-step:** Settings page also exposes individual sections (Tidal Account, Music Directories) so users don't need the full wizard just to change one thing

### New API endpoints for wizard
- `GET /api/setup/status` — returns login state and scan_paths presence (wizard trigger)
- `POST /api/setup/validate-path` — validates a filesystem path exists and is readable server-side
- `POST /api/setup/login/start` — initiates device code flow, returns `{link, code, polling_id}`
- `GET /api/setup/login/poll/{polling_id}` — returns `{status: "pending"|"success"|"timeout"|"error"}`

### Wizard flow

**Step 1 — Tidal Login**
Full-screen card: "Connect your Tidal account." Initiates tidalapi device code flow via `POST /api/setup/login/start`, displays link.tidal.com + code, polls via `GET /api/setup/login/poll/{id}` every 2s until authenticated. Polling times out after 5 minutes — if timeout, shows "Login timed out" with a "Try again" button that generates a fresh code. On success, stores token via existing `config.py` persistence (writes to `token.json`, separate from `settings.json`), shows green checkmark, auto-advances.

**Step 2 — Music Directory**
"Where's your music?" Path input with a "Browse" button that uses the existing `POST /api/settings/browse-directory` endpoint (uses native OS picker via `osascript` on macOS, `tkinter` on Linux). Also accepts typed/pasted paths for headless/Docker environments where the OS picker isn't available. Validates via `POST /api/setup/validate-path`. Shows error if unreachable. Saves to `scan_paths` in settings (stored as comma-separated string in `settings.json`). User can add multiple paths; frontend splits/joins on comma. Shows existing paths with remove buttons.

**Step 3 — Initial Scan**
"Scanning your library..." with progress indicator. Polls `GET /api/library/scan/status` every 2 seconds (no SSE — library scan uses polling, not streaming). Shows scanned/total count updating live. User can skip and scan later. On completion or skip, redirects to Home view.

### Re-entry and mid-session auth

- **Auth expired mid-session:** Persistent banner across all views with "Re-login" button. Opens Step 1 as a modal overlay (same component), not the full wizard flow.
- **Settings page:** "Tidal Account" section shows connection status + "Re-login" button. "Music Directories" section shows current paths with add/remove. Uses the same `browse-directory` endpoint and `validate-path` endpoint as the wizard.
- **Re-Run Wizard button:** In Settings, restarts the full 3-step flow. For users who want a guided experience rather than editing individual settings.

---

## 2. Error States

### Design principle
Errors are never blank screens, console errors, or raw JSON. Every failure state has a human-readable message and an action button that leads to the fix.

### NAS / scan path unreachable
- Library view checks if configured paths are reachable before showing tracks
- **All paths down:** Full-width banner — "Can't reach [path]. Check your network drive connection." + Retry button + "Change paths" link to Settings
- **Partial failure (2 of 3 paths):** Warning toast, not a blocker. Scans what's available, notes which paths failed

### Tidal auth expired
- Persistent banner (not dismissable) across all views: "Tidal session expired" + "Re-login" button
- Re-login opens device code flow as modal, same component as wizard Step 1
- Download queue pauses automatically, resumes after re-auth
- Search shows the banner instead of results, not an empty state

### No scan paths configured (post-setup)
- Library view shows empty state card: "No music directories configured" + "Add folder" button → Settings
- Not the full wizard — user already completed setup, they just cleared their paths

### Concurrent operation conflicts
- Frontend catches 409 responses and shows human-readable toast: "Library scan in progress — try again when it finishes"
- Cleanup blocked during scan (and vice versa) with human-readable explanation, not raw JSON

---

## 3. Install & Launch

### CLI entrypoint (new code)
- `music-dl gui` — starts uvicorn on port 8765, auto-opens default browser
- `music-dl gui --port 9000` — custom port
- `music-dl gui --no-open` — server only, no browser launch (new flag — no existing flag to conflict with)
- Implemented as a Typer subcommand in the existing CLI module

### pip install
- `pip install music-dl` (or `uv pip install music-dl`) installs everything
- CLI + GUI deps are not separated — GUI is the primary experience
- `music-dl gui` works immediately after install

### Docker
- `Dockerfile` in `TIDALDL-PY/` — Python 3.12 slim, installs package, exposes 8765
- `docker-compose.yml` at repo root:
  ```yaml
  services:
    music-dl:
      build: ./TIDALDL-PY
      ports:
        - "8765:8765"
      volumes:
        - ~/.config/music-dl:/config
        - /path/to/music:/music  # user fills in their path
      environment:
        - MUSIC_DL_CONFIG_DIR=/config
  ```
- `path_config_base()` checks `MUSIC_DL_CONFIG_DIR` env var first, falls back to `~/.config/music-dl`
- Container runs `music-dl gui --no-open` (no browser inside container)
- Port auto-increment is disabled when `MUSIC_DL_CONFIG_DIR` is set (Docker indicator) — fixed port only
- First-run wizard handles login and points scan path at `/music`

### User journey convergence
Both install paths (Docker and pip) converge at the same wizard. No CLI knowledge needed after install.

---

## 4. README

### Structure — GUI-first
```
# music-dl
One-line: Download and manage your Tidal music library.

## Quick Start
  ### Docker (recommended)
    docker compose up → open localhost:8765
  ### pip
    pip install music-dl → music-dl gui

## Screenshots
  Setup wizard, library view, download in progress (2-3 shots)

## Features
  Library browser, Tidal search + download, quality upgrades,
  duplicate cleanup, playback

## Configuration
  Music directories, quality settings, download paths
  (brief — Settings page is self-explanatory)

## CLI Usage
  For power users: music-dl --help
  (condensed existing CLI docs)

## Development
  uv sync → uv run pytest → uv run music-dl gui

## License
```

### Principles
- No prerequisites wall before the user sees value — Docker path needs zero prereqs
- Screenshots are mandatory
- CLI is documented but clearly secondary

---

## 5. Self-Healing & Edge Cases

### Token refresh middleware (new code)
tidalapi tokens expire ~24h. User leaves GUI open overnight, next click hits stale token. **New FastAPI middleware** (does not exist today — must be built) runs `_ensure_token_fresh` before every Tidal-facing request. If refresh fails, sets a server-side `_auth_expired` flag. The `/api/setup/status` endpoint exposes this flag so the frontend can show the auth banner. SSE events also include an `auth_expired` field when the flag is set.

### Scan path disappears mid-scan
NAS drops during library scan. Per-file try/except in scan loop — if a path becomes unreachable mid-scan, finish what's reachable, report failure count, surface which path died. Don't kill the whole scan.

### 409 conflict rendering
Currently, concurrent scan + cleanup returns a 409 JSON that the frontend doesn't render gracefully. Frontend should catch 409s and show a human-readable toast: "Library scan in progress — try again when it finishes."

### Port already in use
User runs `music-dl gui` twice or port 8765 is occupied. On startup, check port. If occupied, try port+1 through port+10. Print actual URL to terminal. If all fail: "Port 8765-8775 all in use. Use --port to specify." **Exception:** When `MUSIC_DL_CONFIG_DIR` is set (Docker mode), skip auto-increment — use the exact port specified or fail immediately.

### Corrupted settings file
User hand-edits JSON, breaks syntax. Wrap settings load in try/except. If corrupt: rename to `settings.json.corrupt`, start fresh with defaults, show one-time banner: "Settings file was corrupted and has been reset." **Note:** Tidal tokens are stored in a separate file (`token.json` via `config.py` persistence), so auth survives settings corruption. The user does NOT need to re-login.

### Empty library after scan
User points at a directory with no audio files. After scan completes with 0 tracks: "No audio files found in [path]. Make sure this folder contains .flac, .m4a, or .mp3 files." + "Change directory" button. Not just an empty grid.

### Download path not writable
Validate on settings save — `os.access(path, os.W_OK)`. If fails, show error inline, don't save. On download attempt with invalid path, toast with "Fix in Settings" link.

### Auth polling timeout (new code)
User starts login wizard, closes browser tab. Backend polling thread times out after 5 minutes. `GET /api/setup/login/poll/{id}` returns `{"status": "timeout"}`. If the user returns, the wizard detects the timeout status and shows "Login timed out" with a "Try again" button that starts a fresh device code flow. Stale polling threads are cleaned up on timeout.

---

## 6. Packaging Cleanup

### .gitignore additions
```
.checkpoint/
.playwright/
test-results/
__pycache__/
*.pyc
.venv/
output/
*.egg-info/
dist/
build/
```

### Internal artifacts
Remove `docs/superpowers/` from release branch. These are internal planning specs and plans, not user-facing documentation. Either `.gitignore` the directory or strip during release rebase.

### Git history hygiene
Squash or drop checkpoint commits before public push. One-time interactive rebase — no ongoing process needed.

### pyproject.toml
- Verify `music-dl` script entry exists
- `gui` subcommand added to CLI, not as separate script
- Confirm `[project.urls]` has correct repo URL
- Version remains `3.0.0`

---

## Out of Scope

- New features (DJAI, new views, new API endpoints beyond what's needed for wizard/settings)
- Multi-user or remote access (this is a localhost tool)
- HTTPS/TLS — this is a localhost tool; credentials are not exposed over the network. If a user exposes the port to LAN, that's at their own risk (add a note in README)
- Frontend framework migration (staying vanilla JS)
- Mobile responsiveness (desktop browser is the target)
- CI/CD pipeline (future work after release)
