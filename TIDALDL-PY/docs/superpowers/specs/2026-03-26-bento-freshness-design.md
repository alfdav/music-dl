# Bento Grid Freshness — Design Spec

> Make the home bento grid reflect current listening activity instead of frozen all-time stats, without changing the layout.

## Problem

The bento grid hero tiles (top artist, most replayed) and stat tiles (genre, listening time) are powered by all-time aggregates from `play_events`. When you've been listening to Deftones all week but Linkin Park has 247 cumulative plays, the bento still shows Linkin Park. The recently played strip (localStorage) feels alive while the bento feels like a museum.

Additionally, when the server restarts or `/Volumes/Music` goes offline, `scanned`-table stats (track count, album count) go stale with no indication of age. `play_events`-based stats survive both scenarios since they're in SQLite on local disk.

## Constraints

- **Layout is sacred.** The bento grid structure, tile positions, and visual hierarchy do not change.
- **Tiles are compartments.** Each tile occupies a size class within a fixed grid. New features are added by subdividing existing compartments, not by adding rows or sections.
- **No new sections or labels.** No "This Week" / "All Time" headers. The grid just shows fresher data silently.

## Design

### 1. Backend: Time-Windowed Stats

`LibraryDB.home_stats()` adds a `this_week` key to the response. The 7-day window is a **rolling 7 days** calculated as `played_at >= (now - 7 * 86400)`. This is intentionally different from the `weekly_activity` chart which uses a Monday-to-Sunday calendar week — rolling window ensures the bento always reflects your most recent 7 days regardless of what day it is.

**New fields in `this_week`:**

| Field | Query | Purpose |
|-------|-------|---------|
| `top_artist` | Top artist by COUNT in 7-day window | Hero tile data source |
| `top_artists` | Top 5 artists in 7-day window | Secondary artist tiles |
| `most_replayed` | Most-played track in 7-day window | "On repeat" half-tile |
| `genre_breakdown` | Genre distribution from 7-day window | Genre tile data source |
| `total_plays` | COUNT of plays in window | Fallback check (0 = no recent data) |

All existing all-time fields remain unchanged. No new tables, no new indexes (the existing `idx_play_events_at` on `played_at` covers all window queries).

**API response shape change:**

```json
{
  "this_week": {
    "top_artist": { "name": "Deftones", "play_count": 12, ... },
    "top_artists": [...],
    "most_replayed": { "name": "Change", "artist": "Deftones", "play_count": 5, ... },
    "genre_breakdown": [...],
    "total_plays": 18
  },
  "top_artist": { ... },
  "most_replayed": { ... },
  ...
}
```

**Bug fix:** `top_album` currently queries `scanned.play_count` (diverges from `play_events`). Fix to query `play_events` with `GROUP BY album, artist ORDER BY COUNT(*) DESC`.

### 2. Frontend: Recency-Aware Data Binding

`_renderHomeGrid()` checks `data.this_week.total_plays > 0`:

- **If recent data exists:** artist tiles, genre tile, and listening time tile bind to `this_week` data instead of all-time. Eyebrow text on hero tiles stays as-is (no "THIS WEEK" label). The data just changes silently.
- **If no recent data (0 plays in 7 days):** everything renders exactly as today. All-time stats fill all tiles. No empty state, no nudge, no visual change.

**Tile data source priority:**

| Tile | Recent data available | No recent data |
|------|----------------------|----------------|
| Top artist (hero) | `this_week.top_artist` | `top_artist` (all-time) |
| Secondary artists | `this_week.top_artists[1:3]` | `top_artists[1:3]` (all-time) |
| Most replayed (hero) | All-time (unchanged) | All-time (unchanged) |
| Genre | `this_week.genre_breakdown` | `genre_breakdown` (all-time) |
| Listening time | All-time (unchanged — cumulative stat) | All-time (unchanged) |
| Tracks / Albums | All-time from `scanned` (unchanged) | All-time (unchanged) |

Note: Most replayed hero tile stays all-time — it represents your identity track. The new "on repeat" half-tile handles weekly repeat behavior (see section 3).

### 3. New Half-Tile: "On Repeat"

When `this_week.most_replayed` exists and has `play_count >= 3`, one of the right-side standard tiles (genre tile) becomes a **flex container holding two half-tiles stacked vertically**:

- **Top half:** Genre tile (condensed — label + top genre name + mini bar chart, insight text hidden)
- **Bottom half:** "On repeat" tile — track name, artist, play count this week. Clicking plays the track.

**Implementation:** The outer grid stays identical. The genre tile's DOM node becomes:

```html
<div class="bento-tile bento-stat-tile bento-split">
  <div class="bento-half"><!-- condensed genre --></div>
  <div class="bento-half bento-on-repeat"><!-- on repeat --></div>
</div>
```

**CSS:**

```css
.bento-split {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.bento-split .bento-half {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
```

**Fallback:** If no track qualifies for "on repeat" (fewer than 3 plays this week), the genre tile renders at full size exactly as today. No split, no empty half.

### 4. Volume Offline Handling

No changes. The existing `volume_available` flag and offline banner continue to work. All `play_events`-based stats (both windowed and all-time) survive volume offline since they live in local SQLite. `scanned`-based stats (track/album counts) remain cached as today — they're cumulative and valid even when stale.

### 5. Files Changed

| File | Change |
|------|--------|
| `tidal_dl/helper/library_db.py` | Add windowed queries to `home_stats()`, fix `top_album` query |
| `tidal_dl/gui/api/home.py` | Pass `this_week` through to response, add cover_url conversion |
| `tidal_dl/gui/static/app.js` | Recency-aware data binding in `_renderHomeGrid()`, new `_onRepeatHalf()` renderer, `_genreTile()` split logic |
| `tidal_dl/gui/static/style.css` | `.bento-split`, `.bento-half`, `.bento-on-repeat` styles |

### 6. What This Does NOT Change

- Grid structure, column count, tile positions, or responsive behavior
- Hero tile visual weight or span
- Recently played strip (localStorage, independent)
- Listening time tile (cumulative stat, not windowed)
- Track/album count tiles (from `scanned`, not windowed)
- Any database schema or tables

### 7. Future: Drag-to-Rearrange

The compartment model (tiles as sized units in a fixed grid) naturally supports drag-to-rearrange. Each tile knows its size class; a drag operation swaps tile positions in a persisted layout config. Parked — not part of this spec.
