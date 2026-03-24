# music-dl GUI — Design Specification

**Date:** 2026-03-23
**Status:** Draft
**Concept:** "Listening Room" — browser-based GUI for music-dl

---

## 1. Overview

A browser-based GUI launched via `music-dl gui` that starts a local web server and opens `localhost:PORT` in the default browser. Combines Tidal search + download with local library playback in a single, unified interface.

### Core Principles

- **Granny-friendly UX** — zero learning curve, big click targets, obvious affordances, instant feedback on every action. No jargon in the UI. If it needs a tooltip to explain, it's designed wrong.
- **Responsive navigation** — client-side SPA with instant view transitions. No page reloads. Cached API responses mean revisiting a view feels like it never left.
- **Minimal footprint** — 2 new Python dependencies (FastAPI + uvicorn). Frontend is vanilla HTML/CSS/JS with zero build step.
- **Reuse everything** — the GUI is a thin layer over existing music-dl infrastructure. Search uses `tidalapi`, downloads use `Download` class, ISRC cross-referencing uses `isrc_index`, config uses existing singletons.

---

## 2. Visual Design — "Listening Room"

### Aesthetic Direction

Warm dark theme inspired by a listening room at night. The UI recedes; the music dominates.

### Color Palette

| Token | Value | Usage |
|---|---|---|
| `--bg` | `#0f0e0d` | Page background — warm charcoal, not cold black |
| `--bg-warm` | `#161413` | Elevated surfaces |
| `--surface` | `rgba(255, 245, 235, 0.04)` | Cards, inputs, interactive areas |
| `--surface-hover` | `rgba(255, 245, 235, 0.07)` | Hover state |
| `--glass` | `rgba(22, 20, 19, 0.75)` | Player bar — frosted glass |
| `--glass-border` | `rgba(255, 245, 235, 0.06)` | Subtle dividers |
| `--text` | `#f0ebe4` | Primary text — warm white |
| `--text-secondary` | `rgba(240, 235, 228, 0.50)` | Secondary labels |
| `--text-muted` | `rgba(240, 235, 228, 0.25)` | Timestamps, column headers |
| `--accent` | `#d4a053` | Primary accent — warm gold |
| `--green` | `#7ec97a` | "Local" indicators, connection status |

### Typography

| Role | Font | Weight | Size |
|---|---|---|---|
| Display / track titles | Crimson Pro (serif) | 300–400 | 15–28px |
| Body / labels | Outfit (sans) | 300–500 | 12–14px |
| Mono / timestamps | JetBrains Mono | 400–500 | 9–12px |

### Atmosphere Effects

- **Ambient gradients** — two slow-drifting radial gradients (purple + amber) behind the entire UI, animated over 12–15s cycles
- **Film grain overlay** — SVG fractal noise at 2.5% opacity for analog texture
- **Album art glow** — now-playing artwork radiates a soft ambient light behind it via blurred pseudo-element
- **Waveform progress bar** — procedurally generated waveform visualization inside the seekable progress bar, visible on hover
- **Equalizer animation** — four animated bars on the currently playing track row
- **Staggered entrance** — track rows fade up sequentially on view load (30ms delay per row)

### UX Requirements

- **Click targets** — minimum 40px height for all interactive rows, 34px for buttons
- **Hover states** — every clickable element has a visible hover change (background, color, or scale)
- **Loading feedback** — skeleton placeholders during API fetches, never a blank screen
- **Download feedback** — click download icon, it immediately becomes a progress indicator (spinner or fill animation), then a checkmark on completion
- **Error states** — inline, contextual, dismissible. Never a modal error for a recoverable problem.
- **Keyboard accessible** — space = play/pause, arrow keys = seek/volume, tab navigation through interactive elements

---

## 3. Architecture

### Backend

**Framework:** FastAPI (ASGI)
**Server:** uvicorn
**Pattern:** JSON API + static file serving

FastAPI was chosen because:
- Same author as Typer (consistent ecosystem)
- Async-native (non-blocking audio streaming)
- Auto-generated OpenAPI docs for debugging
- Minimal overhead (~1MB)

### Frontend

