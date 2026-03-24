# music-dl GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a browser-based GUI to music-dl via `music-dl gui` that serves a local web app for searching Tidal, playing music, and downloading tracks.

**Architecture:** FastAPI backend serving JSON API endpoints + static vanilla JS/CSS/HTML frontend. The GUI is a thin layer over existing music-dl infrastructure — search uses `tidalapi`, downloads use the `Download` class, ISRC cross-referencing uses `IsrcIndex`. Audio plays natively in the browser via HTML5 `<audio>`.

**Tech Stack:** FastAPI, uvicorn, vanilla JS SPA (no framework), HTML5 Audio API, CSS custom properties, Server-Sent Events for download progress.

**Spec:** `docs/superpowers/specs/2026-03-23-gui-design.md`

---

## File Map

All paths below are relative to `TIDALDL-PY/`.

### New Files

| File | Responsibility |
|---|---|
| `tidal_dl/gui/__init__.py` | FastAPI app factory — creates app, mounts static, registers routers |
| `tidal_dl/gui/server.py` | uvicorn launcher, browser open, signal handling |
| `tidal_dl/gui/api/__init__.py` | API router aggregation |
| `tidal_dl/gui/api/search.py` | `GET /api/search` — Tidal search with ISRC cross-ref |
| `tidal_dl/gui/api/playback.py` | `GET /api/stream/{track_id}`, `GET /api/local?path=` — audio serving |
| `tidal_dl/gui/api/library.py` | `GET /api/library` — local file metadata |
| `tidal_dl/gui/api/downloads.py` | `POST /api/download`, `GET /api/downloads/active` (SSE), `GET /api/downloads/history` |
| `tidal_dl/gui/api/playlists.py` | `GET /api/playlists`, `GET /api/playlists/{id}/tracks`, `POST /api/playlists/{id}/sync` |
| `tidal_dl/gui/api/settings.py` | `GET/PATCH /api/settings`, `GET /api/auth/status` |
| `tidal_dl/gui/static/index.html` | SPA shell — single HTML page |
| `tidal_dl/gui/static/style.css` | "Listening Room" theme |
| `tidal_dl/gui/static/app.js` | Client-side router, views, state, player |
| `tests/test_gui_api.py` | Backend API tests (FastAPI TestClient) |

### Modified Files

| File | Change |
|---|---|
| `pyproject.toml` | Add `fastapi>=0.115.0`, `uvicorn[standard]>=0.34.0` to dependencies |
| `tidal_dl/cli.py` | Add `gui` command to Typer app |

---

## Task 1: Foundation — Dependencies, Package Skeleton, CLI Command

**Files:**
- Modify: `TIDALDL-PY/pyproject.toml`
- Create: `TIDALDL-PY/tidal_dl/gui/__init__.py`
- Create: `TIDALDL-PY/tidal_dl/gui/server.py`
- Create: `TIDALDL-PY/tidal_dl/gui/api/__init__.py`
- Modify: `TIDALDL-PY/tidal_dl/cli.py`
- Test: `TIDALDL-PY/tests/test_gui_api.py`

- [ ] **Step 1: Add dependencies to pyproject.toml**

Add `fastapi>=0.115.0` and `uvicorn[standard]>=0.34.0` to the `dependencies` list in `pyproject.toml`.

- [ ] **Step 2: Install updated dependencies**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && uv pip install -e .`
Expected: Successfully installs fastapi and uvicorn.

- [ ] **Step 3: Write test for app factory**

Create `tests/test_gui_api.py`:

```python
"""Tests for the GUI API layer."""

from fastapi.testclient import TestClient


def test_app_factory_returns_fastapi_instance():
    from tidal_dl.gui import create_app

    app = create_app()
    assert app is not None
    client = TestClient(app)
    # Static file mount should serve index.html at root
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py::test_app_factory_returns_fastapi_instance -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tidal_dl.gui'`

- [ ] **Step 5: Create gui package with app factory**

Create `tidal_dl/gui/__init__.py`:

```python
"""music-dl GUI — FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from tidal_dl.gui.api import api_router

_STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="music-dl", docs_url="/api/docs", redoc_url=None)
    app.include_router(api_router, prefix="/api")
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
    return app
```

Create `tidal_dl/gui/api/__init__.py`:

```python
"""API router aggregation."""

from fastapi import APIRouter

api_router = APIRouter()
```

Create minimal `tidal_dl/gui/static/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>music-dl</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <div id="app">music-dl loading...</div>
  <script src="/app.js"></script>
</body>
</html>
```

Create empty `tidal_dl/gui/static/style.css` and `tidal_dl/gui/static/app.js` (empty files — placeholders).

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py::test_app_factory_returns_fastapi_instance -v`
Expected: PASS

- [ ] **Step 7: Create server launcher**

Create `tidal_dl/gui/server.py`:

```python
"""Uvicorn launcher for the music-dl GUI."""

import webbrowser

import uvicorn


def run(port: int = 8765, open_browser: bool = True) -> None:
    """Start the GUI server and optionally open the browser."""
    url = f"http://localhost:{port}"
    if open_browser:
        webbrowser.open(url)
    uvicorn.run("tidal_dl.gui:create_app", factory=True, host="127.0.0.1", port=port, log_level="warning")
