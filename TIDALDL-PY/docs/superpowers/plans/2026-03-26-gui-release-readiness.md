# GUI Release Readiness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the web GUI installable and usable by external users — setup wizard, error handling, `music-dl gui` CLI command, Docker, and README.

**Architecture:** Leverage existing auth endpoints (`/auth/login`, `/auth/status`), settings CRUD, and `browse-directory`. Add a `/api/setup/status` endpoint as the wizard trigger. New `gui` Typer subcommand starts uvicorn and opens the browser. Frontend wizard is 3 steps rendered in `app.js`. Docker via single-container Dockerfile + compose.

**Tech Stack:** Python 3.12, FastAPI, Typer, tidalapi, uvicorn, Docker, vanilla JS

**Security note:** Frontend wizard uses innerHTML with hardcoded templates. Dynamic values from Tidal API (verification_uri, user_code) and filesystem paths are interpolated. For a localhost-only tool this is acceptable risk. If the tool ever becomes network-accessible, these should be sanitized with textContent or DOMPurify.

**Existing endpoints reused (do NOT rebuild):**
- `GET /api/auth/status` — returns `{logged_in, username}`
- `POST /api/auth/login` — starts device code flow, returns `{status, verification_uri, user_code}`
- `GET /api/auth/login/status` — polls login progress
- `GET /api/settings` — returns all settings including `scan_paths`
- `PATCH /api/settings` — updates settings
- `POST /api/browse-directory` — native OS folder picker

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `tidal_dl/gui/api/setup.py` | Create | Setup status + path validation endpoints |
| `tidal_dl/gui/api/__init__.py` | Modify | Register setup router |
| `tidal_dl/gui/api/settings.py` | Modify | Add login timeout, download path write check |
| `tidal_dl/gui/__init__.py` | Modify | Add token refresh middleware |
| `tidal_dl/gui/static/app.js` | Modify | Wizard UI, error banners, 409 handling |
| `tidal_dl/gui/static/style.css` | Modify | Wizard + banner styles |
| `tidal_dl/cli.py` | Modify | Add `gui` subcommand |
| `tidal_dl/helper/path.py` | Modify | Support `MUSIC_DL_CONFIG_DIR` env var |
| `tidal_dl/config.py` | Modify | Settings corruption recovery |
| `tests/test_setup.py` | Create | Setup endpoint tests |
| `tests/test_gui_command.py` | Create | CLI gui subcommand tests |
| `TIDALDL-PY/Dockerfile` | Create | Container image |
| `docker-compose.yml` | Create | Compose config |
| `TIDALDL-PY/README.md` | Rewrite | GUI-first documentation |
| `.gitignore` | Modify | Add missing patterns |

**Parallelism:** Tasks 1, 3, 4, 7, 8, 9 are independent. Task 2 depends on 1 (setup router registered). Task 5 depends on 1+2 (backend endpoints exist). Task 6 is independent. Task 10 depends on all.

---

### Task 1: Setup status endpoint + path validation

**Files:**
- Create: `tidal_dl/gui/api/setup.py`
- Modify: `tidal_dl/gui/api/__init__.py`
- Create: `tests/test_setup.py`

The wizard trigger endpoint. Frontend calls this on page load to decide: show wizard or show app.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_setup.py
"""Tests for setup wizard endpoints."""
import re
from fastapi.testclient import TestClient


def _make_client():
    from tidal_dl.gui import create_app
    return TestClient(create_app(port=8765))


def _get_csrf(client):
    _HOST = {"host": "localhost:8765"}
    index = client.get("/", headers=_HOST)
    match = re.search(r'name="csrf-token" content="([^"]+)"', index.text)
    return match.group(1) if match else ""


_HOST = {"host": "localhost:8765"}


def test_setup_status_returns_200():
    client = _make_client()
    resp = client.get("/api/setup/status", headers=_HOST)
    assert resp.status_code == 200
    data = resp.json()
    assert "logged_in" in data
    assert "scan_paths_configured" in data
    assert "setup_complete" in data


