# Track Quality Upgrade System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users upgrade local tracks to higher quality from Tidal — per-track context menu, album-scoped scanner, and bulk library scanner.

**Architecture:** ISRC-keyed quality probe cache in SQLite. Catalog-only probing (no `get_stream()`). Safe replacement: download to `.tmp` first, trash old only after success. Reuses existing `dl.item()` pipeline. New `upgrade.py` API module with SSE scan progress.

**Tech Stack:** Python (FastAPI, SQLite, tidalapi), vanilla JS frontend, SSE for progress streaming.

**Spec:** `docs/superpowers/specs/2026-03-25-quality-upgrade-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tidal_dl/constants.py` | Add `TIER_RANK` dict + `QUALITY_STRING_TO_ENUM` reverse map |
| `tidal_dl/model/cfg.py` | Add `upgrade_target_quality` setting field |
| `tidal_dl/helper/library_db.py` | `quality_probes` table, `idx_scanned_isrc`, probe get/set/batch, migration |
| `tidal_dl/gui/api/upgrade.py` | **New** — probe, start, scan (SSE), cancel, status endpoints |
| `tidal_dl/gui/api/__init__.py` | Register upgrade router |
| `tidal_dl/gui/api/settings.py` | Expose `upgrade_target_quality` in get/update |
| `tidal_dl/gui/static/index.html` | Add "Upgrades" nav item in sidebar |
| `tidal_dl/gui/static/app.js` | Context menu "Upgrade Quality", album "Check for Upgrades" button, bulk scanner view |
| `tidal_dl/gui/static/style.css` | Upgrade badge styles, scanner view layout |

---

## Task 1: Constants — Tier Rank Map + Quality Enum Reverse Map

**Files:**
- Modify: `tidal_dl/constants.py`

- [ ] **Step 1: Add TIER_RANK dict and QUALITY_STRING_TO_ENUM map**

In `tidal_dl/constants.py`, after the existing `QUALITY_RANK` dict (~line 47), add:

```python
# Tier rank for upgrade comparison — maps quality strings to numeric tiers.
# Used by the upgrade system to determine if a Tidal quality is higher than local.
# Dolby Atmos excluded: it's lossy spatial audio, not a fidelity upgrade.
TIER_RANK: dict[str, int] = {
    "LOW": 0,
    "HIGH": 1,
    "LOSSLESS": 2,
    "HI_RES": 3,
    "HI_RES_LOSSLESS": 4,
    # Local file quality strings
    "MP3": 1,
    "AAC": 1,
    "OGG": 1,
    "M4A": 1,
    "FLAC": 2,
    "WAV": 2,
}

# Reverse map: Tidal quality string -> tidalapi.media.Quality enum.
# Used by upgrade system to convert cached probe results to dl.item() args.
# NOTE: tidalapi has no Quality.hi_res member. HI_RES maps to hi_res_lossless
# because Tidal serves the best available quality for the account tier at download time.
QUALITY_STRING_TO_ENUM: dict[str, Quality] = {
    "LOW": Quality.low_96k,
    "HIGH": Quality.low_320k,
    "LOSSLESS": Quality.high_lossless,
    "HI_RES": Quality.hi_res_lossless,
    "HI_RES_LOSSLESS": Quality.hi_res_lossless,
}
```

- [ ] **Step 2: Verify import works**

Run: `cd TIDALDL-PY && uv run python -c "from tidal_dl.constants import TIER_RANK, QUALITY_STRING_TO_ENUM; print('TIER_RANK:', TIER_RANK); print('Q_MAP:', QUALITY_STRING_TO_ENUM)"`

Expected: Both dicts printed without error.

- [ ] **Step 3: Commit**

```bash
git add tidal_dl/constants.py
git commit -m "feat(upgrade): add TIER_RANK and QUALITY_STRING_TO_ENUM maps"
```

---

## Task 2: Settings — Add upgrade_target_quality

**Files:**
- Modify: `tidal_dl/model/cfg.py`
- Modify: `tidal_dl/gui/api/settings.py`

- [ ] **Step 1: Add field to Settings dataclass**

In `tidal_dl/model/cfg.py`, add to the `Settings` dataclass (after `scan_paths` field, ~line 68):

