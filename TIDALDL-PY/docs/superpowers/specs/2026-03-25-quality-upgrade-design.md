# Track Quality Upgrade System — Design Spec

> Upgrade local tracks to the best available quality from Tidal.
> Download first, verify, then trash old file. Probe once, cache forever.

---

## Problem

Users accumulate music at mixed quality — old MP3 rips, AAC downloads, CD-quality FLAC. They have Tidal access with HI_RES and HI_RES_LOSSLESS available but no way to know which tracks can be upgraded or to act on it.

---

## Tier Hierarchy (Upgrade Ladder)

| Tier       | Tidal Quality       | Local File Quality           | Rank |
|------------|---------------------|------------------------------|------|
| Legendary  | HI_RES_LOSSLESS      | 24-bit >48kHz               | 4    |
| Epic       | HI_RES / MQA         | 24-bit ≤48kHz               | 3    |
| Rare       | LOSSLESS             | 16-bit FLAC, WAV            | 2    |
| Uncommon   | HIGH (320kbps)       | MP3, AAC, OGG, M4A          | 1    |
| Common     | LOW (96kbps)         | Unknown                     | 0    |

**Dolby Atmos is excluded from the upgrade ladder.** Atmos is lossy AAC-based spatial audio — a format, not a fidelity tier. Upgrading a 24-bit FLAC to Atmos would be a downgrade for stereo playback. Atmos stays in the display tier system (Mythic) but is never an upgrade target or source.

Upgrade = re-download at a tier strictly higher than current, up to the best Tidal offers.

---

## Settings

- **`upgrade_target_quality`**: dropdown — `Epic` / `Legendary`. Default: `Legendary`.
  - Tracks already at or above the target are never flagged as upgradeable.
  - The system downloads the highest quality Tidal actually offers for the track, as long as it meets or exceeds the target.

---

## Quality Probe Cache

New SQLite table — populated by reading `track.audio_quality` and `track.media_metadata_tags` from the Tidal catalog API (lightweight, no stream initiation).

```sql
CREATE TABLE IF NOT EXISTS quality_probes (
    isrc           TEXT PRIMARY KEY,
    tidal_track_id INTEGER,
    max_quality    TEXT,      -- "HI_RES_LOSSLESS", "LOSSLESS", "HIGH", etc.
    probed_at      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_scanned_isrc ON scanned(isrc);
```

- **Catalog metadata is the default probe method.** Uses `track.audio_quality` and `media_metadata_tags` — no `get_stream()` call, no stream session initiation, minimal ban risk.
- Cached indefinitely — re-probed only on explicit user action ("Re-probe" button).
- ISRC is the primary key. One probe per ISRC, not per track instance.

**Note on `get_stream()` ban risk:** Tidal treats `get_stream()` as a download/play session initiation. Bulk-calling it triggers bot detection (see project memory: Tidal bans bots). We use catalog metadata only for probing. The actual stream quality is confirmed at download time — if the download produces a lower quality than expected, the probe cache is updated and the user is notified.

---

## Upgrade Check Flow

```
Local track (has ISRC in scanned table)
  → Check quality_probes cache
  → Cache miss?
      → Search Tidal by ISRC → get track object
      → Read track.audio_quality + media_metadata_tags
      → Cache result in quality_probes
  → Compare: local tier vs probed tier
  → If probed tier > local tier AND probed tier >= user target
      → Mark as "upgradeable"
  → Else
      → "Best available" or "Not on Tidal"
```

**Resolution chain** (for upgrade/start): `file_path → scanned table (get ISRC) → quality_probes (get tidal_track_id) → Tidal session.track(id) → Track object for dl.item()`. Each step can fail — missing ISRC, no probe, track removed from Tidal. Each failure returns a clear error.

**Quality enum conversion**: The probe cache stores string values (e.g., `"HI_RES_LOSSLESS"`). Before calling `dl.item()`, convert to `tidalapi.media.Quality` enum via the existing `QUALITY_RANK` / `HIFI_QUALITY_MAP` mappings in `constants.py`.

---

## ISRC Coverage

Not all local tracks have ISRC tags. Old MP3 rips, CD rips from pre-ISRC tagging software, and files from non-Tidal sources may lack ISRCs. The library DB tracks this as `status="needs_isrc"`.

The upgrade system **only operates on tracks with ISRCs**. The UI must surface the gap:
- Bulk scanner: "Checked 847 of 1,200 tracks — 353 skipped (no ISRC)"
- Album view: tracks without ISRC show "No ISRC" instead of upgrade badge

Fuzzy matching (artist+title fallback) is out of scope for v1.

---

## Trigger Points

### 1. Per-Track Upgrade (context menu)

- Right-click track row → **"Upgrade Quality"** menu item
- Only shown when: track has ISRC AND current tier < user's upgrade target
- Flow:
  1. Check probe cache / probe Tidal if cache miss
  2. If upgradeable: confirm via toast ("Upgrading to Legendary..."), trigger download
  3. If not upgradeable: toast "Already at best available quality"
- Download uses existing `dl.item()` with `quality_audio` converted from probe cache string to `Quality` enum
- Safe replacement: download to `.upgrading.tmp` suffix first, then trash old file, rename new file
- Library DB (`scanned` table) updated with new path, quality, format
- If download fails: `.tmp` file cleaned up, old file untouched, toast error

### 2. Album-Scoped Scanner

