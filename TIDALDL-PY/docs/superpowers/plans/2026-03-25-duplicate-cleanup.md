# Library Duplicate Detection & Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect duplicate tracks in the local library by ISRC+album or title+artist+duration, auto-clean by moving lower-quality copies to local staging, with 5-minute undo.

**Architecture:** Pure SQL + Python grouping on existing `scanned` table. No new DB tables. New `duplicates.py` API module with preview/clean/undo endpoints. Local staging directory for undo instead of NAS Trash. Concurrency guard via existing `_scan_running` flag.

**Tech Stack:** Python (FastAPI, SQLite, shutil), vanilla JS frontend.

**Spec:** `docs/superpowers/specs/2026-03-25-duplicate-cleanup-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tidal_dl/gui/api/duplicates.py` | **New** — preview, clean, undo endpoints, grouping logic, path scoring, staging management |
| `tidal_dl/gui/api/__init__.py` | Register duplicates router |
| `tidal_dl/gui/api/library.py` | Export `_scan_running` for concurrency check (already module-level, just import it) |
| `tidal_dl/gui/static/app.js` | "Find Duplicates" button in Library view, preview display, cleanup flow, undo button |
| `tidal_dl/gui/static/style.css` | Duplicate group card styles |

---

## Task 1: Backend — duplicates.py Core Logic

**Files:**
- Create: `tidal_dl/gui/api/duplicates.py`
- Modify: `tidal_dl/gui/api/__init__.py`

This task creates the entire backend module. The module is self-contained — all grouping, ranking, staging, and endpoint logic lives here.

- [ ] **Step 1: Create duplicates.py**

Create `tidal_dl/gui/api/duplicates.py` with the full module. Key components:

**Imports and setup:**
```python
from __future__ import annotations
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException
from tidal_dl.gui.api.upgrade import _tier_rank_for_quality
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base

router = APIRouter()
```

**Module-level state:**
```python
_cleanup_running = False
_last_cleanup: dict[str, Any] = {
    "staging_path": None,
    "moved_files": [],  # list of {"original": str, "staged": str, "db_row": dict}
    "stale_pruned": 0,
    "expires_at": 0.0,
}
```

**Helper: `_get_db()`** — Same pattern as upgrade.py: opens LibraryDB from path_config_base.

**Helper: `_path_score(path: str) -> int`** — Exactly as specified in the spec:
- `#recycle` → +100
- `- playlists` or `/playlists/` → +50
- Numbered suffix `_\d{2}\.\w+$` → +30
- Path depth (slash count) as tiebreaker

**Helper: `_normalize(s: str) -> str`** — Lowercase, strip whitespace, collapse spaces. Used for fuzzy title/artist matching.

**Helper: `_reachable_scan_dirs() -> list[Path]`** — Import `_scan_directories` from `tidal_dl.gui.api.library`, filter to dirs that exist on disk. Returns only mounted/reachable paths.

**Helper: `_prune_stale(db, reachable_dirs) -> int`** — For each path in `scanned` table, check if it falls under a reachable dir. If so, check file existence. If file missing, `db.remove(path)`. Returns count of pruned entries. Commits after.

**Helper: `_find_duplicate_groups(db) -> list[dict]`** — Two-phase grouping:

Phase 1 (ISRC + album):
```sql
SELECT isrc, album, COUNT(*) as cnt FROM scanned
WHERE isrc IS NOT NULL AND isrc != '' AND status != 'unreadable'
GROUP BY isrc, COALESCE(album, '') HAVING cnt > 1
```
For each group, fetch all rows, rank by `(-_tier_rank_for_quality(quality, format), _path_score(path), len(path))`. First is keeper, rest are duplicates.

Phase 2 (title+artist fallback for ISRC-less):
```python
# Get all ISRC-less tracks
rows = db._conn.execute(
    "SELECT * FROM scanned WHERE (isrc IS NULL OR isrc = '') AND status != 'unreadable'"
).fetchall()
# Group by normalized (title, artist) with duration ±2s tolerance
```
For each fuzzy group with 2+ members, apply same ranking.

