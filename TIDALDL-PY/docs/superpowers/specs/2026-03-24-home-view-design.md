# Home View — Design Spec

The Home view is the default landing when the user opens the GUI. It replaces the search view as the entry point. The purpose is to reflect the user's listening identity — not editorial curation, not algorithmic recommendations, just a mirror of their taste built from their own play history.

The app is a visual vessel for the user's preferences. We don't push anything.

## Philosophy

- The user is the protagonist. Every element on this page comes from their own behavior.
- The grid grows with the user. A brand new user sees an invitation, not an empty dashboard.
- Every stat tile tells a story with a number *and* a mini chart.
- All tiles are clickable — they lead somewhere meaningful.
- Warm amber palette, serif + mono typography, dark background. No bright gradients, no bubbly UI. Our soul stays.

## Data Infrastructure

### Schema Changes — `scanned` table

Add three columns:

| Column | Type | Default | Purpose |
|---|---|---|---|
| `play_count` | INTEGER | 0 | Total times this track has been played |
| `last_played` | INTEGER | NULL | Unix timestamp of last play |
| `genre` | TEXT | NULL | Genre tag read from file metadata |

### New Table — `play_events`

Time-series log for activity charts (weekly listening pattern, future stats detail view).

```sql
CREATE TABLE play_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    path       TEXT,
    artist     TEXT,
    genre      TEXT,
    duration   INTEGER,
    played_at  INTEGER NOT NULL
);
CREATE INDEX idx_play_events_at ON play_events(played_at);
```

One row per play. `path` is `NULL` for Tidal streams (no local file). `artist`, `genre`, `duration` are denormalized for fast aggregation without joins.

### Genre Reading

`_read_metadata` in `library.py` is extended to read the `genre` field via Mutagen's `easy=True` interface and return it in the metadata dict. `LibraryDB.record()` is extended to accept and persist a `genre` parameter. Common variants are normalized before storage:

- "Electronica/Dance", "Electronica" → "Electronic"
- "Hip-Hop/Rap", "Hip Hop" → "Hip-Hop"
- "R&B/Soul" → "R&B"
- "Alternative Rock", "Alt-Rock" → "Alt Rock"

Tracks with no genre tag get `NULL`. Charts show what exists — no fabrication.

**Backfill for existing libraries:** The new `genre` column will be `NULL` for all existing rows. A Sync Library rescan (`rescan=true`) re-reads all file metadata and populates the genre field. This uses the same mechanism that fixed the "Unknown Artist" metadata issue — no special backfill logic needed.

### Play Count Tracking

Every `playTrack()` call in the frontend sends `POST /api/home/play` with:

```json
{
  "path": "/Volumes/Music/track.flac",
  "artist": "Daft Punk",
  "genre": "Electronic",
  "duration": 320
}
```

For **local tracks**, `path` is required. The backend looks up the `scanned` row to increment `play_count` and set `last_played`. Artist, genre, and duration are also sent in the body (the frontend already has them from the track object) and used directly for the `play_events` insert — no extra DB lookup needed.

For **Tidal streams** (no `path`), the frontend sends `artist`, `genre`, `duration` in the body. A `play_events` row is logged but `scanned.play_count` is not incremented since the track isn't in the library DB.

The backend:
1. If `path` is provided: increments `play_count` and sets `last_played` on the `scanned` row
2. Inserts a row into `play_events` with artist, genre, duration, timestamp (from the request body)

## API

### `POST /api/home/play`

Request body:

```json
{
  "path": "/Volumes/Music/track.flac",
  "artist": "Daft Punk",
  "genre": "Electronic",
  "duration": 320
}
```

`path` is optional (null for Tidal streams). `artist`, `genre`, `duration` are always sent by the frontend. If `path` is provided and matches a `scanned` row, `play_count` is incremented and `last_played` is set. A `play_events` row is always inserted. Returns `204 No Content`.

### `GET /api/home`

Single aggregated response for the entire Home view. No waterfalls.

```json
{
  "top_artist": { "name": "Daft Punk", "play_count": 342, "cover_url": "/api/library/art?path=..." },
  "top_artists": [
    { "name": "Daft Punk", "play_count": 342, "cover_url": "..." },
    { "name": "Coldplay", "play_count": 189, "cover_url": "..." }
  ],
  "most_replayed": {
    "name": "One More Time", "artist": "Daft Punk", "album": "Discovery",
    "play_count": 87, "cover_url": "...", "path": "..."
  },
  "top_genre": "Electronic",
  "genre_breakdown": [
    { "genre": "Electronic", "count": 3400 },
    { "genre": "Alt Rock", "count": 2200 }
  ],
  "listening_time_hours": 214,
  "weekly_activity": [3.2, 5.1, 2.8, 4.0, 6.5, 7.0, 5.5],
  "track_count": 10098,
  "track_genres": [
    { "genre": "Electronic", "count": 4020 },
    { "genre": "Alt Rock", "count": 2800 }
  ],
  "album_count": 847,
  "album_artists": [
    { "artist": "Daft Punk", "count": 12 },
    { "artist": "Coldplay", "count": 9 }
  ],
  "total_plays": 0
}

**Note:** `recently_played` is NOT in the API response. It already lives in browser `localStorage` (the existing `recentlyPlayed` array). The frontend renders the recently played strip client-side from localStorage — no duplication needed.
```

`total_plays` is the sum of all play counts — the frontend uses this to decide which growth stage to render.

