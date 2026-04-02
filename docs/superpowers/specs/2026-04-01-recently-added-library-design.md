# Recently Added in Library — Design Specification

**Date:** 2026-04-01
**Status:** Draft
**Scope:** Add a Library-focused “Recently Added” experience with a sidebar entry and album-grouped shelf

---

## 1. Overview

Add a **Recently Added** experience to the existing Library flow.

This feature is explicitly **Library-first**, not a Home feature:
- the sidebar gets a single **Recently Added** nav item
- clicking it opens the Library and focuses the **Recently Added** section
- the default Library page shows a dedicated **Recently Added** shelf above the normal Library content

The shelf is album-grouped, sorted newest-first, and prefers **download recency** over plain library scan recency.

---

## 2. User-Approved Decisions

### Placement

- Add a single sidebar nav item: **Recently Added**
- Do **not** create an expandable sidebar group
- Keep the feature inside the **Library** experience

### Shelf Layout

- Use a dedicated top shelf above the normal Library results
- Keep the current Library below it
- Make the shelf visually prominent, not a tiny inline strip

### Result Shape

- Show **albums**, not tracks
- Show **12 albums** in the shelf before the user clicks through to see more
- Use one **flat recent grid**, newest first
- Do **not** bucket by Today / This Week / Earlier
- **Any new track** is enough to make an album count as recently added

### Priority Rule

Use both signals, with **downloads first**:
1. recent successful downloads
2. recent scans/imports as fallback

---

## 3. In Scope / Out of Scope

### In Scope

- Sidebar navigation entry for Recently Added
- Library route deep-linking into a recent mode
- Dedicated recent shelf at the top of Library
- Album-level aggregation and deduplication
- Download-first ordering with scan fallback
- Backend endpoint for recent local albums
- Frontend rendering, empty states, and soft-failure handling

### Out of Scope

- Home dashboard changes
- A separate standalone page outside Library
- Date-bucket grouping
- Track-level recent lists
- New database tables for materialized recent albums
- Remote/Tidal-only albums that do not exist locally in the library

---

## 4. UX Design

### Sidebar

Add **Recently Added** as a normal sidebar nav item.

Behavior:
- clicking it navigates into the Library experience
- the Library opens with the **Recently Added** section in focus
- the sidebar does not need nested album items
- it does not need to render album children in the sidebar

### Library Page

The default Library page gains a dedicated **Recently Added** section above the current Library content.

Expected structure:
1. search input stays at the top
2. the **Recently Added** shelf appears directly below the search / control area
3. the shelf shows the newest 12 albums
4. a **See all** affordance expands into the full recent-albums Library listing
5. normal Library content continues below the shelf when not in the expanded recent listing

This keeps the feature discoverable without splitting the Library into a separate product surface.

### Shelf Content

The shelf shows:
- album artwork
- album title
- artist label
- track count
- optional metadata that explains why it is recent when useful (for example source or timestamp in tooltips / future polish)

Clicking a recent album card should reuse the existing local-album navigation behavior.
The existing local route is artist+album based, so the payload must contain stable values that can map directly to the current `localalbum:<artist>:<album>` navigation pattern.

### Empty States

Two empty states are needed:

**Shelf empty, Library still useful**
- show a compact empty block in the recent shelf area
- keep the rest of Library visible below

**User explicitly entered Recently Added and no results exist**
- show a stronger empty state for the selected mode
- include guidance to sync the library or download music

---

## 5. Data Design

### Data Sources

Use existing tables only:
- `download_history` for recent successful downloads
- `scanned` for fallback scan/import recency

Relevant existing fields already exist:
- `download_history.finished_at`
- `download_history.status`
- `download_history.album`
- `download_history.artist`
- `scanned.scanned_at`
- `scanned.album`
- `scanned.artist`
- local cover derivation via representative path / existing album APIs

### Album Identity

Aggregate recency at the album level.

Primary identity should be pragmatic and match existing local-library behavior:
- `(album, artist)` for stable single-artist albums
- normalize multi-artist albums consistently with current library album grouping, so obvious compilation albums do not fragment into duplicate cards

### Priority and Merge Rules

