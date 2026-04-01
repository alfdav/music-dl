# Local Lyrics in Now Playing — Design Specification

**Date:** 2026-03-31
**Status:** Draft
**Scope:** Local-file-first lyrics experience inside the existing now-playing panel

---

## 1. Overview

Add a lyrics mode to the existing now-playing area in the GUI. Clicking the album art toggles an expanded now-playing panel that shows lyrics for the current **local** track.

This first version is intentionally local-file-first:
- local tracks only
- source audio remains untouched
- lyrics are presentation-only UI
- the best available **synced** local lyrics source wins
- unsynced lyrics are used only when no valid synced source is available

The target feel is Apple-Music-like in one specific way: the lyrics view should use a subtle artwork-driven background and a focused, centered current line with smooth motion, without becoming a full-screen takeover.

---

## 2. User-Approved UX Direction

### Interaction

- Clicking album art in the now-playing area toggles lyrics mode.
- Lyrics mode lives inside an **expanded now-playing panel in the same screen**.
- It is **not** a separate route, fullscreen page, or modal sheet.

### Visual Style

- Background uses a **subtle** artwork-driven treatment.
- The artwork influence should be low-contrast and readability-first.
- Playback controls become **mostly hidden** while lyrics are open.
- The audio source and transport remain unchanged.

### Lyrics Behavior

- If synced lyrics are available, show an Apple-Music-style focused layout:
  - current lyric centered/emphasized
  - nearby lines visible above and below
  - smooth motion between active lines
- Long lyric lines **wrap naturally**.
- If only unsynced lyrics exist, show them in the same panel as static wrapped text.
- If no lyrics exist, show a clean empty state rather than failing playback.

---

## 3. In Scope / Out of Scope

### In Scope

- Lyrics mode for the currently playing **local** track
- Album-art click to open/close lyrics mode
- Desktop/tablet layout only in v1 (where the now-playing block already exists)
- Synced lyrics rendering when timing data exists
- Unsynced lyrics fallback
- Empty-state handling when lyrics are unavailable
- Subtle animated/blurred artwork background behind lyrics
- Minimal-control now-playing layout while lyrics are open

### Out of Scope

- Tidal-stream lyrics in v1
- Mobile-specific lyrics UI in v1
- Karaoke word-by-word highlighting
- Editing lyrics metadata in the GUI
- Downloading new lyrics from third-party providers during playback
- Rewrapping, transcoding, or otherwise altering the source audio
- Separate fullscreen lyrics route

---

## 4. Data Sources

The project already supports lyrics data in existing download and metadata paths:

- synced lyrics can be embedded in audio metadata
- unsynced lyrics can be embedded in audio metadata
- optional `.lrc` files can be written alongside media files

### Preferred Resolution Order

For a local track, lyrics resolution should use this order:

1. valid sidecar `.lrc` with timestamped lines
2. valid embedded synced lyrics from tags
3. sidecar `.lrc` plain text / unsynced text
4. embedded unsynced lyrics from tags
5. no lyrics available

### Concrete Source Contract

Supported sources in v1:

- sidecar `.lrc` text file next to the local track
- MP3 embedded synced lyrics from `SYLT`
- MP3 embedded unsynced lyrics from `USLT`
- M4A/MP4 embedded synced lyrics from `©lyr` when it contains timed/LRC-style text
- M4A/MP4 embedded unsynced lyrics from `----:com.apple.iTunes:UNSYNCEDLYRICS`
- FLAC embedded synced lyrics from `LYRICS` when it contains timed/LRC-style text
- FLAC embedded unsynced lyrics from `UNSYNCEDLYRICS`

Parsing rules:
- a valid synced source must yield at least one timed lyric line with non-empty text
- sidecar `.lrc` parsing uses LRC timestamp syntax such as `[mm:ss.xx]`
- MP3 `SYLT` parsing uses the native ID3 timed entries, not text-pattern matching
- MP4 `©lyr` and FLAC `LYRICS` are treated as synced only when their stored text contains LRC-style timestamps; otherwise they are plain unsynced text
- if a sidecar `.lrc` exists but is partially malformed, keep the successfully parsed timestamped lines if any exist; otherwise treat its plain lyric text as unsynced text and continue only if no valid embedded synced source exists
- if an embedded synced payload is malformed or yields zero valid timed lines, discard its synced interpretation and continue down the fallback chain
- source precedence is quality-first, not location-first: any valid synced source beats any unsynced source