- New button in local album detail view: **"Check for Upgrades"**
- Probes all tracks in the album that are below target tier
- Rate: sequential, ~0.5 req/sec (even album-sized batches should be conservative to avoid rate limits)
- Results shown inline per track: upgrade badge (⬆ Legendary), "Best" indicator, or "No ISRC"
- **"Upgrade All"** button for batch action on upgradeable tracks

### 3. Bulk Scanner View

- Accessible from nav sidebar or a button in Library view
- Background job:
  1. Query all library tracks with ISRC where tier < upgrade target
  2. Skip tracks already in probe cache (instant for repeat scans)
  3. Probe uncached tracks at ~0.5 req/sec, backoff on 429
  4. SSE progress stream: `{ checked, total, upgradeable, skipped_no_isrc }`
- Pause/cancel via `threading.Event`
- Results view:
  - Coverage summary: "Checked 847 — 353 skipped (no ISRC) — 47 upgradeable"
  - Grouped by quality jump: "Uncommon → Legendary (34 tracks)", "Rare → Legendary (13 tracks)"
  - Per-track rows with current/available quality, upgrade checkbox
  - **"Upgrade Selected"** and **"Upgrade All"** buttons
- Subsequent scans skip probed tracks — near-instant for fully-probed libraries
- If SSE client disconnects and reconnects: scan continues running, client re-subscribes via same endpoint and gets current state

---

## Download Pipeline Integration (Safe Replacement)

Upgrade downloads reuse the existing pipeline with a safe-replacement wrapper:

1. **Download to temp**: `dl.item()` downloads to `{original_path}.upgrading.tmp` with `quality_audio` set to probed quality (converted to `Quality` enum) and `duplicate_action_override="redownload"` to bypass ISRC dedup
2. **Verify**: Confirm `.tmp` file exists and is non-zero
3. **Trash old file**: `osascript -e 'tell application "Finder" to delete ...'` (macOS, handles long NAS filenames)
4. **Rename new file**: Move `.tmp` to final path. Note: extension may change (e.g., `.m4a` → `.flac`) — this is expected, not an edge case
5. **Update DB**: Delete old path from `scanned`, insert new path with updated quality/format/scanned_at. Update ISRC index path mapping.
6. **On failure** (at any step): Clean up `.tmp` if it exists. Old file is untouched (trash only happens after successful download). Toast error. Do not update DB.

---

## Backend Endpoints

### `POST /api/upgrade/probe`
Probe a batch of ISRCs against Tidal catalog. Max 50 ISRCs per request.
```json
// Request
{ "isrcs": ["USLF10400147", "USRC11700001"] }

// Response
{
  "results": [
    { "isrc": "USLF10400147", "tidal_track_id": 59727857, "max_quality": "HI_RES_LOSSLESS", "upgradeable": true },
    { "isrc": "USRC11700001", "max_quality": "LOSSLESS", "upgradeable": false }
  ]
}
```

### `POST /api/upgrade/start`
Trigger upgrade downloads for a list of tracks. Accepts file paths — resolved to Tidal track IDs via `scanned.isrc → quality_probes.tidal_track_id`.
```json
// Request
{ "track_paths": ["/Volumes/Music/Shakira/Laundry Service/01 - Objection.m4a"] }

// Response
{ "status": "queued", "count": 1, "skipped": 0, "errors": ["..."] }
```
Uses existing SSE download progress stream. Skipped tracks (no ISRC, no probe, not on Tidal) returned in response.

### `GET /api/upgrade/scan`
SSE stream for bulk scan progress.
```json
{ "type": "scan_progress", "checked": 342, "total": 1200, "upgradeable": 47, "skipped_no_isrc": 353 }
{ "type": "scan_complete", "results": [...] }
```

### `POST /api/upgrade/scan/cancel`
Cancel a running bulk scan.

### `GET /api/upgrade/status`
Return cached upgrade status for tracks (from probe table). Cache-only lookup, no API calls.
```json
// Request: ?isrcs=USLF10400147,USRC11700001
// Response: same format as probe response
```

---

## File Handling

- **Safe replacement**: Download to `.tmp` first, trash old file only after verified download
- **Extension changes**: Upgrading `.m4a` (AAC) to `.flac` (lossless) is the common case, not an edge case. The new path uses the correct extension from the download pipeline.
- **Trash**: macOS `osascript` Finder delete (handles long filenames on NAS)
- **Library DB update**: `DELETE` old path, `INSERT` new path in `scanned` table (extension/path will differ)
- **ISRC index**: Update path mapping after successful upgrade

---

## Out of Scope (for now)

- A/B quality comparison playback
- Automatic scheduled scans
- Space impact calculator
- Quality distribution stats on Home view
- Fuzzy matching fallback (artist+title) for tracks without ISRC
- Deezer integration (architecture is ISRC-keyed and source-agnostic — compatible when ready)
- Dolby Atmos as an upgrade target

---

## Files to Modify

| File | Changes |
|------|---------|
| `helper/library_db.py` | `quality_probes` table, `idx_scanned_isrc` index, migration, get/set/batch methods |
| `gui/api/upgrade.py` | New file — probe, scan, start, cancel, status endpoints |
| `gui/api/__init__.py` | Register upgrade router |
| `gui/static/app.js` | Context menu "Upgrade Quality", album upgrade button, bulk scanner view |
| `gui/static/style.css` | Upgrade badge styles, scanner view layout |
| `model/cfg.py` | `upgrade_target_quality` setting field |
| `gui/api/settings.py` | Expose new setting in settings endpoint |
| `constants.py` | `TIER_RANK` mapping for programmatic tier comparison |