```python
    upgrade_target_quality: str = "HI_RES_LOSSLESS"  # "HI_RES" or "HI_RES_LOSSLESS"
```

- [ ] **Step 2: Expose in settings GET endpoint**

In `tidal_dl/gui/api/settings.py`, in `get_settings()` dict (~line 36), add:

```python
        "upgrade_target_quality": d.upgrade_target_quality,
```

- [ ] **Step 3: Add to SettingsUpdate model**

In `tidal_dl/gui/api/settings.py`, in `SettingsUpdate` class (~line 145), add:

```python
    upgrade_target_quality: str | None = None
```

- [ ] **Step 4: Verify settings round-trip**

Run: `cd TIDALDL-PY && uv run python -c "from tidal_dl.config import Settings; s = Settings(); print('target:', s.data.upgrade_target_quality)"`

Expected: `target: HI_RES_LOSSLESS`

- [ ] **Step 5: Commit**

```bash
git add tidal_dl/model/cfg.py tidal_dl/gui/api/settings.py
git commit -m "feat(upgrade): add upgrade_target_quality setting"
```

---

## Task 3: Database — quality_probes Table + ISRC Index

**Files:**
- Modify: `tidal_dl/helper/library_db.py`

- [ ] **Step 1: Add quality_probes table and idx_scanned_isrc in _migrate()**

In `tidal_dl/helper/library_db.py`, in `_migrate()`, after the `playlist_covers` table creation block (~line 128), add:

```python
        # quality_probes cache (Tidal quality lookup results)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS quality_probes (
                isrc           TEXT PRIMARY KEY,
                tidal_track_id INTEGER,
                max_quality    TEXT,
                probed_at      INTEGER
            )"""
        )

        # Index on scanned.isrc for upgrade lookups
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scanned_isrc ON scanned(isrc)"
        )
```

- [ ] **Step 2: Add get/set/batch probe methods**

After the `set_playlist_cover` method, add:

```python
    # ------------------------------------------------------------------
    # Quality probe cache
    # ------------------------------------------------------------------

    def get_probe(self, isrc: str) -> dict | None:
        """Return cached Tidal quality probe for an ISRC, or None."""
        assert self._conn
        row = self._conn.execute(
            "SELECT * FROM quality_probes WHERE isrc = ?", (isrc,)
        ).fetchone()
        return dict(row) if row else None

    def get_probes_batch(self, isrcs: list[str]) -> dict[str, dict]:
        """Return cached probes for a list of ISRCs. Returns {isrc: row_dict}."""
        assert self._conn
        if not isrcs:
            return {}
        placeholders = ",".join("?" for _ in isrcs)
        rows = self._conn.execute(
            f"SELECT * FROM quality_probes WHERE isrc IN ({placeholders})", isrcs
        ).fetchall()
        return {r["isrc"]: dict(r) for r in rows}

    def set_probe(
        self,
        isrc: str,
        tidal_track_id: int,
        max_quality: str,
    ) -> None:
        """Cache a Tidal quality probe result."""
        assert self._conn
        self._conn.execute(
            "INSERT OR REPLACE INTO quality_probes (isrc, tidal_track_id, max_quality, probed_at) VALUES (?, ?, ?, ?)",
            (isrc, tidal_track_id, max_quality, int(time.time())),
        )

    def upgradeable_tracks(self) -> list[dict]:
        """Return all local tracks with a non-empty ISRC.

        Tier filtering is done in Python since quality strings are heterogeneous.
        """
        assert self._conn
        rows = self._conn.execute(
            "SELECT * FROM scanned WHERE isrc IS NOT NULL AND isrc != '' AND status != 'unreadable'"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_probe(self, isrc: str) -> None:
        """Remove a cached probe (for re-probing)."""
        assert self._conn
        self._conn.execute("DELETE FROM quality_probes WHERE isrc = ?", (isrc,))
```

- [ ] **Step 3: Verify migration runs**