Rationale:
- `.lrc` is the most explicit timed-lyrics source for UI playback matching
- the repository already writes different embedded lyric shapes by container, so v1 must name the supported tag keys explicitly
- embedded unsynced lyrics provide a graceful fallback without inventing new parsing rules during implementation

---

## 5. Backend Design

### New Endpoint

Add a local-lyrics API endpoint for the current/local track path.

Suggested shape:

`GET /api/lyrics/local?path=<absolute-local-path>`

### Response Shape

```json
{
  "mode": "synced" | "unsynced" | "none",
  "track_path": "/abs/path/to/file.flac",
  "lines": [
    { "start_ms": 12345, "end_ms": 16789, "text": "Line text" }
  ],
  "text": "plain unsynced lyrics",
  "source": "lrc" | "embedded-synced" | "embedded-unsynced" | "none"
}
```

Rules:
- `mode = synced` → `lines` populated, `text` optional/empty
- `mode = unsynced` → `text` populated, `lines` empty
- `mode = none` → both empty
- backend owns normalization of synced lines: the API must return lines already sorted, de-duplicated by final source order, stripped of empty text entries, and with explicit `end_ms` values populated

### Validation

The endpoint must only read from valid local library paths already trusted by the GUI's playback/local-file path rules.

### Parser/Reader Responsibilities

Backend lyric resolution should be isolated in a small focused helper that:
- checks for sidecar `.lrc`
- parses timestamps if present
- reads embedded lyric tags when sidecar is absent
- normalizes output to the response shape above

This keeps parsing logic out of the route and avoids mixing UI concerns into metadata access.

---

## 6. Frontend Design

### State

Extend player/UI state with a small lyrics state object:

- `lyricsOpen: boolean`
- `lyricsLoading: boolean`
- `lyricsMode: 'synced' | 'unsynced' | 'none'`
- `lyricsData: null | payload`
- `lyricsTrackKey: string | null`

### Open/Close Behavior

- Clicking album art toggles lyrics mode.
- This intentionally repurposes album-art click away from album navigation while lyrics mode exists.
- Album navigation remains available from the now-title/artist/album links already present in the now-playing metadata row.
- If the track changes, lyrics state reloads for the new track.
- If the current track is not local in v1, album-art click does nothing beyond the normal now-playing behavior; the lyrics panel stays closed.
- Lyrics fetch/update must be keyed to the current track key/path. If a response arrives for a stale track, or the panel was closed before the response resolves, discard it without mutating visible lyrics state.

### Layout

When lyrics mode is open:
- the fixed footer player stays fixed
- a lyrics panel grows **upward from the player area as an anchored overlay**, covering part of the main content rather than pushing page layout downward
- desktop/tablet only in v1; mobile keeps its existing compact player behavior with no lyrics panel
- album art remains present but visually subordinated to lyrics
- controls compress into a minimal strip
- lyrics become the focal element

Acceptance criteria for layout:
- open lyrics state must leave playback controls reachable
- lyrics panel must be tall enough to show the active line and at least one context line above and below on desktop
- background treatment must preserve readable lyric contrast over both light and dark album art

### Synced Lyrics Rendering

For synced mode:
- derive active line from `audio.currentTime` using already-normalized backend lines
- center the active line in the lyrics viewport
- fade previous/next lines with lower opacity
- animate transitions smoothly when active line changes
- wrapped long lines remain a single logical lyric item even if visually multiple lines tall

Active-line algorithm:
- frontend does **not** infer or repair missing timing metadata; it consumes normalized `start_ms`/`end_ms` from the backend
- the active line is the last line whose `start_ms <= currentTimeMs < end_ms`
- if playback time lands in a gap before the next line, keep the most recent prior line highlighted until the next line starts
- on seek, recompute active line immediately from the new `audio.currentTime`
- on pause/resume, keep the current active line; no animation reset is required
- if `currentTimeMs` is before the first line, no line is active yet

### Unsynced Rendering

For unsynced mode:
- render wrapped plain text in the same lyrics panel
- no active-line tracking
- preserve the same visual shell/background so the mode still feels coherent

