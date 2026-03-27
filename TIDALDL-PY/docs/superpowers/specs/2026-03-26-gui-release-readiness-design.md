# GUI Release Readiness — Design Spec

**Goal:** Make the web GUI ready for external users to clone, install, and use — the CLI is already public; the GUI is the new primary experience.

**Target audience:** Music collectors of all technical levels. The GUI should be approachable for non-techies; CLI remains for power users.

**Scope:** First-run experience, error resilience, install/launch story, Docker, README, self-healing edge cases, and packaging cleanup. Does NOT include new features — this is about making what exists shippable.

---

## 1. First-Run Setup Wizard

### Trigger conditions
- **Auto:** Shows on launch when Tidal token is missing OR `scan_paths` is empty
- **Manual:** Settings page has a "Run Setup Wizard" button
- **Per-step:** Settings page also exposes individual sections (Tidal Account, Music Directories) so users don't need the full wizard just to change one thing

### Wizard flow

**Step 1 — Tidal Login**
Full-screen card: "Connect your Tidal account." Initiates tidalapi device code flow, displays link.tidal.com + code, polls until authenticated. On success, stores token via existing `config.py` persistence, shows green checkmark, auto-advances.

**Step 2 — Music Directory**
"Where's your music?" Single path input with Add button (no native folder picker — browser security prevents it). Validates path exists server-side on submit, shows error if unreachable. Saves to `scan_paths` in settings. User can add multiple paths. Shows existing paths with remove buttons.

**Step 3 — Initial Scan**
"Scanning your library..." with progress bar using existing SSE scan events. User can skip and scan later. On completion or skip, redirects to Home view.

### Re-entry and mid-session auth

- **Auth expired mid-session:** Persistent banner across all views with "Re-login" button. Opens Step 1 as a modal overlay (same component), not the full wizard flow.
- **Settings page:** "Tidal Account" section shows connection status + "Re-login" button. "Music Directories" section shows current paths with add/remove.
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
- "Library scan in progress — some actions unavailable" banner instead of raw 409 JSON errors
- Cleanup blocked during scan (and vice versa) with human-readable explanation

---

## 3. Install & Launch

### CLI entrypoint
- `music-dl gui` — starts uvicorn on port 8765, auto-opens default browser
- `music-dl gui --port 9000` — custom port
- `music-dl gui --no-open` — server only, no browser launch
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
  ```
- Container runs `music-dl gui --no-open`
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

### Token refresh middleware
tidalapi tokens expire ~24h. User leaves GUI open overnight, next click hits stale token. Backend middleware runs `_ensure_token_fresh` before every Tidal-facing request. If refresh fails, sets flag that injects "session expired" banner on next response.

### Scan path disappears mid-scan
NAS drops during library scan. Per-file try/except in scan loop — if a path becomes unreachable mid-scan, finish what's reachable, report failure count, surface which path died. Don't kill the whole scan.

### 409 conflict rendering
Currently, concurrent scan + cleanup returns a 409 JSON that the frontend doesn't render gracefully. Frontend should catch 409s and show a human-readable toast: "Library scan in progress — try again when it finishes."

### Port already in use
User runs `music-dl gui` twice or port 8765 is occupied. On startup, check port. If occupied, try port+1 through port+10. Print actual URL to terminal. If all fail: "Port 8765-8775 all in use. Use --port to specify."

### Corrupted settings file
User hand-edits JSON, breaks syntax. Wrap settings load in try/except. If corrupt: rename to `settings.json.corrupt`, start fresh with defaults, show one-time banner: "Settings file was corrupted and has been reset."

### Empty library after scan
User points at a directory with no audio files. After scan completes with 0 tracks: "No audio files found in [path]. Make sure this folder contains .flac, .m4a, or .mp3 files." + "Change directory" button. Not just an empty grid.

### Download path not writable
Validate on settings save — `os.access(path, os.W_OK)`. If fails, show error inline, don't save. On download attempt with invalid path, toast with "Fix in Settings" link.

### Auth polling timeout
User starts login, closes browser tab. Polling thread times out after 5 minutes. If user returns, wizard shows fresh code, not stale one.

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
- Frontend framework migration (staying vanilla JS)
- Mobile responsiveness (desktop browser is the target)
- CI/CD pipeline (future work after release)