Run: `cd TIDALDL-PY && uv run python -c "
from pathlib import Path
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import path_config_base
db = LibraryDB(Path(path_config_base()) / 'library.db')
db.open()
db._conn.execute('SELECT * FROM quality_probes LIMIT 1')
idx = db._conn.execute(\"SELECT name FROM sqlite_master WHERE type='index' AND name='idx_scanned_isrc'\").fetchone()
print('Table OK, Index:', idx[0] if idx else 'MISSING')
db.close()
"
`

Expected: `Table OK, Index: idx_scanned_isrc`

- [ ] **Step 4: Commit**

```bash
git add tidal_dl/helper/library_db.py
git commit -m "feat(upgrade): quality_probes table, ISRC index, probe cache methods"
```

---

## Task 4: Backend — upgrade.py API Module

**Files:**
- Create: `tidal_dl/gui/api/upgrade.py`
- Modify: `tidal_dl/gui/api/__init__.py`

This is the largest task. It implements: probe, start (safe replacement), scan (SSE), cancel, status endpoints.

**Key patterns from existing codebase:**
- Get Tidal session: `from tidal_dl.config import Tidal; tidal = Tidal(); session = tidal.session`
- Get settings: `from tidal_dl.config import Settings; settings = Settings()`
- Get DB: `from tidal_dl.helper.library_db import LibraryDB; db = LibraryDB(Path(path_config_base()) / "library.db"); db.open()`
- SSE broadcast: `from tidal_dl.gui.api.downloads import _broadcast` (module-level function, importable directly)
- Download: `from tidal_dl.download import Download, register_downloaded_track; dl = Download(tidal_obj=tidal, path_base=settings.data.download_base_path, fn_logger=logger, skip_existing=False)`
- Call: `outcome, new_path = dl.item(file_template=settings.data.format_track, media=track, quality_audio=quality_enum, duplicate_action_override="redownload")`
- Outcome check: `from tidal_dl.model.downloader import DownloadOutcome; if outcome in (DownloadOutcome.DOWNLOADED, DownloadOutcome.COPIED):`
- Trash on macOS: `subprocess.run(["osascript", "-e", f'tell application "Finder" to delete (POSIX file "{escaped}" as alias)'], capture_output=True, timeout=10)`

**Safe replacement — file extension changes:**
`dl.item()` determines the final filename and extension itself (based on format template + detected codec). The new file will already have the correct extension (e.g., `.flac`). The old file (e.g., `.m4a`) stays untouched until `dl.item()` succeeds. After success:
1. Trash old file via `_trash_file(old_path)`
2. Remove old path from `scanned` DB via `db.remove(old_path)`
3. Register new file via `register_downloaded_track(new_path)` (reads metadata, inserts into `scanned`)
No renaming needed — `dl.item()` writes to the correct final path directly.

**Setting validation:** The `upgrade_target_quality` value must be one of `"HI_RES"` or `"HI_RES_LOSSLESS"`. In the probe/start/scan endpoints, read it and look up in `TIER_RANK`. If not found, default to rank 4 (HI_RES_LOSSLESS).

- [ ] **Step 1: Create upgrade.py**

Create `tidal_dl/gui/api/upgrade.py` with the full module containing:

1. `_tier_rank_for_quality(q)` — maps any quality string (Tidal or local file) to a tier rank int. For local strings like "44100Hz/16bit" or "96000Hz/24bit", parse the bit depth and sample rate.
2. `_probe_tidal_isrc(session, isrc)` — searches Tidal by ISRC via `session.search(isrc, models=[...], limit=5)`, finds exact ISRC match, reads `track.audio_quality` + `track.media_metadata_tags`, returns `{tidal_track_id, max_quality}` or None.
3. `POST /upgrade/probe` — Pydantic `ProbeRequest(isrcs: list[str])`, max 50. Gets DB, checks cache via `get_probes_batch()`, probes Tidal for cache misses with 2s sleep between probes (0.5 req/sec). Calls `db.commit()` after all probes. Returns `{results: [{isrc, tidal_track_id, max_quality, upgradeable}]}`.
4. `POST /upgrade/start` — Pydantic `UpgradeStartRequest(track_paths: list[str])`. Resolution chain: `path -> db.get(path) -> isrc -> db.get_probe(isrc) -> tidal_track_id`. Validates each step, collects errors/skipped. Spawns `_trigger_upgrade_downloads()` in daemon thread.
5. `_trigger_upgrade_downloads(track_ids, upgrade_map, settings)` — Background thread. For each track: resolve via `tidal.session.track(tid)`, get quality from probe cache, convert via `QUALITY_STRING_TO_ENUM`, broadcast "upgrading" status, call `dl.item()`, on success trash old file + remove from DB + register new file + broadcast "done", on failure broadcast error.
6. `_trash_file(path)` — macOS: osascript Finder delete. Other: `os.remove()`.
7. `GET /upgrade/scan` — SSE endpoint. Starts `_start_bulk_scan()` if not running. Uses module-level `_scan_clients: list[asyncio.Queue]` and `_scan_state` dict. Streams progress events.
8. `_start_bulk_scan()` — Background thread. Gets all tracks with ISRC via `db.upgradeable_tracks()`, filters by local tier rank < target, batch-checks probe cache, probes Tidal for misses at 0.5 req/sec. Broadcasts progress every 5 tracks. Broadcasts `scan_complete` with full results list.
9. `POST /upgrade/scan/cancel` — Sets `_scan_state["cancel"]` threading.Event.
10. `GET /upgrade/status` — Cache-only lookup. Accepts `?isrcs=` comma-separated, max 100. Returns probe results from DB without API calls.

- [ ] **Step 2: Register router in __init__.py**

In `tidal_dl/gui/api/__init__.py`, add import and include:

```python
from tidal_dl.gui.api.upgrade import router as upgrade_router
# ...
api_router.include_router(upgrade_router, tags=["upgrade"])
```

- [ ] **Step 3: Verify server boots**

Run: `cd TIDALDL-PY && uv run python -c "from tidal_dl.gui.server import run; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add tidal_dl/gui/api/upgrade.py tidal_dl/gui/api/__init__.py
git commit -m "feat(upgrade): upgrade API — probe, start, scan SSE, cancel, status endpoints"
```

---

## Task 5: Frontend — Context Menu "Upgrade Quality"

**Files:**
- Modify: `tidal_dl/gui/static/app.js`

- [ ] **Step 1: Add upgradeTrack helper function**

After the `toggleFavorite` function, add:

```javascript
async function upgradeTrack(track) {
  const localPath = track.local_path || track.path;
  if (!localPath) { toast('No local file path', 'error'); return; }
  const isrc = track.isrc;
  if (!isrc) { toast('No ISRC — cannot match on Tidal', 'error'); return; }

  toast('Checking Tidal for upgrade...', 'success');

  try {
    const probeData = await api('/upgrade/probe', { method: 'POST', body: { isrcs: [isrc] } });
    const result = (probeData.results || [])[0];
    if (!result || !result.upgradeable) {
      toast('Already at best available quality', 'success');
      return;
    }
    toast('Upgrading to ' + qualityLabel(result.max_quality) + '...', 'success', 5000);
    await api('/upgrade/start', { method: 'POST', body: { track_paths: [localPath] } });
  } catch (err) {
    toast('Upgrade failed: ' + (err.message || err), 'error');
  }
}
```

- [ ] **Step 2: Add "Upgrade Quality" to context menu in renderTrackRow**

In `renderTrackRow`, in the context menu items array (~line 1537), after the 'Open in Finder' item and before the `'sep'`, add the upgrade option conditionally. The condition must read the user's upgrade target from settings (fetched at app load and stored as `state.settings.upgrade_target_quality`), not hardcode tier names:

```javascript
        // Upgrade Quality — only for local tracks with ISRC below user's target tier
        ...(() => {
          if (!track.isrc) return [];
          const tier = _qualityTier(track.quality || track.format);
          const targetRank = { 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 }[state.settings?.upgrade_target_quality] || 4;
          const tierRanks = { 'Common': 0, 'Uncommon': 1, 'Rare': 2, 'Epic': 3, 'Legendary': 4, 'Mythic': 5 };
          if ((tierRanks[tier.tier] || 0) >= targetRank) return [];
          return [{ label: 'Upgrade Quality', icon: 'download', action: () => upgradeTrack(track) }];
        })(),
```

This compares the track's current tier rank against the user's configured target. A track at Epic won't show the option when target is Epic, but will when target is Legendary.

