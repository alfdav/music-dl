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
- the best available **supported synced** local lyrics source wins
- unsynced lyrics are used only when no valid supported synced source is available

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

For a local track, lyrics resolution should use this deterministic winner-selection algorithm:

1. if a sidecar `.lrc` yields at least one valid timed line after line-level cleanup and has no fatal whole-file parse failure, it wins as `lrc-synced`
2. otherwise, if any supported embedded source yields valid synced lines, the first winning embedded synced source wins as `embedded-synced`
3. otherwise, if sidecar `.lrc` yields cleaned plain text, it wins as `lrc-unsynced`
4. otherwise, if any supported embedded unsynced source yields text, it wins as `embedded-unsynced`
5. otherwise, return `none`

A sidecar with parse errors is never considered a top-priority synced winner over a valid embedded synced source.

### Concrete Source Contract

Supported sources in v1:

- sidecar `.lrc` text file next to the local track

Sidecar discovery contract:
- only files with the same basename as the audio file are candidates
- `.lrc` extension match is case-insensitive in v1
- if multiple same-basename sidecar candidates exist, prefer exact `.lrc`; if ambiguity remains, ignore sidecar lyrics entirely and continue to embedded fallback
- MP3 embedded unsynced lyrics from `USLT`
- M4A embedded synced lyrics from `©lyr` when it contains timed/LRC-style text
- M4A embedded unsynced lyrics from `----:com.apple.iTunes:UNSYNCEDLYRICS`
- FLAC embedded synced lyrics from `LYRICS` when it contains timed/LRC-style text
- FLAC embedded unsynced lyrics from `UNSYNCEDLYRICS`

Parser-coverage note:
- MP4 container fixture parsing may still be used as low-level metadata-parser coverage, but user-visible v1 lyrics support is limited to sidecar `.lrc`, FLAC, M4A, and MP3-unsynced playback-compatible cases

Explicitly out of scope for v1:
- MP3 embedded synced lyrics from `SYLT`, until real repository-produced files are verified to round-trip as usable timed lyrics for this GUI
- local MP3 files whose only synced lyrics source is `SYLT` are expected to fall back to unsynced/none in v1 and are excluded from synced-lyrics acceptance criteria

Parsing rules:
- a valid synced source must yield at least one timed lyric line with non-empty text
- sidecar `.lrc` parsing supports `[mm:ss]`, `[mm:ss.x]`, `[mm:ss.xx]`, and `[mm:ss.xxx]` timestamps
- embedded timed text in M4A `©lyr` and FLAC `LYRICS` uses the same LRC parsing rules as sidecar text once decoded
- sidecar `.lrc` parser ignores metadata/header tags such as `[ar:]`, `[ti:]`, `[al:]`, and `[by:]` in both synced and unsynced rendering
- unsynced fallback text must strip malformed timestamp tokens, BOM/CRLF artifacts, and repeated blank lines before display
- sidecar `.lrc` parser applies `[offset:<ms>]` to all parsed timestamps in v1, clamped so negative results become `0`
- multiple timestamps on one lyric line produce multiple timed entries before duplicate-timestamp merge normalization
- non-timestamp lyric text inside an otherwise synced LRC payload is ignored for timed rendering; it does not attach to the previous timed line
- M4A `©lyr` and FLAC `LYRICS` are treated as synced only when their stored text contains LRC-style timestamps; otherwise they are plain unsynced text
- when multiple embedded values or frames are present for the same logical source, use deterministic container-specific selection rules:
  - FLAC/Vorbis: first non-empty string value in tag value order
  - M4A: first non-empty decoded value in atom value order
  - MP3 `USLT`: prefer frame with empty description and `eng` language, then any `eng`, then first non-empty frame in Mutagen iteration order