For each album:
- if it has a recent successful download entry, use that as the primary recency signal
- if it has no qualifying download entry, use the most recent `scanned_at`
- if both exist for the same album, prefer the **download-derived** timestamp
- exclude albums that no longer exist in the local scanned library

### Inclusion Rule

If even **one** newly downloaded or newly scanned track belongs to an album, that album can appear in Recently Added.

### Sorting Rule

Sort albums by a single effective recent timestamp descending:
- `download timestamp` when present
- otherwise `scan timestamp`

---

## 6. Backend Design

### New Library-Facing Endpoint

Add a dedicated endpoint for recent local albums rather than overloading Home.

Suggested shape:

`GET /api/library/recent-albums?limit=12&offset=0`

This endpoint serves both:
- the 12-album Library shelf
- the expanded **See all** recent-albums listing inside Library

### Response Shape

Each album item should include enough data for card rendering and stable navigation:

```json
{
  "album": "Discovery",
  "artist": "Daft Punk",
  "track_count": 14,
  "cover_url": "/api/library/art?path=...",
  "recent_at": 1775000000,
  "recent_source": "download"
}
```

Envelope example:

```json
{
  "albums": [...],
  "total": 42,
  "limit": 12,
  "offset": 0
}
```

### Backend Responsibilities

The backend should:
- read qualifying recent albums from `download_history`
- read fallback recent albums from `scanned`
- merge and deduplicate them by album identity
- filter out non-local / no-longer-present albums
- derive `cover_url` using the same local-art approach already used elsewhere in the Library APIs

### Why a Dedicated Endpoint

This is a Library concern, not a Home concern. A dedicated endpoint keeps:
- Home stats unrelated to Library browsing
- frontend logic simpler
- future pagination / “see all recent” behavior clean

---

## 7. Frontend Design

### Library Section Integration

Add **Recently Added** as a dedicated Library section above the standard Library content.

Behavior:
- the default Library page shows the shelf automatically
- the shelf shows the first 12 items
- a **See all** affordance opens the broader recent-albums listing within Library

### Sidebar Deep Link

The sidebar nav item should navigate to Library with the recent section in focus.

Suggested behavior:
- use the existing route/navigation system
- deep-link to the Library section rather than a disconnected page
- the sidebar target and the shelf’s **See all** affordance should land in the same recent-albums Library state

### Card Behavior

Recent album cards should behave exactly like existing local album cards:
- click opens the local album detail view
- missing artwork falls back to existing gradient treatment

### Failure Behavior

If the recent endpoint fails:
- show a localized error/empty block in the recent area
- do **not** break the rest of the Library page
- keep ordinary Library browsing usable

---

## 8. Testing Strategy

### Backend Tests

Add tests for:
- download-first ordering when both download and scan timestamps exist
- scan fallback when no download history exists
- deduplication of the same album across both sources
- inclusion when only one new track exists for an album
- exclusion of albums that are no longer present in the local scanned library
- response shape and pagination envelope

### Frontend Tests

Where current test coverage style supports it, verify:
- sidebar Recently Added opens Library with the recent section in focus
- Library renders the dedicated recent shelf by default
- the **See all** affordance opens the expanded recent-albums listing
- album cards navigate to the existing local album view
- endpoint failure does not break the rest of Library

### Non-Goals for Initial Verification

Do not overbuild this with a new persistence layer or complex client caching. The initial goal is correctness and smooth integration into the current Library flow.

---

## 9. Recommended Implementation Approach

Use a lightweight merge of the **existing** `download_history` and `scanned` tables.

This is the recommended approach because it:
- matches the user-approved priority rule
- avoids new schema maintenance
- fits the existing Library architecture
- minimizes long-term drift risk compared to a materialized `recent_albums` table

---

## 10. Acceptance Criteria

The feature is complete when all of the following are true:

- the sidebar includes **Recently Added**
- clicking it opens Library with the recent section in focus
- Library shows a dedicated top shelf for recent albums by default
- the shelf contains the newest **12** albums
- the shelf has an explicit **See all** affordance
- albums are grouped at the album level, not shown as loose tracks
- successful downloads outrank plain scan recency
- one newly added track is enough to surface an album
- clicking a recent album opens the existing local album view
- empty/error states fail softly and do not break Library browsing