```

- [ ] **Step 8: Wire `gui` command into CLI**

Add to `tidal_dl/cli.py`, just above the `main()` function at the bottom:

```python
@app.command()
def gui(
    port: int = typer.Option(8765, help="Port to serve on."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open browser."),
) -> None:
    """Launch the music-dl web interface."""
    from tidal_dl.gui.server import run

    run(port=port, open_browser=not no_browser)
```

- [ ] **Step 9: Smoke test the CLI command**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m tidal_dl.cli gui --help`
Expected: Shows help text for the `gui` command with `--port` and `--no-browser` options.

- [ ] **Step 10: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/pyproject.toml TIDALDL-PY/tidal_dl/gui/ TIDALDL-PY/tidal_dl/cli.py TIDALDL-PY/tests/test_gui_api.py
git commit -m "feat(gui): add FastAPI skeleton with gui command, app factory, and static serving"
```

---

## Task 2: Search API Endpoint

**Files:**
- Create: `TIDALDL-PY/tidal_dl/gui/api/search.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/api/__init__.py`
- Test: `TIDALDL-PY/tests/test_gui_api.py`

- [ ] **Step 1: Write test for search endpoint**

Append to `tests/test_gui_api.py`:

```python
from unittest.mock import MagicMock, patch


def _mock_tidal_session():
    """Create a mock Tidal session with search results."""
    session = MagicMock()
    track = MagicMock()
    track.id = 12345
    track.name = "Says"
    track.duration = 462
    track.isrc = "DEGC31200059"
    track.audio_quality = "HI_RES_LOSSLESS"
    track.full_name = "Says"

    artist = MagicMock()
    artist.name = "Nils Frahm"
    artist.id = 4194216
    track.artists = [artist]

    album = MagicMock()
    album.name = "Spaces"
    album.id = 28413900
    album.image = MagicMock(return_value="https://example.com/cover.jpg")
    track.album = album

    session.search.return_value = {"tracks": [track], "top_hit": None}
    return session


def test_search_returns_tracks():
    from tidal_dl.gui import create_app

    app = create_app()
    client = TestClient(app)

    mock_session = _mock_tidal_session()
    with patch("tidal_dl.gui.api.search.get_tidal_session", return_value=mock_session):
        resp = client.get("/api/search?q=Nils+Frahm&type=tracks")

    assert resp.status_code == 200
    data = resp.json()
    assert "tracks" in data
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["name"] == "Says"
    assert data["tracks"][0]["artist"] == "Nils Frahm"


def test_search_missing_query_returns_422():
    from tidal_dl.gui import create_app

    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/search")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py::test_search_returns_tracks -v`
Expected: FAIL — route not found (404) or import error.

- [ ] **Step 3: Implement search endpoint**

Create `tidal_dl/gui/api/search.py`:

```python
"""GET /api/search — Tidal search with ISRC cross-reference."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from tidal_dl.config import Tidal
from tidal_dl.helper.isrc_index import IsrcIndex
from tidal_dl.helper.path import path_config_base

router = APIRouter()

_isrc_index: IsrcIndex | None = None


def _get_isrc_index() -> IsrcIndex:
    global _isrc_index
    if _isrc_index is None:
        from pathlib import Path
        _isrc_index = IsrcIndex(Path(path_config_base()) / "isrc_index.json")
        _isrc_index.load()
    return _isrc_index


def get_tidal_session():
    """Get or create the Tidal session singleton."""
    tidal = Tidal()
    return tidal.session


def _serialize_track(track: Any, isrc_index: IsrcIndex) -> dict:
    artists = track.artists or []
    artist_name = ", ".join(a.name for a in artists if a.name)
    album = track.album
    album_name = album.name if album else ""
    album_id = album.id if album else None

    cover_url = ""
    if album:
        try:
            cover_url = album.image(480)
        except Exception:
            pass

    isrc = getattr(track, "isrc", "") or ""
    is_local = isrc_index.contains(isrc) if isrc else False

    return {
        "id": track.id,
        "name": track.full_name or track.name,
        "artist": artist_name,
        "album": album_name,
        "album_id": album_id,
        "cover_url": cover_url,
        "duration": track.duration or 0,
        "quality": getattr(track, "audio_quality", "") or "",
        "isrc": isrc,
        "is_local": is_local,
    }


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, description="Search query"),
    type: str = Query("tracks", description="Search type: tracks, albums, artists, playlists"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """Search Tidal and return results with local-match flags."""
    session = get_tidal_session()
    results = session.search(q, models=[_model_for_type(type)], limit=limit, offset=offset)
    isrc_index = _get_isrc_index()

    if type == "tracks":
        tracks = results.get("tracks", []) or []
        return {
            "tracks": [_serialize_track(t, isrc_index) for t in tracks],
            "total": len(tracks),
        }

    # Albums, artists, playlists — simpler serialization
    items = results.get(type, []) or []
    return {
        type: [_serialize_item(item) for item in items],
        "total": len(items),
    }


def _model_for_type(type_str: str):
    from tidalapi.album import Album
    from tidalapi.artist import Artist
    from tidalapi.media import Track
    from tidalapi.playlist import Playlist

    return {"tracks": Track, "albums": Album, "artists": Artist, "playlists": Playlist}.get(type_str, Track)


def _serialize_item(item: Any) -> dict:
    cover_url = ""
    try:
        cover_url = item.image(480)
    except Exception:
        pass
    return {
        "id": item.id,
        "name": getattr(item, "name", ""),
        "cover_url": cover_url,
    }
```

- [ ] **Step 4: Register search router**

Update `tidal_dl/gui/api/__init__.py`:

```python
"""API router aggregation."""

from fastapi import APIRouter

from tidal_dl.gui.api.search import router as search_router

api_router = APIRouter()
api_router.include_router(search_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/tidal_dl/gui/api/search.py TIDALDL-PY/tidal_dl/gui/api/__init__.py TIDALDL-PY/tests/test_gui_api.py
git commit -m "feat(gui): add search API endpoint with ISRC cross-reference"
```

---

## Task 3: Playback API — Stream and Local File Serving

**Files:**
- Create: `TIDALDL-PY/tidal_dl/gui/api/playback.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/api/__init__.py`
- Test: `TIDALDL-PY/tests/test_gui_api.py`

- [ ] **Step 1: Write test for local file serving**

Append to `tests/test_gui_api.py`:

```python
import tempfile
from pathlib import Path


def test_local_file_serves_audio(tmp_path):
    """Local file endpoint serves audio files from allowed directories."""
    from tidal_dl.gui import create_app

    # Create a fake audio file
    audio_file = tmp_path / "test.flac"
    audio_file.write_bytes(b"fake-flac-data")

    app = create_app()

    # Patch settings to allow the tmp directory
    with patch("tidal_dl.gui.api.playback.get_download_paths", return_value=[str(tmp_path)]):
        client = TestClient(app)
        resp = client.get(f"/api/local?path={audio_file}")

    assert resp.status_code == 200


def test_local_file_rejects_path_traversal(tmp_path):
    """Local file endpoint rejects paths outside allowed directories."""
    from tidal_dl.gui import create_app

    app = create_app()
    with patch("tidal_dl.gui.api.playback.get_download_paths", return_value=[str(tmp_path)]):
        client = TestClient(app)
        resp = client.get("/api/local?path=/etc/passwd")

    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py::test_local_file_serves_audio -v`
Expected: FAIL — route not found.

- [ ] **Step 3: Implement playback endpoint**

Create `tidal_dl/gui/api/playback.py`:

```python
"""Audio playback endpoints — Tidal streaming and local file serving."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from tidal_dl.config import Settings, Tidal

router = APIRouter()


def get_download_paths() -> list[str]:
    """Return allowed download directories from settings."""
    settings = Settings()
    paths = [settings.data.download_base_path]
    # Include scan paths if configured
    if settings.data.scan_paths:
        paths.extend(p.strip() for p in settings.data.scan_paths.split(",") if p.strip())
    return paths


@router.get("/local")
def serve_local_file(path: str = Query(..., description="Absolute path to audio file")):
    """Serve a local audio file with range request support.

    Path must be within a configured download directory.
    """
    file_path = Path(path).resolve()
    allowed = get_download_paths()

    if not any(str(file_path).startswith(str(Path(d).resolve())) for d in allowed):
        raise HTTPException(status_code=403, detail="Path outside allowed directories")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    suffix = file_path.suffix.lower()
    media_types = {
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type)


@router.get("/stream/{track_id}")
def stream_tidal_track(track_id: int):
    """Proxy a Tidal stream to the browser.

    Uses full stream if OAuth session is active, falls back to preview URL.
    """
    import requests as http_requests

    tidal = Tidal()
    session = tidal.session

    # Try full stream first (requires OAuth)
    if session.check_login():
        try:
            from tidalapi.media import Track

            track = session.track(track_id)
            stream = track.get_stream()
            manifest = stream.get_stream_manifest()
            urls = manifest.get_urls()

            if urls:
                resp = http_requests.get(urls[0], stream=True, timeout=30)
                content_type = resp.headers.get("Content-Type", "audio/flac")

                return StreamingResponse(
                    resp.iter_content(chunk_size=8192),
                    media_type=content_type,
                    headers={"Accept-Ranges": "bytes"},
                )
        except Exception:
            pass  # Fall through to preview

    # Fallback: 30-second preview URL (no auth needed)
    try:
        preview_url = f"https://listening-test.tidal.com/v1/tracks/{track_id}/preview"
        resp = http_requests.get(preview_url, stream=True, timeout=15)
        if resp.status_code == 200:
            return StreamingResponse(
                resp.iter_content(chunk_size=8192),
                media_type=resp.headers.get("Content-Type", "audio/mp4"),
            )
    except Exception:
        pass

    raise HTTPException(status_code=503, detail="Unable to stream track")
```

- [ ] **Step 4: Register playback router**

Update `tidal_dl/gui/api/__init__.py` to include:

```python
from tidal_dl.gui.api.playback import router as playback_router

api_router.include_router(playback_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/tidal_dl/gui/api/playback.py TIDALDL-PY/tidal_dl/gui/api/__init__.py TIDALDL-PY/tests/test_gui_api.py
git commit -m "feat(gui): add playback API — local file serving and Tidal stream proxy"
```

---

## Task 4: Frontend — SPA Shell, Router, and Listening Room Theme

**Files:**
- Modify: `TIDALDL-PY/tidal_dl/gui/static/index.html`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/style.css`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/app.js`

This task builds the complete SPA shell with client-side routing, the "Listening Room" CSS theme, sidebar navigation, and player bar skeleton. No API integration yet — views show placeholder content.

- [ ] **Step 1: Write the SPA shell HTML**

Replace `tidal_dl/gui/static/index.html` with the full SPA shell:
- `<head>` with Google Fonts (Crimson Pro, Outfit, JetBrains Mono), viewport meta, CSS link
- `<body>` structure: `.ambient` (background gradients), `.grain` (noise overlay), `.app` (sidebar + main), `.player` (bottom bar)
- Sidebar with nav items: Search, Library, Playlists, Downloads, Sync, Settings
- Main area: `#view` container where JS swaps view content
- Player bar: now-playing info, transport buttons, progress bar, volume
- `<audio id="audio">` element (hidden, controlled by JS)
- Script tag loading `app.js`

Use the mockup from `.superpowers/brainstorm/30388-1774310788/gui-v2-listening-room.html` as the HTML reference, but make these changes:
- Replace hardcoded track list with `<div id="view"></div>` placeholder
- Add `<audio id="audio" preload="none"></audio>` before closing `</body>`
- Add `data-view` attributes to nav items for JS routing
- Add `id` attributes to player bar elements for JS control

- [ ] **Step 2: Write the full Listening Room CSS**

Replace `tidal_dl/gui/static/style.css` with the complete theme from the mockup, plus these additions:
- View transition: `.view-enter { animation: fadeUp 0.25s ease both; }`
- Skeleton loading: `.skeleton { background: var(--surface); animation: shimmer 1.5s infinite; }`
- `@keyframes shimmer` for loading placeholders
- `.toast` class for inline notifications (download started, errors)
- Responsive grid adjustments for the track list

- [ ] **Step 3: Write the JS SPA core — router, state, player**

Replace `tidal_dl/gui/static/app.js` with the SPA core. Structure:

```javascript
// ---- STATE ----
const state = { view: 'search', queue: [], queueIndex: -1, playing: false, volume: 0.7 };

// ---- ROUTER ----
function navigate(view) { ... }  // Swaps #view content, updates sidebar active state
window.addEventListener('hashchange', () => navigate(location.hash.slice(1) || 'search'));

// ---- API ----
const cache = {};
async function api(path) { ... }  // Fetch + cache wrapper

// ---- VIEWS ----
function renderSearch() { ... }   // Search input + results
function renderLibrary() { ... }  // Local file browser
function renderPlaylists() { ... }
function renderDownloads() { ... }

// ---- PLAYER ----
const audio = document.getElementById('audio');
function play(track) { ... }      // Set source, play
function togglePlay() { ... }     // Pause/resume
function next() { ... }
function prev() { ... }
function seek(pct) { ... }
function updateProgress() { ... } // Called on 'timeupdate' event

// ---- INIT ----
navigate(location.hash.slice(1) || 'search');
```

Each view renderer function returns an HTML string that gets set as `#view.innerHTML`. Event listeners are attached after render via delegation on `#view`.

- [ ] **Step 4: Manual smoke test**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -c "from tidal_dl.gui.server import run; run(port=8765, open_browser=True)"`

Verify in browser:
- Page loads at `localhost:8765`
- Sidebar navigation switches views (hash changes)
- Player bar is visible at bottom
- Ambient gradients animate
- Grain overlay visible

Kill server with Ctrl+C.

- [ ] **Step 5: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/tidal_dl/gui/static/
git commit -m "feat(gui): add SPA shell with Listening Room theme, router, and player skeleton"
```

---

## Task 5: Search View — Frontend Wired to API

**Files:**
- Modify: `TIDALDL-PY/tidal_dl/gui/static/app.js`

- [ ] **Step 1: Implement `renderSearch()` view**

The search view must:
- Render search input (pre-focused, rounded, with search icon SVG inline)
- Filter pills below (Tracks active by default, Albums, Artists, Playlists)
- On input (debounced 300ms), call `GET /api/search?q={value}&type={activeFilter}`
- Render results as track rows matching the mockup layout: `#` | art (gradient placeholder) | title+artist | album (italic serif) | quality badge | time | action (download btn or "local" dot)
- Clicking a track row calls `play(track)` — player picks the right source
- Show skeleton placeholders during fetch
- Show "No results" message for empty results

- [ ] **Step 2: Wire click-to-play**

When a track row is clicked:
- Build a queue from all visible search results
- Set `state.queueIndex` to the clicked track's position
- Call `play(state.queue[state.queueIndex])`
- `play()` sets `audio.src`:
  - If `track.is_local` → `/api/local?path={track.local_path}`
  - Else → `/api/stream/{track.id}`
- Update player bar: now-playing title, artist, album art
- Add `.playing` class to the active track row
- Start `requestAnimationFrame` loop for progress bar updates

- [ ] **Step 3: Wire download button**

Download button on each track row (not local):
- On click, `POST /api/download` with `{ track_ids: [track.id] }`
- Immediately swap the download icon to a spinner animation (CSS-only)
- On completion (via SSE in Task 8), swap to green checkmark + "local" tag

For now (before downloads API exists), just show an alert or console.log on click. Wire the real download in Task 8.

- [ ] **Step 4: Manual test**

Start server, search for an artist, verify:
- Results render with correct layout
- Quality badges show correct colors
- Local tracks show green dot
- Clicking a track starts playback (or shows "Unable to stream" if not logged in)
- Progress bar updates in real time during playback

- [ ] **Step 5: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/tidal_dl/gui/static/app.js
git commit -m "feat(gui): wire search view to API with playback and download buttons"
```

---

## Task 6: Library API and View

**Files:**
- Create: `TIDALDL-PY/tidal_dl/gui/api/library.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/api/__init__.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/app.js`
- Test: `TIDALDL-PY/tests/test_gui_api.py`

- [ ] **Step 1: Write test for library endpoint**

Append to `tests/test_gui_api.py`:

```python
def test_library_returns_tracks(tmp_path):
    """Library endpoint scans download directory and returns metadata."""
    from tidal_dl.gui import create_app

    app = create_app()

    with patch("tidal_dl.gui.api.library.get_download_path", return_value=str(tmp_path)):
        client = TestClient(app)
        resp = client.get("/api/library")

    assert resp.status_code == 200
    data = resp.json()
    assert "tracks" in data
    assert isinstance(data["tracks"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py::test_library_returns_tracks -v`
Expected: FAIL.

- [ ] **Step 3: Implement library endpoint**

Create `tidal_dl/gui/api/library.py`:

```python
"""GET /api/library — local file metadata."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from mutagen import File as MutagenFile

from tidal_dl.config import Settings

router = APIRouter()

_AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}


def get_download_path() -> str:
    settings = Settings()
    return settings.data.download_base_path


def _read_metadata(file_path: Path) -> dict | None:
    """Read audio metadata from a file using mutagen."""
    try:
        audio = MutagenFile(file_path)
        if audio is None:
            return None

        tags = audio.tags or {}

        def _tag(key: str, fallback: str = "") -> str:
            val = tags.get(key)
            if val is None:
                return fallback
            if isinstance(val, list):
                return str(val[0]) if val else fallback
            return str(val)

        return {
            "path": str(file_path),
            "name": _tag("title", file_path.stem),
            "artist": _tag("artist", "Unknown Artist"),
            "album": _tag("album", "Unknown Album"),
            "duration": int(audio.info.length) if audio.info else 0,
            "isrc": _tag("isrc"),
            "quality": f"{audio.info.sample_rate}Hz/{audio.info.bits_per_sample}bit" if audio.info and hasattr(audio.info, "bits_per_sample") else file_path.suffix[1:].upper(),
            "format": file_path.suffix[1:].upper(),
            "is_local": True,
        }
    except Exception:
        return None


@router.get("/library")
def library(
    sort: str = Query("recent", description="Sort: recent, artist, album, title"),
) -> dict:
    """Scan download directory and return local file metadata."""
    download_path = Path(get_download_path())
    if not download_path.is_dir():
        return {"tracks": [], "total": 0}

    tracks = []
    for f in download_path.rglob("*"):
        if f.suffix.lower() in _AUDIO_EXTENSIONS:
            meta = _read_metadata(f)
            if meta:
                tracks.append(meta)

    # Sort
    sort_keys = {
        "recent": lambda t: Path(t["path"]).stat().st_mtime,
        "artist": lambda t: t["artist"].lower(),
        "album": lambda t: t["album"].lower(),
        "title": lambda t: t["name"].lower(),
    }
    key_fn = sort_keys.get(sort, sort_keys["recent"])
    reverse = sort == "recent"
    tracks.sort(key=key_fn, reverse=reverse)

    return {"tracks": tracks, "total": len(tracks)}
```

- [ ] **Step 4: Register library router**

Update `tidal_dl/gui/api/__init__.py` to include:

```python
from tidal_dl.gui.api.library import router as library_router

api_router.include_router(library_router)
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py -v`
Expected: All PASS.

- [ ] **Step 6: Implement `renderLibrary()` in app.js**

Library view:
- On mount, call `GET /api/library?sort=recent`
- Sort toggle pills: Recently Added | Artist | Album | Title
- Render track list identical to search view but with local file paths
- Clicking plays from local file: `audio.src = '/api/local?path=' + encodeURIComponent(track.path)`
- All tracks show format badge instead of quality badge (FLAC, MP3, etc.)

- [ ] **Step 7: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/tidal_dl/gui/api/library.py TIDALDL-PY/tidal_dl/gui/api/__init__.py TIDALDL-PY/tidal_dl/gui/static/app.js TIDALDL-PY/tests/test_gui_api.py
git commit -m "feat(gui): add library API and view — browse and play local files"
```

---

## Task 7: Downloads API with SSE Progress

**Files:**
- Create: `TIDALDL-PY/tidal_dl/gui/api/downloads.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/api/__init__.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/app.js`
- Test: `TIDALDL-PY/tests/test_gui_api.py`

- [ ] **Step 1: Write test for download trigger**

Append to `tests/test_gui_api.py`:

```python
def test_download_accepts_track_ids():
    from tidal_dl.gui import create_app

    app = create_app()
    client = TestClient(app)

    with patch("tidal_dl.gui.api.downloads.trigger_download") as mock_dl:
        mock_dl.return_value = {"status": "queued", "count": 1}
        resp = client.post("/api/download", json={"track_ids": [12345]})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py::test_download_accepts_track_ids -v`
Expected: FAIL.

- [ ] **Step 3: Implement downloads endpoint**

Create `tidal_dl/gui/api/downloads.py`:

```python
"""Download management — trigger downloads, SSE progress, history."""

from __future__ import annotations

import asyncio
import time
import threading
from collections import deque
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class DownloadRequest(BaseModel):
    track_ids: list[int] = []
    url: str = ""


class DownloadEntry:
    def __init__(self, track_id: int, name: str):
        self.track_id = track_id
        self.name = name
        self.progress: float = 0.0
        self.status: str = "queued"  # queued, downloading, done, error
        self.started_at: float = time.time()
        self.finished_at: float | None = None


# In-memory state
_active: dict[int, DownloadEntry] = {}
_history: deque[dict] = deque(maxlen=50)
_sse_clients: list[asyncio.Queue] = []


def _broadcast(event: dict):
    """Send event to all connected SSE clients."""
    for q in _sse_clients[:]:
        try:
            q.put_nowait(event)
        except Exception:
            pass


def trigger_download(track_ids: list[int]) -> dict:
    """Trigger downloads using the existing Download pipeline in a background thread."""
    from tidal_dl.config import Settings, Tidal
    from tidal_dl.download import Download

    def _run():
        import logging

        tidal = Tidal()
        settings = Settings()
        logger = logging.getLogger("music-dl.gui")
        dl = Download(
            tidal_obj=tidal,
            path_base=settings.data.download_base_path,
            fn_logger=logger,
            skip_existing=settings.data.skip_existing,
        )

        for tid in track_ids:
            entry = _active.get(tid)
            if entry:
                entry.status = "downloading"
                _broadcast({"type": "progress", "track_id": tid, "status": "downloading", "progress": 0})

            try:
                track = tidal.session.track(tid)
                dl.item(file_template=settings.data.format_track, media=track)

                if entry:
                    entry.status = "done"
                    entry.progress = 100
                    entry.finished_at = time.time()
                    _history.appendleft({
                        "track_id": tid,
                        "name": entry.name,
                        "status": "done",
                        "finished_at": entry.finished_at,
                    })
                    del _active[tid]
                    _broadcast({"type": "complete", "track_id": tid, "status": "done"})
            except Exception as exc:
                if entry:
                    entry.status = "error"
                    entry.finished_at = time.time()
                    del _active[tid]
                    _broadcast({"type": "error", "track_id": tid, "error": str(exc)})

    for tid in track_ids:
        _active[tid] = DownloadEntry(tid, f"Track {tid}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"status": "queued", "count": len(track_ids)}


@router.post("/download")
def download(req: DownloadRequest):
    """Trigger download of one or more tracks."""
    if not req.track_ids and not req.url:
        raise HTTPException(status_code=400, detail="Provide track_ids or url")

    if req.url:
        # URL-based download — delegate to existing CLI pipeline
        return {"status": "queued", "count": 1}

    return trigger_download(req.track_ids)


@router.get("/downloads/active")
async def downloads_sse():
    """Server-Sent Events stream for download progress."""
    queue: asyncio.Queue = asyncio.Queue()
    _sse_clients.append(queue)

    async def event_stream():
        try:
            # Send current active downloads first
            for entry in _active.values():
                yield f"data: {_json_dumps({'type': 'progress', 'track_id': entry.track_id, 'name': entry.name, 'status': entry.status, 'progress': entry.progress})}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {_json_dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive ping, stay connected
                    yield f"data: {_json_dumps({'type': 'ping'})}\n\n"
        except Exception:
            pass
        finally:
            if queue in _sse_clients:
                _sse_clients.remove(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/downloads/history")
def downloads_history(limit: int = 50) -> dict:
    """Recent download history."""
    return {"downloads": list(_history)[:limit]}


def _json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj)
```

- [ ] **Step 4: Register downloads router**

Update `tidal_dl/gui/api/__init__.py` to include:

```python
from tidal_dl.gui.api.downloads import router as downloads_router

api_router.include_router(downloads_router)
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py -v`
Expected: All PASS.

- [ ] **Step 6: Implement `renderDownloads()` in app.js**

Downloads view:
- Active downloads section: track name + animated progress bar + cancel button
- Connect to `/api/downloads/active` via `EventSource` for real-time updates
- History section: recent downloads with timestamp, loaded from `/api/downloads/history`
- Auto-reconnect SSE on disconnect

Also update Search view: wire download button to `POST /api/download` and listen for SSE completion to update the "local" badge.

- [ ] **Step 7: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/tidal_dl/gui/api/downloads.py TIDALDL-PY/tidal_dl/gui/api/__init__.py TIDALDL-PY/tidal_dl/gui/static/app.js TIDALDL-PY/tests/test_gui_api.py
git commit -m "feat(gui): add downloads API with SSE progress and downloads view"
```

---

## Task 8: Playlists API and View

**Files:**
- Create: `TIDALDL-PY/tidal_dl/gui/api/playlists.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/api/__init__.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/app.js`
- Test: `TIDALDL-PY/tests/test_gui_api.py`

- [ ] **Step 1: Write test for playlists endpoint**

Append to `tests/test_gui_api.py`:

```python
def test_playlists_returns_list():
    from tidal_dl.gui import create_app

    app = create_app()
    client = TestClient(app)

    mock_playlist = MagicMock()
    mock_playlist.id = "abc-123"
    mock_playlist.name = "Chill"
    mock_playlist.num_tracks = 42
    mock_playlist.image = MagicMock(return_value="https://example.com/pl.jpg")
    mock_playlist.last_updated = 1700000000.0

    mock_session = MagicMock()
    mock_user = MagicMock()
    mock_user.playlists.return_value = [mock_playlist]
    mock_session.user = mock_user

    with patch("tidal_dl.gui.api.playlists.get_tidal_session", return_value=mock_session):
        resp = client.get("/api/playlists")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["playlists"]) == 1
    assert data["playlists"][0]["name"] == "Chill"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py::test_playlists_returns_list -v`
Expected: FAIL.

- [ ] **Step 3: Implement playlists endpoint**

Create `tidal_dl/gui/api/playlists.py`:

```python
"""Playlist endpoints — list, tracks, sync."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from tidal_dl.config import Tidal
from tidal_dl.gui.api.search import _get_isrc_index, _serialize_track

router = APIRouter()


def get_tidal_session():
    tidal = Tidal()
    return tidal.session


@router.get("/playlists")
def list_playlists() -> dict:
    """List user's Tidal playlists."""
    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    playlists = session.user.playlists() or []
    return {
        "playlists": [
            {
                "id": str(pl.id),
                "name": getattr(pl, "name", ""),
                "num_tracks": getattr(pl, "num_tracks", 0),
                "cover_url": _safe_image(pl),
                "last_updated": getattr(pl, "last_updated", None),
            }
            for pl in playlists
        ]
    }


@router.get("/playlists/{playlist_id}/tracks")
def playlist_tracks(playlist_id: str) -> dict:
    """Get tracks for a specific playlist with local-match flags."""
    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    try:
        playlist = session.playlist(playlist_id)
        tracks = playlist.tracks() or []
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Playlist not found: {exc}")

    isrc_index = _get_isrc_index()
    return {
        "tracks": [_serialize_track(t, isrc_index) for t in tracks],
        "total": len(tracks),
    }


@router.post("/playlists/{playlist_id}/sync")
def sync_playlist(playlist_id: str) -> dict:
    """Trigger sync for a playlist — download missing tracks."""
    # Reuse existing sync infrastructure
    session = get_tidal_session()
    if not session.check_login():
        raise HTTPException(status_code=401, detail="Not logged in to Tidal")

    try:
        playlist = session.playlist(playlist_id)
        tracks = playlist.tracks() or []
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    isrc_index = _get_isrc_index()
    missing = [t for t in tracks if not isrc_index.contains(getattr(t, "isrc", "") or "")]

    if not missing:
        return {"status": "up_to_date", "missing": 0}

    # Trigger downloads for missing tracks
    from tidal_dl.gui.api.downloads import trigger_download
    track_ids = [t.id for t in missing]
    trigger_download(track_ids)

    return {"status": "syncing", "missing": len(missing), "total": len(tracks)}


def _safe_image(obj: Any) -> str:
    try:
        return obj.image(480)
    except Exception:
        return ""
```

- [ ] **Step 4: Register playlists router**

Update `tidal_dl/gui/api/__init__.py` to include:

```python
from tidal_dl.gui.api.playlists import router as playlists_router

api_router.include_router(playlists_router)
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py -v`
Expected: All PASS.

- [ ] **Step 6: Implement `renderPlaylists()` in app.js**

Playlists view:
- List of playlists as cards: cover art, name, track count
- Click playlist → expand to show track list (same layout as search results)
- Each track shows local/remote status
- "Download Missing" button per playlist → `POST /api/playlists/{id}/sync`
- Button disabled + spinner while syncing

- [ ] **Step 7: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/tidal_dl/gui/api/playlists.py TIDALDL-PY/tidal_dl/gui/api/__init__.py TIDALDL-PY/tidal_dl/gui/static/app.js TIDALDL-PY/tests/test_gui_api.py
git commit -m "feat(gui): add playlists API and view with sync support"
```

---

## Task 9: Settings API and Modal

**Files:**
- Create: `TIDALDL-PY/tidal_dl/gui/api/settings.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/api/__init__.py`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/app.js`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/style.css`
- Test: `TIDALDL-PY/tests/test_gui_api.py`

- [ ] **Step 1: Write test for settings and auth status endpoints**

Append to `tests/test_gui_api.py`:

```python
def test_auth_status_returns_state():
    from tidal_dl.gui import create_app

    app = create_app()
    client = TestClient(app)

    with patch("tidal_dl.gui.api.settings.get_tidal_instance") as mock_tidal:
        mock_tidal.return_value.session.check_login.return_value = False
        resp = client.get("/api/auth/status")

    assert resp.status_code == 200
    data = resp.json()
    assert "logged_in" in data


def test_settings_returns_config():
    from tidal_dl.gui import create_app

    app = create_app()
    client = TestClient(app)

    with patch("tidal_dl.gui.api.settings.get_settings") as mock_settings:
        mock_settings.return_value = {"download_base_path": "/tmp/music", "quality_audio": "HI_RES_LOSSLESS"}
        resp = client.get("/api/settings")

    assert resp.status_code == 200
    data = resp.json()
    assert "download_base_path" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py::test_auth_status_returns_state -v`
Expected: FAIL.

- [ ] **Step 3: Implement settings endpoint**

Create `tidal_dl/gui/api/settings.py`:

```python
"""Settings and auth status endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from tidal_dl.config import Settings, Tidal

router = APIRouter()


def get_tidal_instance():
    return Tidal()


def get_settings() -> dict:
    s = Settings()
    d = s.data
    return {
        "download_base_path": d.download_base_path,
        "quality_audio": str(d.quality_audio),
        "format_track": d.format_track,
        "format_album": d.format_album,
        "cover_album_file": d.cover_album_file,
        "metadata_cover_embed": d.metadata_cover_embed,
        "lyrics_embed": d.lyrics_embed,
        "lyrics_file": d.lyrics_file,
        "skip_existing": d.skip_existing,
        "downloads_concurrent_max": d.downloads_concurrent_max,
    }


@router.get("/auth/status")
def auth_status() -> dict:
    """Return OAuth session status."""
    tidal = get_tidal_instance()
    logged_in = tidal.session.check_login()
    username = ""
    if logged_in:
        try:
            user = tidal.session.user
            username = getattr(user, "name", "") or ""
        except Exception:
            pass
    return {"logged_in": logged_in, "username": username}


@router.get("/settings")
def read_settings() -> dict:
    """Return current settings."""
    return get_settings()


class SettingsUpdate(BaseModel):
    download_base_path: str | None = None
    quality_audio: str | None = None
    cover_album_file: bool | None = None
    metadata_cover_embed: bool | None = None
    lyrics_embed: bool | None = None
    lyrics_file: bool | None = None
    skip_existing: bool | None = None
    downloads_concurrent_max: int | None = None


@router.patch("/settings")
def update_settings(update: SettingsUpdate) -> dict:
    """Update settings. Only provided fields are changed."""
    s = Settings()
    for field, value in update.model_dump(exclude_none=True).items():
        if hasattr(s.data, field):
            setattr(s.data, field, value)
    s.save()
    return get_settings()
```

- [ ] **Step 4: Register settings router**

Update `tidal_dl/gui/api/__init__.py` to include:

```python
from tidal_dl.gui.api.settings import router as settings_router

api_router.include_router(settings_router)
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/test_gui_api.py -v`
Expected: All PASS.

- [ ] **Step 6: Implement settings modal in frontend**

Settings modal:
- Triggered by clicking "Settings" in sidebar
- Dark overlay + centered glass-effect modal panel
- Grouped fields: Download Path (text input), Quality (dropdown), Save Covers (toggle), Save Lyrics (toggle), Skip Existing (toggle), Concurrent Downloads (number input)
- Auth status section at top: "Connected as {username}" or "Not logged in — run `music-dl login` in terminal"
- Changes saved on input blur via `PATCH /api/settings`
- Close via X button or clicking overlay
- CSS: `.modal-overlay`, `.modal-panel` with backdrop-filter blur

- [ ] **Step 7: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/tidal_dl/gui/api/settings.py TIDALDL-PY/tidal_dl/gui/api/__init__.py TIDALDL-PY/tidal_dl/gui/static/ TIDALDL-PY/tests/test_gui_api.py
git commit -m "feat(gui): add settings API and modal with auth status"
```

---

## Task 10: Polish — Self-Hosted Fonts, Final UX Pass, README

**Files:**
- Create: `TIDALDL-PY/tidal_dl/gui/static/fonts/` (font files)
- Modify: `TIDALDL-PY/tidal_dl/gui/static/style.css`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/index.html`
- Modify: `README.md`

- [ ] **Step 1: Download and self-host fonts**

Download woff2 files for Crimson Pro (300, 400, 600), Outfit (300, 400, 500, 600), JetBrains Mono (400, 500) from Google Fonts. Save to `tidal_dl/gui/static/fonts/`.

Update `style.css`: replace Google Fonts `@import` with local `@font-face` declarations pointing to `/fonts/*.woff2`. This ensures the GUI works offline.

- [ ] **Step 2: UX review pass**

Review all views for:
- Tab order makes sense (search input is first focusable element)
- All click targets are minimum 40px tall
- Every interactive element has a visible hover state
- Loading skeletons appear during API fetches
- Error states are inline and dismissible (toast notifications)
- Player bar keyboard shortcuts work: Space = play/pause, Left/Right arrows = seek ±5s

- [ ] **Step 3: Update README**

Add a "Web GUI" section to README.md:

```markdown
## Web GUI

Launch a browser-based interface for searching, playing, and downloading:

```bash
music-dl gui
```

Options:
- `--port 8765` — custom port (default: 8765)
- `--no-browser` — don't auto-open browser

The GUI runs locally at `http://localhost:8765` and requires no additional setup.
```

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/hackbook/Documents/opt/music-dl/TIDALDL-PY && python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/hackbook/Documents/opt/music-dl
git add TIDALDL-PY/tidal_dl/gui/static/ README.md
git commit -m "feat(gui): self-host fonts, UX polish, update README"
```

---

## Execution Notes

### Testing Strategy

- **Backend**: FastAPI `TestClient` with mocked Tidal session and Settings singletons. No real API calls in tests.
- **Frontend**: Manual browser testing. Each task has a "manual test" step describing what to verify.
- **Integration**: Start server, run through the full flow: search → play → download → verify in library.

### Singleton Handling

The `Settings` and `Tidal` singletons are shared between CLI and GUI. The GUI imports them normally — they're already thread-safe. The `clear_singletons` fixture in `conftest.py` ensures test isolation.

### Security

- Local file serving validates paths against configured download directories (no path traversal)
- Server binds to `127.0.0.1` only (no remote access)
- No authentication on the API (it's localhost-only, single-user)