- byte values must be decoded as UTF-8 with replacement fallback before timed/untimed classification
- malformed individual lines inside a sidecar `.lrc` are skipped during line-level cleanup; they do not by themselves disqualify synced mode
- a fatal whole-file parse failure means the file cannot produce any valid timed lines after cleanup/offset handling; only then is it ineligible to win as `lrc-synced`
- if a sidecar `.lrc` has no usable timed lines, treat its cleaned plain lyric text as an unsynced candidate only
- if an embedded synced payload is malformed or yields zero valid timed lines, discard its synced interpretation and continue down the fallback chain
- source precedence is quality-first, not location-first: any valid synced source beats any unsynced source
- specifically: a valid embedded synced source beats an untimed/plain-text sidecar `.lrc`
- only when no valid synced source exists does the best unsynced source win

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
  "source": "lrc-synced" | "lrc-unsynced" | "embedded-synced" | "embedded-unsynced" | "none"
}
```

Rules:
- `mode = synced` → `lines` populated, `text` optional/empty
- `mode = unsynced` → `text` populated, `lines` empty
- `mode = none` → both empty
- backend owns normalization of synced lines: the API must return lines already sorted, merged where timestamps collide, stripped of empty text entries, and with explicit `end_ms` values populated
- `source` must explicitly distinguish sidecar-unsynced from embedded-unsynced so fallback outcomes are observable and testable
- backend computes `end_ms` as follows:
  - for non-final lines, `end_ms` is the next line's `start_ms`
  - if duplicate timestamps occur, merge those rows into one rendered lyric item with newline-separated text in source order before computing `end_ms`
  - for the final line, `end_ms` is the track duration in milliseconds when duration is known
  - if track duration is unavailable, final-line `end_ms` falls back to `start_ms + 4000`
  - normalization must guarantee `end_ms > start_ms` for every returned line; lines that cannot satisfy that after normalization are discarded

### Validation

The endpoint must reuse the same validator helpers and trust semantics as `/api/playback/local` via a shared resolver contract used by both routes:
- resolver result kinds: `ok | bad_request | forbidden | not_found | not_audio`
- first run the same local-path validator used by playback
- if that fails, apply the same library-DB fallback check used by playback and resolve the file path strictly
- malformed or missing query input maps to `bad_request` → `400`
- a well-formed path rejected by the playback trust rules maps to `forbidden` → `403`
- a trusted/resolved path that no longer exists maps to `not_found` → `404`
- a trusted/resolved path that exists but cannot be parsed as audio maps to `not_audio` → `404`
- `ok` returns the strict resolved path string used as canonical `track_path`
- the route must not duplicate security logic outside that shared resolver

The route must not invent a near-match validator; it must stay aligned with playback path security.

### Parser/Reader Responsibilities

Backend lyric resolution should be isolated in a small focused helper that:
- checks for sidecar `.lrc`
- parses timestamps if present
- reads embedded lyric tags when needed for fallback comparison, even when a sidecar exists but is only unsynced or malformed
- chooses the winning source by the precedence rules above
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
- This intentionally repurposes album-art click away from album navigation for local tracks while lyrics mode exists.
- Album navigation remains available from the now-title/artist/album links already present in the now-playing metadata row.
- If the track changes, lyrics state reloads for the new track.
- If the current track is not local in v1, album-art click keeps its current album-navigation behavior and the lyrics panel stays closed.
- The canonical local-track key for lyrics state and stale-response rejection is the backend-normalized `track_path` returned by the lyrics API response.
- `track_path` must be the backend's strict resolved absolute path string for the trusted local audio file, matching playback-style resolution semantics rather than the raw query string.
- Before the first response arrives for a local track, the request key is the current `track.local_path`; once the backend responds, `track_path` becomes the source of truth for cache and stale-response comparisons.
- Lyrics fetch/update must be keyed to that canonical local-track key. If a response arrives for a stale track, or the panel was closed before the response resolves, discard it without mutating visible lyrics state.
- On open or track change, immediately clear any previously rendered lyrics and show a lightweight loading shell until the new payload resolves.
- Reopening lyrics for the same canonical local-track key may reuse the last successful payload for that track until playback changes, rather than forcing an immediate refetch.

### Layout

When lyrics mode is open:
- the fixed footer player stays fixed
- the lyrics overlay is mounted as an absolutely positioned child of the existing footer player container and anchored to its top edge
- the footer player keeps `position: relative`; the lyrics overlay uses `position: absolute` with bottom aligned to the top of the player strip so it grows upward without clipping the player controls
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
- because backend `end_ms` for non-final lines is the next line's `start_ms`, the prior line remains highlighted through inter-line gaps until the next line starts
- on seek, recompute active line immediately from the new `audio.currentTime`
- on pause/resume, keep the current active line; no animation reset is required
- if `currentTimeMs` is before the first line, no line is active yet
- if the frontend receives a malformed lyrics API payload, it does not attempt source fallback itself; it clears lyrics content and shows the distinct error shell

### Unsynced Rendering

For unsynced mode:
- render wrapped plain text in the same lyrics panel
- no active-line tracking
- preserve the same visual shell/background so the mode still feels coherent

### Empty State

For no-lyrics mode:
- show a simple empty state such as:
  - title: `Lyrics not available`
  - subtext: `This local track does not have synced, embedded, or sidecar lyrics yet.`

For transport/error mode:
- use a distinct error shell rather than silently reusing the no-lyrics state
- suggested copy:
  - title: `Could not load lyrics`
  - subtext: `Try again while playback continues.`

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
- when `prefers-reduced-motion: reduce` is active, lyric transitions and artwork-motion effects should degrade to minimal fade/no-motion behavior
- seek/progress and play-pause remain visible in the player strip
- previous/next remain available
- queue panel and lyrics panel are mutually exclusive in v1: opening lyrics closes the queue, and opening the queue closes lyrics
- closing lyrics must have an obvious affordance beyond re-clicking the album art (for example, a close button or collapse handle)
- keyboard behavior in v1 may remain minimal, but Escape should close whichever of queue or lyrics is currently open
- measurable acceptance criteria for v1 desktop/tablet:
  - the anchored lyrics overlay must expose at least 220px of lyrics viewport height above the player strip
  - the player strip must keep play/pause and seek/progress visible at all times while lyrics are open
  - the overlay must stack above main content and above the footer player shell, but below transient global dialogs/menus
  - because queue and lyrics are mutually exclusive in v1, the lyrics overlay never coexists visibly with the queue panel sibling
- the experience should feel lyrics-first, controls-second

---

## 8. Failure Handling

| Situation | Behavior |
|---|---|
| Track is local, synced lyrics found | Show synced focused lyrics view |
| Track is local, only unsynced lyrics found | Show static wrapped text |
| Track is local, no lyrics found | Show empty state |
| Backend source malformed during resolution | Backend falls back down the defined source chain before responding |
| Frontend receives malformed lyrics API payload | Stop loading, clear lyrics content, and show the distinct error shell |
| Lyrics fetch returns `4xx`/`5xx`, times out, or fails JSON parsing | Stop loading, clear stale content, and show the distinct error shell |
| Lyrics fetch is aborted because the user closed lyrics or changed tracks | Silently ignore it as expected control flow |
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
- timed `©lyr` / `LYRICS` text resolves correctly when no higher-precedence synced source exists
- untimed/plain `.lrc` loses to valid embedded synced lyrics
- embedded unsynced lyrics resolve correctly when no synced source exists
- malformed embedded synced payload falls back correctly
- duplicate timestamps are merged into one rendered lyric item during normalization
- common LRC metadata tags are ignored and `[offset:]` is applied correctly
- normalized synced output guarantees `end_ms > start_ms` for every returned line
- no-lyrics case returns `mode: none`
- invalid local path is rejected

### Frontend/Source Tests

- album-art click toggles lyrics mode wiring exists
- album navigation remains available through metadata links after album-art click is repurposed
- remote/non-local tracks do not open the lyrics panel in v1 and album-art click keeps current album navigation behavior
- synced lyrics mode includes active-line rendering path using normalized backend timings
- stale lyric responses are ignored when canonical backend `track_path` no longer matches or lyrics mode closes
- opening lyrics clears prior content and shows a loading shell until new data arrives
- non-success fetch outcomes stop loading and show the distinct error shell without stale lyrics remaining visible
- user-driven fetch aborts from close/track-change are ignored silently and do not show the error shell
- opening lyrics closes queue, and opening queue closes lyrics
- unsynced fallback rendering path exists
- wrapped lyric container/layout exists
- empty-state rendering path exists

### Manual Verification

Manual verification before claiming feature completion should include:
- local track with sidecar synced `.lrc`
- local track with embedded synced lyrics in supported v1 formats
- local `.mp4` file is outside v1 lyrics support unless local playback support expands in a later spec
- local MP3 file whose only synced lyrics source is `SYLT` correctly falls back in v1
- local track with untimed/plain `.lrc` plus valid embedded synced lyrics
- local track with only unsynced lyrics
- local track with multiple embedded unsynced values/frames where first non-empty wins
- local track with no lyrics
- partially malformed `.lrc` file
- duplicate-timestamp or multi-timestamp lyric lines
- long lyric lines that wrap
- seek forward/backward while lyrics mode is open
- final lyric line remains active through track end (or fixed fallback window when duration is unavailable)
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

Implementation note for repository compatibility:
- fixture-based verification should use real files produced by the current downloader for FLAC and M4A before claiming embedded synced support complete in v1
- MP3 embedded synced support is deferred until equivalent real-file verification exists
- parser-level MP4 fixtures, if added, are only metadata-parser coverage artifacts and do not imply user-visible v1 `.mp4` lyrics support
- fixture coverage should include repo-owned real `.lrc`, FLAC `LYRICS`, and M4A `©lyr` examples where practical, without requiring oversized binary assets

---

## 11. Why This Design

This version is intentionally narrow because it solves the actual requested experience without overreaching:
- it keeps the original audio path untouched
- it avoids Tidal-stream lyric complexity in v1
- it builds on data the project already knows how to store
- it fits the current GUI architecture instead of introducing a new page or subsystem

The result should feel immersive and polished without being a large architectural change.