### Empty State

For no-lyrics mode:
- show a simple empty state such as:
  - title: `Lyrics not available`
  - subtext: `This local track does not have synced or embedded lyrics yet.`

---

## 7. Motion and Visual Treatment

### Background

- Use current artwork colors as subtle influence only.
- Prefer blur, dimming, and low-opacity gradients over bold animation.
- Motion should be slow and restrained.
- Background must never compete with lyric readability.

### Transition

When toggling lyrics open:
- expand the now-playing panel in place
- gently fade/shift the artwork layer into the background treatment
- reveal lyrics with a soft vertical motion
- avoid a hard route change or modal pop

### Controls

- controls remain available but visually de-emphasized
- seek/progress and play-pause remain visible in the player strip
- queue panel may continue to exist, but opening lyrics does not require the queue to open and must not break queue behavior
- closing lyrics must have an obvious affordance beyond re-clicking the album art (for example, a close button or collapse handle)
- keyboard behavior in v1 may remain minimal, but Escape should close the lyrics panel if it is open
- the experience should feel lyrics-first, controls-second

---

## 8. Failure Handling

| Situation | Behavior |
|---|---|
| Track is local, synced lyrics found | Show synced focused lyrics view |
| Track is local, only unsynced lyrics found | Show static wrapped text |
| Track is local, no lyrics found | Show empty state |
| Lyrics payload malformed | Fall back down the defined source chain: valid synced → valid unsynced → empty state |
| Track changes while lyrics are open | Reload lyrics for the new track and discard any stale in-flight response for the previous track |
| Track is remote/Tidal stream in v1 | Keep the lyrics panel closed; no remote fallback UI in v1 |
| Artwork missing | Use neutral subtle gradient fallback |
| User closes lyrics while fetch is in flight | Ignore the response when it arrives |

The lyrics feature must never interrupt or degrade playback.

---

## 9. Testing Strategy

### Backend Tests

- sidecar `.lrc` parsing returns normalized synced lines with explicit `end_ms`
- partially malformed `.lrc` with at least one good timestamped line still returns synced mode
- untimed or effectively invalid `.lrc` falls back to unsynced text unless a valid embedded synced source exists
- MP3 `SYLT` resolves correctly when no valid sidecar synced source exists
- timed `©lyr` / `LYRICS` text resolves correctly when no higher-precedence synced source exists
- embedded unsynced lyrics resolve correctly when no synced source exists
- malformed embedded synced payload falls back correctly
- no-lyrics case returns `mode: none`
- invalid local path is rejected

### Frontend/Source Tests

- album-art click toggles lyrics mode wiring exists
- album navigation remains available through metadata links after album-art click is repurposed
- remote/non-local tracks do not open the lyrics panel in v1
- synced lyrics mode includes active-line rendering path using normalized backend timings
- stale lyric responses are ignored when track key changes or lyrics mode closes
- unsynced fallback rendering path exists
- wrapped lyric container/layout exists
- empty-state rendering path exists

### Manual Verification

Manual verification before claiming feature completion should include:
- local track with synced lyrics
- local track with only unsynced lyrics
- local track with no lyrics
- partially malformed `.lrc` file
- long lyric lines that wrap
- seek forward/backward while lyrics mode is open
- track change while lyrics mode is open
- closing lyrics during a slow/fake delayed load
- remote/Tidal track does not open lyrics mode
- playback controls still usable when lyrics mode is visible

---

## 10. Implementation Notes

Recommended implementation order:

1. add backend lyrics reader + route
2. add now-playing lyrics state + album-art toggle
3. build unsynced/empty-state shell first
4. add synced active-line tracking using `audio.currentTime`
5. add subtle artwork background and motion polish
6. verify manual cases above

This keeps the highest-risk logic (lyrics parsing and timed active-line tracking) isolated and testable.

---

## 11. Why This Design

This version is intentionally narrow because it solves the actual requested experience without overreaching:
- it keeps the original audio path untouched
- it avoids Tidal-stream lyric complexity in v1
- it builds on data the project already knows how to store
- it fits the current GUI architecture instead of introducing a new page or subsystem

The result should feel immersive and polished without being a large architectural change.
