# Library Duplicate Detection & Cleanup — Design Spec

> Find duplicate tracks, keep the best quality copy in the canonical location, auto-trash the rest.

---

## Problem

Library accumulates duplicates from downloading the same track into multiple playlists/folders. A single song can appear 6+ times (mixed formats). Stale DB entries pointing to deleted files create phantom tracks in the UI.

---

## Duplicate Grouping

Two-tier matching:

1. **ISRC + Album (primary)** — Group tracks sharing the same `(ISRC, album)` pair. This catches same-recording copies within the same album context (re-downloads, playlist copies) while preserving cross-album completeness. A track on "Greatest Hits" and the original album both stay — they serve different album contexts. Tracks with no album metadata fall back to bare ISRC grouping.
2. **Title+Artist+Duration (fallback)** — For tracks without ISRC. Normalized case-insensitive match on `(title, artist)` with duration tolerance of **±2 seconds** (tight to avoid grouping radio edits/remasters). True re-download duplicates have identical or near-identical duration.

A group with 2+ members (after stale pruning) is a **duplicate cluster**. Single-member groups are excluded from results.

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
- **Per-path safety gate**: Check reachability of each configured `scan_paths` directory independently. Only prune entries whose parent scan path is confirmed reachable. If `/Volumes/Music/FLAC` is mounted but `/Volumes/Music/MP3` is not, only prune stale entries under `/Volumes/Music/FLAC`. Entries under unreachable scan dirs are left untouched.
- If **no** scan dirs are reachable, skip pruning entirely.

Grouping operates on **post-prune data** only. All counts in the response reflect post-prune state.

---

## Undo via Local Staging (not macOS Trash)

macOS Trash behavior on NAS (SMB/NFS) is unreliable — some NAS firmware permanently deletes instead of moving to `.Trashes`, and Finder's "Put Back" is GUI-only with no programmatic equivalent.

Instead of trashing, duplicates are **moved to a local staging directory**:

- Staging path: `~/.config/music-dl/undo-staging/{timestamp}/`
- Files are `shutil.move()`'d from NAS to local staging (fast for small files, slower for large FLAC but deterministic)
- DB entries are removed from `scanned` table
- Staging expires after **5 minutes** — on expiry or next clean, old staging is deleted
- **Undo**: moves files back from staging to original paths, re-inserts into `scanned` table
- If local disk is too small for staging, fall back to `_trash_file()` with a warning that undo may not work

---

## Concurrency Guard

Cleanup must not run concurrently with a library scan:

- Check `_scan_running` flag (already exists in `library.py`) before starting preview or clean
- If a scan is in progress, return HTTP 409 Conflict: "Library scan in progress — try again after scan completes"
- Same guard on the scan endpoint: refuse scan if cleanup is in progress

---

## Execution Flow

1. **Check concurrency** — Refuse if scan is running.
2. **Prune stale** — Remove DB entries for missing files (per-path mount safety).
3. **Group** — SQL query groups by `(ISRC, album)`, then Python groups ISRC-less tracks by normalized `(title, artist, duration±2s)`. Filter to groups with 2+ members.
4. **Rank** — For each group, sort copies by quality → path score → path length. First = keeper.
5. **Move duplicates** — `shutil.move()` to local staging dir. Remove moved paths from `scanned` table.
6. **Report** — Return summary: groups found, copies moved, stale records pruned.
7. **Undo window** — Staging persists for 5 minutes. UI shows "Undo" button.

---

## Backend Endpoints

### `GET /api/duplicates/preview`

Dry-run scan. Returns what would be cleaned without acting. No file size calculation (avoids slow NAS stat calls — size can be added to `scanned` table later if needed).

```json
{
  "stale_count": 45,
  "groups": [
    {
      "key": "ISRC:NLB630100326:Laundry Service",
      "keeper": { "path": "/Volumes/Music/Shakira/Laundry Service/Suerte.flac", "quality": "44100Hz/16bit", "format": "FLAC", "tier": "Rare" },
      "duplicates": [
        { "path": "/Volumes/Music/- Playlists/Latin/Suerte.m4a", "quality": "44100Hz/16bit", "format": "M4A", "tier": "Uncommon" }
      ]
    }
  ],
  "total_groups": 312,
  "total_duplicates": 847
}
```

### `POST /api/duplicates/clean`

Execute cleanup: prune stale + move duplicates to staging. Returns action confirmation.

```json
{
  "stale_pruned": 45,
  "groups_cleaned": 312,
  "duplicates_moved": 847,
  "staging_path": "~/.config/music-dl/undo-staging/1711400000",
  "undo_available": true,
  "undo_expires_at": 1711400300
}
```

### `POST /api/duplicates/undo`

Restore last batch from staging. Only valid within 5 minutes of clean.

```json
{ "restored": 847, "failed": 3, "errors": ["..."] }
```

---

## Frontend

- **"Duplicates" button** in the Library view header (next to scan/refresh).
- Click → calls `GET /api/duplicates/preview` → shows summary card:
  - "Found 312 duplicate groups (847 extra copies)"
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

- **Per-path mount check**: Only prune entries under reachable scan dirs.
- **Local staging, not trash**: Deterministic undo on any filesystem.
- **Undo**: 5-minute window to restore all moved files.
- **Preview first**: Frontend always shows preview before executing.
- **Album-scoped ISRC**: Same recording on different albums preserved.
- **Concurrency guard**: Cleanup blocked during scan, scan blocked during cleanup.
- **Post-prune grouping**: Groups built after stale records removed. Single-member groups excluded.

---

## Files to Modify

| File | Changes |
|------|---------|
| `tidal_dl/gui/api/duplicates.py` | **New** — preview, clean, undo endpoints, grouping logic, path scoring |
| `tidal_dl/gui/api/__init__.py` | Register duplicates router |
| `tidal_dl/helper/library_db.py` | `prune_stale(reachable_dirs)` method |
| `tidal_dl/gui/api/library.py` | Export `_scan_running` flag for concurrency check |
| `tidal_dl/gui/static/app.js` | Duplicates button in Library, preview display, cleanup flow |
| `tidal_dl/gui/static/style.css` | Duplicate group styles |

---

## Out of Scope

- Audio fingerprinting (chromaprint/acoustid) — too slow for NAS
- Playlist reference repair after cleanup
- Automatic scheduled dedup
- Cross-library dedup (multiple NAS volumes)
- File size in preview (add `size_bytes` column to `scanned` table later)