def test_setup_status_types():
    client = _make_client()
    data = client.get("/api/setup/status", headers=_HOST).json()
    assert isinstance(data["logged_in"], bool)
    assert isinstance(data["scan_paths_configured"], bool)
    assert isinstance(data["setup_complete"], bool)


def test_validate_path_existing(tmp_path):
    client = _make_client()
    csrf = _get_csrf(client)
    resp = client.post(
        "/api/setup/validate-path",
        json={"path": str(tmp_path)},
        headers={**_HOST, "X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_validate_path_nonexistent():
    client = _make_client()
    csrf = _get_csrf(client)
    resp = client.post(
        "/api/setup/validate-path",
        json={"path": "/nonexistent/path/xyz"},
        headers={**_HOST, "X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is False


def test_validate_path_empty():
    client = _make_client()
    csrf = _get_csrf(client)
    resp = client.post(
        "/api/setup/validate-path",
        json={"path": ""},
        headers={**_HOST, "X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -v --tb=short`
Expected: FAIL (no module `tidal_dl.gui.api.setup`)

- [ ] **Step 3: Implement setup.py**

```python
# tidal_dl/gui/api/setup.py
"""Setup wizard endpoints — status check and path validation."""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from tidal_dl.config import Settings, Tidal

router = APIRouter()


@router.get("/setup/status")
def setup_status() -> dict:
    """Check if first-run setup is needed."""
    tidal = Tidal()
    try:
        logged_in = tidal.session.check_login()
    except Exception:
        logged_in = False

    settings = Settings()
    scan_paths = (settings.data.scan_paths or "").strip()
    scan_paths_configured = len(scan_paths) > 0

    return {
        "logged_in": logged_in,
        "scan_paths_configured": scan_paths_configured,
        "setup_complete": logged_in and scan_paths_configured,
    }


class ValidatePathRequest(BaseModel):
    path: str


@router.post("/setup/validate-path")
def validate_path(req: ValidatePathRequest) -> dict:
    """Check if a filesystem path exists and is readable."""
    path = req.path.strip()
    if not path:
        return {"valid": False, "error": "Path is empty"}
    exists = os.path.isdir(path)
    readable = os.access(path, os.R_OK) if exists else False
    if not exists:
        return {"valid": False, "error": "Directory does not exist"}
    if not readable:
        return {"valid": False, "error": "Directory is not readable"}
    return {"valid": True, "error": None}
```

- [ ] **Step 4: Register router in `__init__.py`**

Add to `tidal_dl/gui/api/__init__.py`:
```python
from tidal_dl.gui.api.setup import router as setup_router
# after other includes:
api_router.include_router(setup_router, tags=["setup"])
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_setup.py -v --tb=short`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add tidal_dl/gui/api/setup.py tidal_dl/gui/api/__init__.py tests/test_setup.py
git commit -m "feat(setup): wizard status endpoint and path validation"
```

---

### Task 2: Login timeout + token refresh middleware

**Files:**
- Modify: `tidal_dl/gui/api/settings.py:86-94` (login timeout)
- Modify: `tidal_dl/gui/__init__.py` (token refresh middleware)

- [ ] **Step 1: Add login timeout to settings.py**

In `tidal_dl/gui/api/settings.py`, modify the `_wait_for_login` function (lines 86-94). Replace:

```python
        def _wait_for_login():
            try:
                future.result()  # blocks until user completes browser login
                if tidal.login_finalize():
                    _login_state["status"] = "success"
                else:
                    _login_state["status"] = "failed"
            except Exception:
                _login_state["status"] = "failed"
```

With:

```python
        def _wait_for_login():
            try:
                future.result(timeout=300)  # 5 min timeout
                if tidal.login_finalize():
                    _login_state["status"] = "success"
                else:
                    _login_state["status"] = "failed"
            except TimeoutError:
                _login_state["status"] = "timeout"
            except Exception:
                _login_state["status"] = "failed"
```

- [ ] **Step 2: Add token refresh middleware to `gui/__init__.py`**

In `create_app()`, add after the CORS middleware block (after line 28):

```python
    # Token refresh middleware — keeps Tidal session alive
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class TokenRefreshMiddleware(BaseHTTPMiddleware):
        """Run _ensure_token_fresh before Tidal-facing API calls."""
        _TIDAL_PATHS = ("/api/search", "/api/download", "/api/playlists")

        async def dispatch(self, request: Request, call_next):
            if any(request.url.path.startswith(p) for p in self._TIDAL_PATHS):
                try:
                    from tidal_dl.config import Tidal as _Tidal
                    _Tidal()._ensure_token_fresh()
                except Exception:
                    pass  # auth status endpoint will surface the error
            return await call_next(request)

    app.add_middleware(TokenRefreshMiddleware)
```

- [ ] **Step 3: Run existing tests to check no regressions**

Run: `uv run pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 0 failed

- [ ] **Step 4: Commit**

```bash
git add tidal_dl/gui/api/settings.py tidal_dl/gui/__init__.py
git commit -m "feat(auth): login timeout (5min) and token refresh middleware"
```

---

### Task 3: `MUSIC_DL_CONFIG_DIR` env var support

**Files:**
- Modify: `tidal_dl/helper/path.py:74-79`

- [ ] **Step 1: Modify `path_config_base()` in `path.py`**

Read the current function first. Replace it with:

```python
def path_config_base() -> str:
    # Docker / custom override takes precedence
    custom = os.environ.get("MUSIC_DL_CONFIG_DIR", "")
    if custom:
        return custom
    # Original logic follows:
    path_user_custom: str = os.environ.get("XDG_CONFIG_HOME", "")
    path_config: str = ".config" if not path_user_custom else ""
    # ... rest of existing function unchanged ...
```

Add the 3-line `MUSIC_DL_CONFIG_DIR` check at the very top of the function, before any other logic. Do NOT change the rest of the function.

- [ ] **Step 2: Run existing tests**

Run: `uv run pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 0 failed

- [ ] **Step 3: Commit**

```bash
git add tidal_dl/helper/path.py
git commit -m "feat(config): support MUSIC_DL_CONFIG_DIR env var for Docker"
```

---

### Task 4: `music-dl gui` CLI subcommand

**Files:**
- Modify: `tidal_dl/cli.py`
- Create: `tests/test_gui_command.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_gui_command.py
"""Tests for the music-dl gui CLI subcommand."""
from typer.testing import CliRunner
from tidal_dl.cli import app

runner = CliRunner()


def test_gui_help():
    """The gui subcommand should show help text."""
    result = runner.invoke(app, ["gui", "--help"])
    assert result.exit_code == 0
    assert "port" in result.output.lower()
    assert "no-open" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gui_command.py -v --tb=short`
Expected: FAIL (no `gui` command)

- [ ] **Step 3: Add gui subcommand to cli.py**

Add these imports near the top of `cli.py` (with existing imports):

```python
import os
import socket
import webbrowser
```

Add the command before `if __name__ == "__main__"` (or at end of file with other commands):

```python
@app.command()
def gui(
    port: int = typer.Option(8765, help="Port for the web GUI"),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open browser"),
):
    """Launch the web GUI in your browser."""
    import uvicorn
    from tidal_dl.gui import create_app

    def _port_available(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", p)) != 0

    docker_mode = bool(os.environ.get("MUSIC_DL_CONFIG_DIR"))

    actual_port = port
    if not _port_available(port):
        if docker_mode:
            Console().print(f"[red]Port {port} is in use.[/red]")
            raise typer.Exit(1)
        for candidate in range(port + 1, port + 11):
            if _port_available(candidate):
                actual_port = candidate
                Console().print(f"[yellow]Port {port} in use, using {actual_port}[/yellow]")
                break
        else:
            Console().print(f"[red]Ports {port}-{port+10} all in use. Use --port to specify.[/red]")
            raise typer.Exit(1)

    _app = create_app(port=actual_port)
    url = f"http://localhost:{actual_port}"
    Console().print(f"[green]music-dl GUI → {url}[/green]")

    if not no_open:
        import threading
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(_app, host="0.0.0.0", port=actual_port, log_level="warning")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_gui_command.py -v --tb=short`
Expected: Pass

- [ ] **Step 5: Commit**

```bash
git add tidal_dl/cli.py tests/test_gui_command.py
git commit -m "feat(cli): add 'music-dl gui' subcommand with port fallback"
```

---

### Task 5: Frontend wizard + error banners

**Files:**
- Modify: `tidal_dl/gui/static/app.js`
- Modify: `tidal_dl/gui/static/style.css`

This is the largest frontend task. Read `app.js` first to understand the existing patterns (`_navigate`, `_showToast`, `_csrf`, view rendering). The wizard integrates at the top of the init flow.

- [ ] **Step 1: Add wizard check to app initialization**

In `app.js`, find the main initialization code (DOMContentLoaded or init function). Add at the very beginning, before any view rendering:

```javascript
async function _checkSetup() {
    try {
        const resp = await fetch('/api/setup/status');
        const data = await resp.json();
        if (!data.setup_complete) {
            _renderWizard(data);
            return true;
        }
    } catch (e) {
        console.error('Setup check failed:', e);
    }
    return false;
}
```

Call `_checkSetup()` before rendering the default view. If it returns true, skip normal navigation.

- [ ] **Step 2: Implement wizard step 1 — Tidal login**

Add `_renderWizard()` and `_wizardStepLogin()` functions. The login step:
- Shows a "Connect to Tidal" button
- On click, POSTs to `/api/auth/login` (existing endpoint)
- Shows the verification URI and user code
- Polls `/api/auth/login/status` every 2s
- On success, re-checks setup status and advances
- On timeout/failure, shows error with retry button

Use the existing `_csrf()` helper for CSRF tokens. Use `textContent` for dynamic user-facing values where possible; use element creation (createElement/appendChild) for structured content instead of innerHTML with user data.

- [ ] **Step 3: Implement wizard step 2 — music directories**

Add `_wizardStepPaths()` function:
- Text input + Browse button (POST `/api/browse-directory`) + Add button
- Validates via POST `/api/setup/validate-path` before adding
- Shows list of added paths with remove buttons
- On "Continue", PATCHes `/api/settings` with `scan_paths` as comma-joined string
- POSTs `/api/library/scan` to start initial scan
- Navigates to home view

- [ ] **Step 4: Add error banners**

Add `_checkErrorBanners()` function, called after each view render:
- Checks `/api/auth/status` — if not logged in, shows persistent "Tidal session expired" banner with re-login button
- On library view, checks if `scan_paths` is empty — shows "No music directories configured" with settings link

Add global 409 handler by wrapping `fetch`:

```javascript
const _origFetch = window.fetch;
window.fetch = async (...args) => {
    const resp = await _origFetch(...args);
    if (resp.status === 409) {
        const data = await resp.clone().json().catch(() => null);
        _showToast(data?.detail || 'Operation in progress — try again shortly.');
    }
    return resp;
};
```

- [ ] **Step 5: Add wizard + banner CSS to style.css**

Append wizard styles: `.setup-wizard`, `.wizard-card`, `.wizard-btn`, `.device-code`, `.wizard-paths`, `.path-input-row`, `.error-banner`, `.banner-action`, spinner animation. Follow existing CSS variable patterns (`--card-bg`, `--accent`, `--text-secondary`).

- [ ] **Step 6: Manual smoke test**

Start server and verify:
1. Fresh state (no token) → wizard shows
2. Login step → device code displayed, polling works
3. Path step → browse and type paths, validation works
4. After setup → normal app loads
5. Error banner → shows when auth expires (can test by clearing token)

- [ ] **Step 7: Commit**

```bash
git add tidal_dl/gui/static/app.js tidal_dl/gui/static/style.css
git commit -m "feat(wizard): 3-step setup wizard, error banners, 409 handling"
```

---

### Task 6: Self-healing — corrupted settings, download path validation

**Files:**
- Modify: `tidal_dl/config.py` (settings corruption recovery)
- Modify: `tidal_dl/gui/api/settings.py` (download path write check)

- [ ] **Step 1: Add settings corruption recovery**

In `tidal_dl/config.py`, find where the settings JSON file is loaded/parsed. Wrap the parse in try/except. On `JSONDecodeError` or `KeyError`:
1. Copy the corrupt file to `{path}.corrupt`
2. Log a warning
3. Reset `self.data` to the dataclass defaults
4. Call `self.save()` to write clean defaults

- [ ] **Step 2: Add download path write check to settings.py**

In `tidal_dl/gui/api/settings.py` `update_settings()`, add after the existing `validate_download_path` check:

```python
    if "download_base_path" in updates:
        path = updates["download_base_path"]
        if not validate_download_path(path):
            raise HTTPException(status_code=400, detail="Invalid download path")
        if path and not os.access(path, os.W_OK):
            raise HTTPException(status_code=400, detail="Download path is not writable")
```

Add `import os` at the top if not already there.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 0 failed

- [ ] **Step 4: Commit**

```bash
git add tidal_dl/config.py tidal_dl/gui/api/settings.py
git commit -m "fix(resilience): settings corruption recovery, download path write check"
```

---

### Task 7: Docker

**Files:**
- Create: `TIDALDL-PY/Dockerfile`
- Create: `docker-compose.yml` (at repo root)

- [ ] **Step 1: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY tidal_dl/ tidal_dl/

RUN pip install --no-cache-dir .

ENV MUSIC_DL_CONFIG_DIR=/config

EXPOSE 8765

CMD ["music-dl", "gui", "--no-open", "--port", "8765"]
```

- [ ] **Step 2: Create docker-compose.yml at repo root**

```yaml
services:
  music-dl:
    build: ./TIDALDL-PY
    ports:
      - "8765:8765"
    volumes:
      - ${MUSIC_DL_CONFIG:-~/.config/music-dl}:/config
      - ${MUSIC_DIR:-./music}:/music
    environment:
      - MUSIC_DL_CONFIG_DIR=/config
    restart: unless-stopped
```

- [ ] **Step 3: Test build (if Docker available)**

Run: `docker compose build`
Expected: Image builds. If Docker not available, skip — CI will validate.

- [ ] **Step 4: Commit**

```bash
git add TIDALDL-PY/Dockerfile docker-compose.yml
git commit -m "feat(docker): Dockerfile + compose for one-command GUI setup"
```

---

### Task 8: .gitignore + packaging cleanup

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Ensure these entries exist in `.gitignore`**

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
docs/superpowers/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore cleanup for release"
```

---

### Task 9: README rewrite

**Files:**
- Rewrite: `TIDALDL-PY/README.md`

- [ ] **Step 1: Write GUI-first README**

Structure:
1. One-line description
2. Quick Start (Docker + pip — 3 lines each)
3. Screenshots placeholder (TODO)
4. Features list (6 bullet points)
5. Configuration (brief — Settings page is self-explanatory)
6. CLI Usage (for power users, condensed)
7. Development (uv sync, pytest, music-dl gui)
8. Security note (localhost-only, no HTTPS)
9. License

Lead with Docker as recommended path. `pip install music-dl && music-dl gui` as alternative. Both converge at the setup wizard.

- [ ] **Step 2: Commit**

```bash
git add TIDALDL-PY/README.md
git commit -m "docs: GUI-first README with Docker quick start"
```

---

### Task 10: Final integration test + release tag

**Depends on:** All previous tasks complete.

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short 2>&1 | tail -5`
Expected: 0 failed

- [ ] **Step 2: Test Docker build (if available)**

Run: `docker compose build && docker compose up -d && sleep 3 && curl -s http://localhost:8765/api/setup/status && docker compose down`
Expected: JSON response with `setup_complete: false`

- [ ] **Step 3: Manual smoke test**

Start: `uv run music-dl gui`
Verify:
1. Browser opens automatically
2. Wizard shows if not logged in
3. Login flow works (device code appears)
4. Path selection works (Browse + typed path)
5. Library scan starts after paths saved
6. Error banner appears when auth is expired
7. Settings page has "Run Setup Wizard" button
8. 409 errors show as toasts, not raw JSON

- [ ] **Step 4: Tag release**

```bash
git tag -a v3.0.0 -m "music-dl v3.0.0 — Web GUI release"
```
