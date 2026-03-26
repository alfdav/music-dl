# Library Duplicate Detection & Cleanup — Design Spec

> Find duplicate tracks, keep the best quality copy in the canonical location, auto-trash the rest.

---

## Problem

Library accumulates duplicates from downloading the same track into multiple playlists/folders. A single song can appear 6+ times (mixed formats). Stale DB entries pointing to deleted files create phantom tracks in the UI.

---

## Duplicate Grouping

Two-tier matching:

1. **ISRC (primary)** — Identical recording. Group all tracks sharing the same ISRC.
2. **Title+Artist+Duration (fallback)** — For tracks without ISRC. Normalized case-insensitive match on `(title, artist)` with duration tolerance of ±5 seconds.

A group with 2+ members is a **duplicate cluster**.

---

## Winner Selection (automatic, deterministic)

For each cluster, rank copies by:

1. **Quality tier rank** — Legendary (4) > Epic (3) > Rare (2) > Uncommon (1) > Common (0). Uses `_tier_rank_for_quality(quality, format)` with format-aware lossy cap (M4A/MP3/AAC/OGG always Uncommon).
2. **Canonical path score** — Penalize paths containing `#recycle`, `- Playlists`, or numbered suffixes (`_01`, `_02`). Prefer clean `Artist/Album/Track` structure.
3. **Shortest path** — Tiebreaker. Canonical paths tend to be shorter.

Top-ranked copy = **keeper**. All others = **duplicates** (trashed).

---

## Stale Record Pruning

Before grouping, scan all `scanned` table entries and check file existence on disk.

- Path where file doesn't exist → **remove from DB** (not trash — file is already gone).
- **Safety gate**: Only prune when at least one configured `scan_paths` directory is reachable (mounted). If no scan dirs exist on disk, skip pruning entirely to avoid wiping the DB cache when NAS is offline.

---

## Execution Flow

1. **Prune stale** — Remove DB entries for missing files (with mount safety check).
2. **Group** — SQL query groups by ISRC, then Python groups ISRC-less tracks by normalized `(title, artist, duration±5s)`.
3. **Rank** — For each group, sort copies by quality → path score → path length. First = keeper.
4. **Trash duplicates** — `_trash_file()` via macOS Finder osascript for each loser. Remove trashed paths from `scanned` table.
5. **Report** — Return summary: groups found, copies trashed, stale records pruned, bytes freed.
6. **Undo window** — Results cached in memory for 5 minutes. Undo restores files from macOS Trash and re-inserts paths into `scanned` table.

---

## Backend Endpoints

### `GET /api/duplicates/preview`

Dry-run scan. Returns what would be cleaned without acting.

```json
{
  "stale_count": 45,
  "groups": [
    {
      "key": "ISRC:NLB630100326",
      "keeper": { "path": "/Volumes/Music/Shakira/Laundry Service/Suerte.flac", "quality": "44100Hz/16bit", "format": "FLAC", "tier": "Rare" },
      "duplicates": [
        { "path": "/Volumes/Music/- Playlists/Latin/Suerte.m4a", "quality": "44100Hz/16bit", "format": "M4A", "tier": "Uncommon" }
      ]
    }
  ],
  "total_groups": 312,
  "total_duplicates": 847,
  "total_bytes": 2147483648
}
```

### `POST /api/duplicates/clean`

Execute cleanup: prune stale + trash duplicates. Returns same structure as preview plus action confirmation.

```json
{
  "stale_pruned": 45,
  "groups_cleaned": 312,
  "duplicates_trashed": 847,
  "bytes_freed": 2147483648,
  "undo_available": true,
  "undo_expires_at": 1711400000
}
```

### `POST /api/duplicates/undo`

Restore last batch from macOS Trash. Only valid within 5 minutes of clean.

```json
{ "restored": 847, "failed": 3, "errors": ["..."] }
```

---

## Frontend

- **"Duplicates" button** in the Library view header (next to scan/refresh).
- Click → calls `GET /api/duplicates/preview` → shows summary card:
  - "Found 312 duplicate groups (847 extra copies, ~2.1 GB)"
  - "45 stale records (files no longer on disk)"
  - Expandable group list: keeper (highlighted green) + duplicates (dimmed, struck through path)
  - **"Clean Up"** button → calls `POST /api/duplicates/clean`
- After cleanup → summary toast + **"Undo"** button visible for 5 minutes.
- Each group row shows: track title, artist, quality tier badge, format, path (truncated).

---

## Path Scoring

```python
def _path_score(path: str) -> int:
    """Lower score = more canonical. Higher score = more likely a duplicate."""
    score = 0
    p = path.lower()
    if "#recycle" in p: score += 100
    if "- playlists" in p or "/playlists/" in p: score += 50
    # Numbered suffix like _01, _02 from duplicate downloads
    if re.search(r'_\d{2}\.\w+$', p): score += 30
    # Deep nesting penalty
    score += p.count("/")
    return score
```

---

## Safety

- **Mount check**: Skip all pruning if NAS scan dirs aren't reachable.
- **Trash, not delete**: All file removal goes through macOS Finder trash (recoverable).
- **Undo**: 5-minute window to restore from Trash.
- **Preview first**: Frontend always shows preview before executing.
- **No cross-album matching**: Same song on "Greatest Hits" vs original album are NOT duplicates (different album metadata = different groups... unless same ISRC, which means same recording).

**Note on ISRC cross-album**: ISRC identifies a specific recording, not an album placement. The same ISRC on a "Greatest Hits" and the original album IS the same recording. Grouping by ISRC is correct — the winner selection will keep the copy in the canonical album folder.

---

## Files to Modify

| File | Changes |
|------|---------|
| `tidal_dl/gui/api/duplicates.py` | **New** — preview, clean, undo endpoints |
| `tidal_dl/gui/api/__init__.py` | Register duplicates router |
| `tidal_dl/helper/library_db.py` | `find_duplicate_groups()`, `prune_stale()` methods |
| `tidal_dl/gui/static/app.js` | Duplicates button in Library, preview modal, cleanup flow |
| `tidal_dl/gui/static/style.css` | Duplicate group styles |

---

## Out of Scope

- Audio fingerprinting (chromaprint/acoustid) — too slow for NAS
- Playlist reference repair after cleanup
- Automatic scheduled dedup
- Cross-library dedup (multiple NAS volumes)