**Framework:** None — vanilla HTML/CSS/JS
**Routing:** Client-side hash router (~30 lines)
**State:** Simple JS module with event emitter pattern
**Rendering:** Direct DOM manipulation (no virtual DOM)

At 5 views and ~20 interactive elements, a framework adds organizational overhead without solving real problems. The entire frontend JS should be under 2000 lines.

### Audio Playback

**Engine:** HTML5 `<audio>` element (browser-native)
**Supported formats:** FLAC, MP3, AAC/M4A, OGG, WAV (browser-dependent)
**Local files:** FastAPI serves from download directory via range-request-capable endpoint
**Tidal streams:** Backend proxies authenticated stream URL to frontend `<audio>` element

Playback strategy:
1. If OAuth session exists → stream full track from Tidal
2. If no OAuth → fall back to 30-second preview URLs (no auth required)
3. Local files always play in full

### Data Flow

```
Browser (SPA)
  ↕ JSON API (fetch + cache)
FastAPI Server
  ↕ tidalapi (search, stream URLs)
  ↕ filesystem (local library, config)
  ↕ Download class (download pipeline)
  ↕ ISRC index (cross-reference)
```

---

## 4. Views

### 4.1 Search View (default)

**Purpose:** Search Tidal, preview tracks, download what you want.

**Layout:**
- Search input (rounded, full-width) with filter pills below (Tracks | Albums | Artists | Playlists)
- Results title with count
- Track list: # | Art | Title+Artist | Album | Quality | Time | Actions
- Quality badges: Master (gold), FLAC (blue), Hi-Res (green)
- Actions per track:
  - Download button (arrow icon) — for tracks not in local library
  - "local" indicator (green dot + text) — for tracks matching ISRC index
- Clicking a track row starts playback

**Data source:** `tidalapi.Session.search()`
**ISRC cross-reference:** Check each result ISRC against `isrc_index.json` to show local status

### 4.2 Library View

**Purpose:** Browse and play your downloaded music collection.

**Layout:**
- Toggle: Albums grid | Tracks list
- Albums grid: cover art cards with album name + artist, click to expand track list
- Tracks list: same format as Search but with local metadata (from mutagen)
- Sort options: recently added, artist, album, title

**Data source:** Scan configured download directory, read metadata via mutagen
**Caching:** Library scan results cached in memory on first load, refreshed on download completion

### 4.3 Playlists View

**Purpose:** Browse Tidal playlists, see what you have locally, download missing tracks.

**Layout:**
- List of Tidal playlists (name, track count, last modified)
- Click playlist → track list with local/remote status per track
- "Download missing" button per playlist (uses existing sync infrastructure)

**Data source:** `tidalapi.Session.user.playlists()` + ISRC cross-reference

### 4.4 Downloads View

**Purpose:** See what's downloading and what recently completed.

**Layout:**
- Active downloads: track name, progress bar (percentage + speed), cancel button
- Recent downloads: last 50, showing track name, album, quality, timestamp
- Download progress via Server-Sent Events (SSE) for real-time updates without polling

**Data source:** In-memory download manager state, exposed via SSE endpoint

### 4.5 Settings (Modal)

**Purpose:** Configure music-dl without touching the CLI.

**Layout:**
- Modal overlay triggered from sidebar
- Grouped settings: Download (quality, path template, concurrency), Account (login/logout status), Sources (HiFi API instances)
- Maps 1:1 to existing `cfg` command options
- Changes persist immediately via existing `Settings` singleton

**Data source:** `Settings` singleton (read/write)

---

## 5. Player Bar

Persistent bottom bar, visible on all views. 96px tall, frosted glass background with backdrop blur.

### Layout (3-column grid)

**Left (300px):** Now-playing — album art (60px, with ambient glow) + track title + artist/album

**Center (flex):** Transport controls + progress
- Shuffle | Previous | Play/Pause | Next | Repeat
- Seekable progress bar with waveform visualization + elapsed/total time
- Play/pause button: white circle, prominent, 42px

**Right (220px):** Volume slider + queue toggle

### Unified Queue

- Single queue mixing Tidal streams and local files
- Queue state held in frontend JS (array of track objects with source type)
- Clicking a track in any view replaces or enqueues based on context:
  - Click track row → replace queue with current list, start from clicked track
  - Future: drag to queue, "play next" context menu