Return list of group dicts: `{"key": str, "keeper": dict, "duplicates": [dict]}`.

**Helper: `_staging_dir(ts: int) -> Path`** — Returns `Path(path_config_base()) / "undo-staging" / str(ts)`. Creates dirs.

**Helper: `_cleanup_old_staging()`** — Deletes any staging dirs older than 5 minutes.

**Endpoint: `GET /api/duplicates/preview`**
- Check `_scan_running` from library.py — if True, return 409
- Check `_cleanup_running` — if True, return 409
- Call `_prune_stale()` with reachable dirs (preview prunes stale since they're dead data)
- Call `_find_duplicate_groups(db)`
- Return `{stale_count, groups, total_groups, total_duplicates}`

**Endpoint: `POST /api/duplicates/clean`**
- Same concurrency checks
- Set `_cleanup_running = True`
- Prune stale
- Find groups
- For each duplicate in each group: `shutil.move(original, staging_dir/hash_filename)`, record mapping
- Remove moved paths from `scanned` table
- Store results in `_last_cleanup` with `expires_at = time.time() + 300`
- Set `_cleanup_running = False`
- Return `{stale_pruned, groups_cleaned, duplicates_moved, undo_available, undo_expires_at}`

**Endpoint: `POST /api/duplicates/undo`**
- Check `_last_cleanup["expires_at"] > time.time()`
- For each moved file: `shutil.move(staged, original)`, re-insert into `scanned` table using stored `db_row`
- Clear `_last_cleanup`
- Return `{restored, failed, errors}`

**Key codebase patterns (the agent MUST follow these):**
- Get Tidal config: `from tidal_dl.config import Settings; settings = Settings()`
- Get scan dirs: `from tidal_dl.gui.api.library import _scan_directories, _scan_running`
- DB pattern: `db = _get_db(); try: ... finally: db.close()`
- `_tier_rank_for_quality` is imported from `upgrade.py` — already handles format-aware lossy cap

**Staging file naming:** Use `hashlib.md5(original_path.encode()).hexdigest() + original_extension` to avoid filename collisions in staging dir. Store the original-to-staged mapping in `_last_cleanup["moved_files"]`.

**Re-inserting on undo:** Store the full `dict(row)` from the `scanned` table before removal. On undo, call `db.record(path=row["path"], status=row["status"], isrc=row.get("isrc"), artist=row.get("artist"), title=row.get("title"), album=row.get("album"), duration=row.get("duration"), quality=row.get("quality"), fmt=row.get("format"), genre=row.get("genre"))`.

- [ ] **Step 2: Register router in __init__.py**

In `tidal_dl/gui/api/__init__.py`, add:
```python
from tidal_dl.gui.api.duplicates import router as duplicates_router
```
And:
```python
api_router.include_router(duplicates_router, tags=["duplicates"])
```

- [ ] **Step 3: Verify server boots**

Run: `cd TIDALDL-PY && uv run python -c "from tidal_dl.gui.server import run; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add tidal_dl/gui/api/duplicates.py tidal_dl/gui/api/__init__.py
git commit -m "feat(duplicates): preview, clean, undo endpoints with ISRC+album grouping"
```

---

## Task 2: Frontend — Duplicates Button + Preview

**Files:**
- Modify: `tidal_dl/gui/static/app.js`
- Modify: `tidal_dl/gui/static/style.css`

- [ ] **Step 1: Add "Find Duplicates" button to renderLibrary**

In `tidal_dl/gui/static/app.js`, find `function renderLibrary(container)` at line 2155. After the filter pills section and before `container.appendChild(resultsArea)` (~line 2194), add a duplicates button:

```javascript
  // Duplicates button
  const dupBtn = h('button', { className: 'pill dup-scan-btn' });
  dupBtn.textContent = 'Find Duplicates';
  dupBtn.addEventListener('click', () => _showDuplicatePreview(resultsArea));
  pills.appendChild(dupBtn);
```

- [ ] **Step 2: Add _showDuplicatePreview function**

Add after the renderLibrary function area (near other library helpers):

```javascript
async function _showDuplicatePreview(container) {
  while (container.firstChild) container.removeChild(container.firstChild);
  container.appendChild(textEl('div', 'Scanning for duplicates...', 'upgrade-scanner-status'));

  try {
    const data = await api('/duplicates/preview');
    while (container.firstChild) container.removeChild(container.firstChild);

    // Summary
    const summary = h('div', { className: 'dup-summary' });
    if (data.stale_count > 0) {
      summary.appendChild(textEl('div', data.stale_count + ' stale records pruned (files no longer on disk)', 'dup-stale-note'));
    }
    if (data.total_groups === 0) {
      summary.appendChild(textEl('div', 'No duplicates found \u2014 your library is clean!', 'upgrade-empty'));
      container.appendChild(summary);
      return;
    }
    summary.appendChild(textEl('div', 'Found ' + data.total_groups + ' duplicate groups (' + data.total_duplicates + ' extra copies)', 'dup-summary-text'));
    container.appendChild(summary);

    // Clean Up button
    const cleanBtn = h('button', { className: 'pill active dup-clean-btn' });
    cleanBtn.textContent = 'Clean Up ' + data.total_duplicates + ' Duplicates';
    container.appendChild(cleanBtn);

    // Group list
    const groupList = h('div', { className: 'dup-groups' });
    (data.groups || []).forEach(g => {
      const card = h('div', { className: 'dup-group-card' });
      // Keeper
      const keeperRow = h('div', { className: 'dup-keeper' });
      keeperRow.appendChild(textEl('span', '\u2713 KEEP', 'dup-keep-badge'));
      keeperRow.appendChild(textEl('span', (g.keeper.tier || '') + ' \u00B7 ' + (g.keeper.format || ''), 'dup-tier'));
      keeperRow.appendChild(textEl('span', g.keeper.path, 'dup-path'));
      card.appendChild(keeperRow);
      // Duplicates
      (g.duplicates || []).forEach(d => {
        const dupRow = h('div', { className: 'dup-duplicate' });
        dupRow.appendChild(textEl('span', '\u2717 REMOVE', 'dup-remove-badge'));
        dupRow.appendChild(textEl('span', (d.tier || '') + ' \u00B7 ' + (d.format || ''), 'dup-tier'));
        dupRow.appendChild(textEl('span', d.path, 'dup-path'));
        card.appendChild(dupRow);
      });
      groupList.appendChild(card);
    });
    container.appendChild(groupList);

    // Wire clean button
    cleanBtn.addEventListener('click', async () => {
      cleanBtn.disabled = true;
      cleanBtn.textContent = 'Cleaning...';
      try {
        const result = await api('/duplicates/clean', { method: 'POST' });
        cleanBtn.textContent = 'Cleaned ' + result.duplicates_moved + ' duplicates';
        toast('Removed ' + result.duplicates_moved + ' duplicates. Undo available for 5 minutes.', 'success', 8000);

        // Show undo button
        if (result.undo_available) {
          const undoBtn = h('button', { className: 'pill dup-undo-btn' });
          undoBtn.textContent = 'Undo Cleanup';
          undoBtn.addEventListener('click', async () => {
            undoBtn.disabled = true;
            undoBtn.textContent = 'Restoring...';
            try {
              const undoResult = await api('/duplicates/undo', { method: 'POST' });
              toast('Restored ' + undoResult.restored + ' files', 'success');
              undoBtn.textContent = 'Restored';
            } catch (err) {
              toast('Undo failed: ' + (err.message || err), 'error');
              undoBtn.disabled = false;
            }
          });
          cleanBtn.parentElement.insertBefore(undoBtn, cleanBtn.nextSibling);

          // Auto-hide undo after 5 minutes
          setTimeout(() => { undoBtn.remove(); }, 300000);
        }
      } catch (err) {
        toast('Cleanup failed: ' + (err.message || err), 'error');
        cleanBtn.disabled = false;
        cleanBtn.textContent = 'Retry Clean Up';
      }
    });
  } catch (err) {
    while (container.firstChild) container.removeChild(container.firstChild);
    if (err.message && err.message.includes('409')) {
      container.appendChild(textEl('div', 'A library scan is running \u2014 try again after it completes.', 'upgrade-empty'));
    } else {
      container.appendChild(textEl('div', 'Failed to scan for duplicates: ' + (err.message || err), 'upgrade-empty'));
    }
  }
}
```

All user-derived content uses `textContent`, never innerHTML.

- [ ] **Step 3: Add CSS styles**

In `tidal_dl/gui/static/style.css`, append:

```css
/* Duplicate cleanup */
.dup-summary { margin-bottom: 16px; }
.dup-summary-text { font-size: 14px; font-weight: 500; margin-bottom: 8px; }
.dup-stale-note { font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; }
.dup-scan-btn { margin-left: auto; }
.dup-clean-btn { margin-bottom: 16px; }
.dup-undo-btn { margin-left: 8px; margin-bottom: 16px; }
.dup-groups { display: flex; flex-direction: column; gap: 8px; }
.dup-group-card { background: var(--glass-bg); border-radius: 10px; padding: 10px 14px; }
.dup-keeper, .dup-duplicate { display: flex; align-items: center; gap: 10px; padding: 4px 0; font-size: 12px; }
.dup-duplicate { opacity: 0.5; text-decoration: line-through; }
.dup-keep-badge { font-size: 10px; font-weight: 700; color: rgba(100, 200, 100, 0.9); flex-shrink: 0; width: 60px; }
.dup-remove-badge { font-size: 10px; font-weight: 700; color: rgba(200, 100, 100, 0.7); flex-shrink: 0; width: 60px; }
.dup-tier { font-size: 11px; color: var(--text-secondary); flex-shrink: 0; width: 80px; }
.dup-path { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); font-size: 11px; direction: rtl; text-align: left; }
```

Note: `direction: rtl` on `.dup-path` shows the filename end (most useful part) when truncated.

- [ ] **Step 4: Verify in browser**

Navigate to `http://localhost:8765/#library`. The "Find Duplicates" button should appear in the filter pills row.

- [ ] **Step 5: Commit**

```bash
git add tidal_dl/gui/static/app.js tidal_dl/gui/static/style.css
git commit -m "feat(duplicates): Find Duplicates button, preview display, cleanup with undo"
```

---

## Task 3: Integration Test

Manual verification after both tasks are complete.

- [ ] **Step 1: Restart server**

```bash
cd TIDALDL-PY && uv run python -c "from tidal_dl.gui.server import run; run(open_browser=False)"
```

- [ ] **Step 2: Test preview**

1. Navigate to `http://localhost:8765/#library`
2. Click "Find Duplicates"
3. Verify stale count and duplicate groups appear
4. Check that keeper has highest quality and canonical path
5. Check that duplicates are dimmed with strikethrough

- [ ] **Step 3: Test cleanup**

1. Click "Clean Up N Duplicates"
2. Verify toast message with count
3. Verify "Undo Cleanup" button appears
4. Check staging directory exists: `ls ~/.config/music-dl/undo-staging/`

- [ ] **Step 4: Test undo**

1. Click "Undo Cleanup" within 5 minutes
2. Verify files restored
3. Verify toast "Restored N files"

- [ ] **Step 5: Test concurrency guard**

1. Start a library scan
2. While scan is running, click "Find Duplicates"
3. Should show "A library scan is running" message

- [ ] **Step 6: Final commit if fixes needed**

```bash
git add -A && git commit -m "fix(duplicates): integration test fixes"
```