**Field details:**
- `weekly_activity`: Hours listened per day for the **current calendar week** (Mon=0 to Sun=6), using the server's local timezone for day boundaries. Computed from `SUM(duration)` on `play_events` grouped by day-of-week where `played_at` falls within the current week.
- `listening_time_hours`: Total all-time listening, computed from `SUM(duration)` on `play_events`. This counts actual plays, not library size × duration.

**Cold start:** When `total_plays` is 0, most arrays are empty and nullable fields are null. The frontend renders based on what data exists.

**`most_replayed` source:** Computed from `scanned` table (`ORDER BY play_count DESC LIMIT 1`), not from `play_events`. The `scanned` table has the track `title` which `play_events` does not.

### Cover URL for Artists

Artist tiles need a cover image. The endpoint uses the most-played track by that artist and returns its album art path. This is computed in the `GET /api/home` aggregation — no new endpoint needed.

## Frontend

### Navigation

- New "Home" nav item — first in the sidebar, above Search, with a house icon.
- `navigate('home')` is the default on page load (replaces `navigate('search')`).
- Hash: `#home`.

### `renderHome(container)`

Calls `GET /api/home`, then renders based on `total_plays`:

**Growth thresholds:**
- **Cold start**: `total_plays == 0`
- **Early days**: `total_plays >= 1` (any data at all — tiles appear as their individual thresholds are met)
- **Established**: `total_plays >= 100` (full grid)

#### Cold Start (0 plays)

```
┌─────────────────────────────────┐
│ Good morning, welcome to YOUR   │
│ library                         │
│                                 │
│ ┌─────────────────────────────┐ │
│ │ ♪  I'm feeling lucky       │ │  ← bento card style
│ │    (plays a random track)   │ │
│ └─────────────────────────────┘ │
│                                 │
│ This space is yours. Play some  │
│ music and watch it come alive.  │
└─────────────────────────────────┘
```

The lucky button is rendered as a bento tile — same card styling as the rest of the grid. It's the only tile, inviting the first interaction.

#### Early Days (~5-50 plays)

```
┌──────────────────────────────────────────────────────┐
│ Good morning, welcome to YOUR library    [Lucky btn] │
│                                                      │
│ ┌──────────┬──────────┬──────────┬──────────┐       │
│ │ Top      │ Most     │ Coldplay │ 3h       │       │
│ │ Artist   │ Replayed │ 8 plays  │ Listen   │       │
│ │ Daft Punk│ One More │          │ M-S chart│       │
│ │ 18 plays │ Time     │          │          │       │
│ ├──────────┴──────────┼──────────┼──────────┤       │
│ │                     │ 30 trks  │ 4 albums │       │
│ │                     │ genre ▊▊ │ artist▊▊ │       │
│ └─────────────────────┴──────────┴──────────┘       │
│                                                      │
│ Recently played                                      │
│ [art] [art] [art]                                    │
└──────────────────────────────────────────────────────┘
```

Tiles only appear when they have enough data to be meaningful. Top artist needs 5+ plays. Most replayed needs 10+ plays on a single track. Stat tiles appear once there's any data to chart.

#### Established (100+ plays)

Full 3-row × 4-col bento grid as shown in the mockup (v6). All tiles populated with charts.

### Tile Specifications

| Tile | Size | Background | Chart | Click Action |
|---|---|---|---|---|
| Top Artist | 2×1 (hero) | Faded album art @ 20% + dark gradient overlay | — | Filter library by artist |
| Other Artists | 1×1 | Faded album art @ 20% + dark gradient overlay | — | Filter library by artist |
| Most Replayed | 2×1 | Faded album art @ 20% + dark gradient overlay (purple tint) | — | Play the track |
| Top Genre | 1×1 | Solid dark | Horizontal bar chart: top 4 genres | Future: stats detail |
| Listening Time | 1×1 | Solid dark | Vertical bar chart: Mon–Sun hours | Future: stats detail |
| Tracks | 1×1 | Solid dark | Horizontal bar chart: top 4 genres by track count | Future: stats detail |
| Albums | 1×1 | Solid dark | Horizontal bar chart: top 4 artists by album count | Future: stats detail |

All tiles show a "View artist" / "Play" / "View stats" hint on hover (top-right corner, faded).

### Recently Played Strip

- Horizontal scroll, full width (bleeds to container edges).
- Renders as many cards as exist in `recently_played` — no fixed cap.
- Each card: 130×130px album art, track/album name, artist name below.
- Clicking a card plays that track.

### Responsive Layout

- **≥900px**: 4-column grid, `grid-template-columns: repeat(4, 1fr)`
- **<900px**: 2-column grid, hero tiles span full width (2 cols), everything else 1 col
- Recently played strip is always horizontal scroll regardless of width

### "I'm Feeling Lucky" Button

- **Cold start**: Rendered as a bento tile (the only card in the grid)
- **Early/Established**: Small amber pill button, top-right of the greeting row, inline with the title

### "Check My Stats" Link

- Small pill button next to the "Recently played" section label
- For now: shows a toast "Coming soon" or navigates to DJAI placeholder
- Future: opens a detailed stats breakdown view

## Not In Scope (Future Work)

- "Check my stats" detail view
- DJAI mood-based picks
- Tidal genre enrichment (API lookup for tracks missing genre tags)
- Ambient color extraction from now-playing album art
- Time decay on play counts (weighting recent plays heavier)

## Mockups

Interactive mockups showing all three growth stages are in:
`.superpowers/brainstorm/1711-1774362750/home-layout-v6.html`

Open with any local HTTP server or the visual companion at the port shown during brainstorming.