---

## 6. API Endpoints

### Search
- `GET /api/search?q={query}&type={tracks|albums|artists|playlists}&offset={n}&limit={n}`
  - Returns Tidal search results with ISRC local-match flags

### Library
- `GET /api/library?sort={recent|artist|album|title}&view={tracks|albums}`
  - Returns local library metadata
- `GET /api/library/album/{album_id}`
  - Returns tracks for a specific album

### Playback
- `GET /api/stream/{track_id}`
  - Proxies Tidal stream (full if OAuth, preview if not)
  - Returns audio with proper Content-Type and range request support
- `GET /api/local/{file_path}`
  - Serves local audio file with range request support
  - Path validated against configured download directories

### Downloads
- `POST /api/download` — body: `{"track_ids": [...], "quality": "..."}` or `{"url": "..."}`
  - Triggers download via existing pipeline
- `GET /api/downloads/active` — SSE stream of download progress events
- `GET /api/downloads/history?limit={n}` — recent download history

### Playlists
- `GET /api/playlists` — list user's Tidal playlists
- `GET /api/playlists/{id}/tracks` — playlist tracks with local-match flags
- `POST /api/playlists/{id}/sync` — trigger sync for a playlist

### Settings
- `GET /api/settings` — current settings
- `PATCH /api/settings` — update settings

### Auth
- `GET /api/auth/status` — OAuth session status (logged in, username, expiry)

---

## 7. File Structure

```
TIDALDL-PY/tidal_dl/
├── gui/
│   ├── __init__.py           # FastAPI app factory, CORS, static mount
│   ├── server.py             # uvicorn launcher, browser open, signal handling
│   ├── api/
│   │   ├── __init__.py       # API router aggregation
│   │   ├── search.py         # GET /api/search
│   │   ├── library.py        # GET /api/library, /api/local/{path}
│   │   ├── playback.py       # GET /api/stream/{track_id}
│   │   ├── downloads.py      # POST /api/download, GET /api/downloads/*
│   │   ├── playlists.py      # GET/POST /api/playlists/*
│   │   └── settings.py       # GET/PATCH /api/settings, GET /api/auth/status
│   └── static/
│       ├── index.html         # SPA shell — single HTML file
│       ├── style.css          # Listening Room theme — all CSS
│       ├── app.js             # Router, state, views, player — all JS
│       └── fonts/             # Crimson Pro, Outfit, JetBrains Mono (self-hosted)
└── cli.py                     # + new `gui` command via Typer
```

### CLI Integration

```python
@app.command()
def gui(
    port: int = typer.Option(8765, help="Port to serve on"),
    no_browser: bool = typer.Option(False, help="Don't auto-open browser"),
):
    """Launch the music-dl web interface."""
```

---

## 8. New Dependencies

| Package | Version | Purpose | Size |
|---|---|---|---|
| `fastapi` | `>=0.115.0` | API framework | ~1 MB |
| `uvicorn[standard]` | `>=0.34.0` | ASGI server | ~1 MB |

No frontend dependencies. No build step. No node_modules.

Fonts self-hosted in `static/fonts/` to avoid external CDN calls (works offline).

---

## 9. What This Reuses (No New Code)

| Existing Module | GUI Usage |
|---|---|
| `tidalapi` session | Search, stream URLs, playlists |
| `config.Settings` singleton | Read/write settings |
| `config.Tidal` singleton | OAuth session state |
| `download.Download` class | Download pipeline from GUI |
| `helper.isrc_index` | Local/Tidal cross-referencing |
| `helper.tidal` | Track/album/playlist helpers |
| `helper.checkpoint` | Resume interrupted downloads |
| `mutagen` | Read local file metadata for Library view |

---

## 10. Out of Scope (v1)

- Lyrics display
- Album art color extraction for dynamic theming
- Drag-and-drop queue reordering
- Keyboard shortcuts beyond basic transport
- Mobile-responsive layout (desktop-first, mobile later)
- Video playback
- Multi-user / remote access
- Waveform generation from actual audio data (v1 uses procedural waveform)