**Note:** The settings must be loaded into `state.settings` at app startup (fetch `/api/settings` and store). Check if this already exists; if not, add it in the app initialization.

- [ ] **Step 3: Test visually**

Open `http://localhost:8765`, navigate to a local album, right-click a track. "Upgrade Quality" should appear for eligible tracks.

- [ ] **Step 4: Commit**

```bash
git add tidal_dl/gui/static/app.js
git commit -m "feat(upgrade): context menu Upgrade Quality for local tracks"
```

---

## Task 6: Frontend — Album "Check for Upgrades" Button

**Files:**
- Modify: `tidal_dl/gui/static/app.js`
- Modify: `tidal_dl/gui/static/style.css`

- [ ] **Step 1: Add upgrade button to renderLocalAlbumDetail**

In `renderLocalAlbumDetail` (~line 1753), after `completeAlbumBtn` and before `albumMeta.appendChild(albumActions)`, add:

```javascript
  // "Check for Upgrades" pill
  const upgradeBtn = h('button', { className: 'pill album-upgrade-btn' });
  upgradeBtn.textContent = 'Check for Upgrades';
  upgradeBtn.style.display = 'none'; // shown after tracks load
  albumActions.appendChild(upgradeBtn);
```

- [ ] **Step 2: Wire up upgrade button after tracks load**

After the tracks load and render (~line 1782, after `tracks.forEach`), add the upgrade check logic:
- Filter tracks that have ISRC and tier below Epic/Legendary
- If any exist, show the button
- On click: probe ISRCs via `/upgrade/probe`, show upgrade badges on rows, change button to "Upgrade N Tracks"
- Second click: call `/upgrade/start` with upgradeable track paths

All DOM content must use `textContent` (not innerHTML) for user-derived strings. SVG icons use the existing `svgIcon()` helper which creates safe DOM nodes.

- [ ] **Step 3: Add upgrade badge CSS**

In `tidal_dl/gui/static/style.css`, add:

```css
/* Upgrade badges */
.upgrade-badge {
  display: inline-block;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: 8px;
  background: rgba(234, 179, 8, 0.15);
  color: rgba(234, 179, 8, 0.9);
  font-weight: 600;
  letter-spacing: 0.02em;
  vertical-align: middle;
}
```

- [ ] **Step 4: Test on Laundry Service album**

Navigate to `http://localhost:8765/#localalbum:Shakira:Laundry%20Service`. Click "Check for Upgrades". Verify badges and upgrade flow.

- [ ] **Step 5: Commit**

```bash
git add tidal_dl/gui/static/app.js tidal_dl/gui/static/style.css
git commit -m "feat(upgrade): album Check for Upgrades button with inline badges"
```

---

## Task 7: Frontend — Bulk Scanner View

**Files:**
- Modify: `tidal_dl/gui/static/index.html` (nav item)
- Modify: `tidal_dl/gui/static/app.js`
- Modify: `tidal_dl/gui/static/style.css`

- [ ] **Step 1: Add "Upgrades" nav item in index.html**

Nav items are **raw HTML in `tidal_dl/gui/static/index.html`**, NOT JavaScript. Find the "Activity" section (~line 50-55, near the `data-view="downloads"` item). Add a new nav item after the downloads item:

```html
    <div class="nav-item" data-view="upgrades">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><path d="M12 19V5"/><polyline points="5 12 12 5 19 12"/></svg>
      <span>Upgrades</span>
    </div>
```

The SVG is an upward arrow icon (representing quality upgrade).

- [ ] **Step 2: Add route handler for upgrades view**

The view router is a **`switch` statement** in app.js (~line 407-428), NOT if/else. Add a new `case` before the `default:` block:

```javascript
    case 'upgrades': renderUpgradeScanner(container); break;
```

Insert this at ~line 416, before `case 'settings':`.

- [ ] **Step 3: Implement renderUpgradeScanner function**

Add `renderUpgradeScanner(container)` and `_renderScanResults(container, results)` functions.

Key elements:
- Breadcrumb: Library > Quality Upgrades
- Status text, progress bar, Start Scan / Cancel buttons
- Connects to `GET /api/upgrade/scan` SSE on scan start
- Progress updates: "Checked X / Y — Z upgradeable (N skipped, no ISRC)"
- On complete: renders results grouped by quality jump (e.g., "Uncommon -> Legendary (34 tracks)")
- Each result row: title, artist, current -> available quality, individual "Upgrade" button
- "Upgrade All" button at top

All user-derived content (track titles, artist names) rendered via `textContent`, never innerHTML.

- [ ] **Step 4: Add scanner view CSS**

```css
/* Upgrade Scanner */
.upgrade-scanner-view { padding: 0 20px; max-width: 900px; }
.upgrade-scanner-header { margin-bottom: 20px; }
.upgrade-scanner-status { color: var(--text-secondary); font-size: 13px; margin: 8px 0 12px; }
.upgrade-scanner-controls { display: flex; gap: 8px; }
.upgrade-progress-bar { height: 4px; background: var(--glass-bg); border-radius: 2px; margin-bottom: 20px; overflow: hidden; }
.upgrade-progress-fill { height: 100%; background: var(--accent); width: 0; transition: width 0.3s ease; border-radius: 2px; }
.upgrade-group { margin-bottom: 24px; }
.upgrade-group-header { font-size: 13px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.04em; }
.upgrade-row { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-radius: 8px; background: var(--glass-bg); margin-bottom: 4px; }
.upgrade-row-title { flex: 2; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.upgrade-row-artist { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--text-secondary); }
.upgrade-row-quality { flex-shrink: 0; font-size: 11px; color: var(--accent); font-weight: 500; }
.upgrade-all-btn { margin-bottom: 20px; }
.upgrade-empty { color: var(--text-secondary); font-size: 14px; padding: 40px 0; text-align: center; }
```

- [ ] **Step 5: Test bulk scanner**

Navigate to `http://localhost:8765/#upgrades`. Click "Start Scan". Verify progress and results.

- [ ] **Step 6: Commit**

```bash
git add tidal_dl/gui/static/index.html tidal_dl/gui/static/app.js tidal_dl/gui/static/style.css
git commit -m "feat(upgrade): bulk upgrade scanner view with SSE progress"
```

---

## Task 8: Settings UI — Upgrade Target Dropdown

**Files:**
- Modify: `tidal_dl/gui/static/app.js`

- [ ] **Step 1: Add upgrade_target_quality to settings form**

Find the settings form fields array (search for `quality_audio` in the settings rendering). Add a new field:

```javascript
    { key: 'upgrade_target_quality', label: 'Upgrade Target', type: 'select', options: ['HI_RES', 'HI_RES_LOSSLESS'] },
```

- [ ] **Step 2: Verify in browser**

Open settings. "Upgrade Target" dropdown should show with Epic (HI_RES) and Legendary (HI_RES_LOSSLESS) options.

- [ ] **Step 3: Commit**

```bash
git add tidal_dl/gui/static/app.js
git commit -m "feat(upgrade): upgrade target quality dropdown in settings"
```

---

## Task 9: Integration Test — Full Upgrade Flow

- [ ] **Step 1: Restart server**

```bash
cd TIDALDL-PY && uv run python -c "from tidal_dl.gui.server import run; run(open_browser=False)"
```

- [ ] **Step 2: Test album-scoped upgrade on Laundry Service**

1. Navigate to `http://localhost:8765/#localalbum:Shakira:Laundry%20Service`
2. Click "Check for Upgrades"
3. Verify upgrade badges appear on applicable tracks
4. Click "Upgrade N Tracks" and verify downloads start via SSE

- [ ] **Step 3: Test per-track context menu**

1. Right-click a track in the album
2. Verify "Upgrade Quality" appears in context menu
3. Click it, verify probe + download flow

- [ ] **Step 4: Test bulk scanner**

1. Navigate to `http://localhost:8765/#upgrades`
2. Click "Start Scan"
3. Verify SSE progress updates
4. Verify results grouped by quality jump

- [ ] **Step 5: Test settings**

1. Go to Settings
2. Change "Upgrade Target" between Epic and Legendary
3. Re-run album check — verify different tracks flagged

- [ ] **Step 6: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix(upgrade): integration test fixes"
```
