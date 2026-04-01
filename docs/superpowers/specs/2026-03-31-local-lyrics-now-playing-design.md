# Local Lyrics in Now Playing — Design Specification

**Date:** 2026-03-31
**Status:** Draft
**Scope:** Local-file-first lyrics experience anchored to the existing now-playing/player area

---

## 1. Overview

Add a lyrics mode to the existing now-playing/player area in the GUI. Clicking the album art toggles a lyrics overlay anchored above the player strip for the current **local** track.

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
- Lyrics mode appears as a **same-screen overlay anchored to the player strip**.
- It is **not** a separate route, fullscreen page, or modal sheet.

### Visual Style

- Background uses a **subtle** artwork-driven treatment.
- The artwork influence should be low-contrast and readability-first.
- The audio source and transport remain unchanged.
- Control visibility while lyrics are open is explicit in this spec rather than "mostly hidden":
  - play/pause, previous, next, seek/progress, volume, the **queue toggle button**, and close affordance remain visible and interactive
  - title/artist/album metadata links remain visible in the player strip
  - album art remains visible but visually subordinated to the lyrics treatment
  - existing now-playing action buttons injected into `#now-playing` (`favorite` / `download`) are hidden while lyrics are open in v1; the lyrics overlay does not duplicate them
  - library/list-row actions such as favorite/download/context menus remain where they already live in the main view; the lyrics overlay does not duplicate them

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

A sidecar qualifies as `lrc-synced` only when cleanup yields at least one valid timed line and no fatal whole-file synced-parse failure. Sidecars with a few malformed lines may still win as synced after those lines are skipped. Sidecars that fail whole-file synced parsing may continue only as cleaned unsynced text and therefore lose to any valid embedded synced source.

### Concrete Source Contract

Supported sources in v1:

- sidecar `.lrc` text file next to the local track

Sidecar discovery contract:
- only sibling files in the same directory as the audio file are candidates
- candidate target name is `<audio-stem>.lrc`
- lookup algorithm is deterministic:
  1. if a sibling file exists whose filename exactly matches `<audio-stem>.lrc`, use that one candidate only
  2. otherwise, enumerate sibling files whose lowercase filename equals lowercase(`<audio-stem>.lrc`)
  3. if that case-insensitive set contains exactly one file, use it
  4. if that set contains zero files, there is no sidecar candidate
  5. if that set contains more than one file, sidecar resolution is ambiguous and sidecar lyrics are ignored entirely for this track
- candidate enumeration for step 2 must sort by full filename bytes/Unicode codepoint order before counting/matching so tests behave consistently across platforms

Supported embedded sources in v1:
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
- sidecar `.lrc` bytes must be decoded in this order before parsing: UTF-8 with BOM handling (`utf-8-sig`), plain UTF-8, UTF-16 with BOM handling, then final replacement-fallback decode if none succeed cleanly
- embedded text/byte values must be decoded as UTF-8 with replacement fallback before timed/untimed classification unless the container reader already returns decoded text
- malformed individual lines inside a sidecar `.lrc` are skipped during line-level cleanup; they do not by themselves disqualify synced mode
- a fatal whole-file parse failure means the file cannot produce any valid timed lines after cleanup/offset handling; only then is it ineligible to win as `lrc-synced`
- if a sidecar `.lrc` has no usable timed lines, treat its cleaned plain lyric text as an unsynced candidate only
- usable unsynced text means non-empty text after cleanup and trimming; empty-string results are not valid unsynced candidates and must fall through to the next source or to `none`
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
- `track_path` is required for every successful response mode, including `mode: none`
- `lines` and `text` are always present; the unused field is returned as an empty array/string rather than omitted
- `mode = synced` → `lines` populated, `text` empty string
- if synced normalization would leave `lines` empty, backend must downgrade the response to `unsynced` or `none` rather than returning `mode = synced` with zero lines
- `mode = unsynced` → `text` populated, `lines` empty array
- `mode = none` → `text` empty string and `lines` empty array
- `source = none` is required when `mode = none`
- frontend payload validation treats the response as malformed unless:
  - `mode` is one of `synced | unsynced | none`
  - `track_path` is a non-empty string
  - `source` is present and compatible with `mode`
  - for `mode = synced`, every line has finite non-negative integer `start_ms` and `end_ms`, `end_ms > start_ms`, and non-empty `text`
  - for `mode = unsynced`, `text` is a non-empty string after trim/cleanup
  - for `mode = none`, `text == ''` and `lines.length == 0`
- backend owns normalization of synced lines: the API must return lines already sorted, merged where timestamps collide, stripped of empty text entries, and with explicit `end_ms` values populated
- `source` must explicitly distinguish sidecar-unsynced from embedded-unsynced so fallback outcomes are observable and testable
- backend computes `end_ms` as follows:
  - for non-final lines, `end_ms` is the next line's `start_ms`
  - if duplicate timestamps occur, merge those rows into one rendered lyric item with newline-separated text in source order before computing `end_ms`
  - for the final line, `end_ms` is the track duration in milliseconds only when duration is positive and strictly greater than that line's `start_ms`
  - if track duration is missing, zero, negative, non-finite, or `<= start_ms`, final-line `end_ms` falls back to `start_ms + 4000`
  - normalization must guarantee `end_ms > start_ms` for every returned line; lines that cannot satisfy that after normalization are discarded

### Validation

Introduce a shared internal helper such as `resolve_local_audio_path(raw_path, allowed_dirs)` that both the lyrics route and `/api/playback/local` call. This helper owns the trust algorithm; v1 does **not** require the existing `validate_audio_path()` function to keep its current contract if refactoring it is the cleanest way to implement the richer result types.
- resolver result kinds: `ok | bad_request | forbidden | not_found | not_audio`
- resolver pseudocode in v1:
  1. if query `path` is missing, empty, or all whitespace → `bad_request`
  2. attempt strict resolution + allowed-dir containment + playback audio-extension allowlist using the same security properties playback relies on today
  3. if that direct validation succeeds, return `ok(resolved_path)`
  4. otherwise, run library-DB fallback against the **raw query path string exactly as provided** using the same `_path_in_library(raw_path)` check playback uses today
  5. if the raw query path is not trusted by that DB check → `forbidden`
  6. if it is trusted by DB fallback but `Path(raw_path).resolve(strict=True)` fails → `not_found`
  7. if the DB-trusted resolved file exists but its suffix is outside the playback-supported local audio extension allowlist → `not_audio`
  8. otherwise return `ok(resolved_path)`
- `ok` returns the strict resolved path string used as canonical `track_path`
- lyrics-route status mapping in v1:
  - `bad_request` → `400`
  - `forbidden` → `403`
  - `not_found` → `404`
  - `not_audio` → `404`
- `/api/playback/local` does not need a user-visible API contract change in this spec; it may keep collapsing non-`ok` resolver outcomes to its current `403` behavior even after adopting the shared resolver internally
- any path-based local-file endpoint touched by this feature that trusts the same audio path (notably `/api/library/art` for artwork-driven UI) should adopt the same shared resolver or the same shared helper family rather than duplicating trust fallback logic again
- the lyrics route must not duplicate security logic outside that shared resolver

The route must not invent a near-match validator; it must stay aligned with playback path security.

### Parser/Reader Responsibilities

Backend lyric resolution should be isolated in a small focused helper that:
- checks for sidecar `.lrc`
- parses timestamps if present
- reads embedded lyric tags when needed for fallback comparison, even when a sidecar exists but is only unsynced or malformed
- chooses the winning source by the precedence rules above
- treats lyrics-extraction/parser failure on an otherwise trusted playable file as "no usable lyrics from this source" and continues fallback rather than surfacing an HTTP error
- if every candidate source fails or yields nothing on an otherwise trusted playable file, returns `mode: none`
- normalizes output to the response shape above

This keeps parsing logic out of the route and avoids mixing UI concerns into metadata access.

---

## 6. Frontend Design

### State

Extend player/UI state with a small lyrics state object:

- `lyricsPanelState: 'closed' | 'loading' | 'synced' | 'unsynced' | 'empty' | 'error'`
- `lyricsData: null | payload`
- `lyricsCanonicalTrackPath: string | null`
- `lyricsRequestToken: number`
- `lyricsCache: Record<string, payload>`
- `lyricsError: null | string`

State contract:
- backend `mode: none` maps to frontend `lyricsPanelState: 'empty'`
- transport failures, malformed payloads, and non-abort fetch failures map to `lyricsPanelState: 'error'`
- `lyricsRequestToken` is a monotonically increasing request identity used only for stale-response rejection
- `lyricsCache` is keyed only by backend-normalized canonical `track_path`, never by raw query input
- `lyricsCache` is session-scoped in v1 (cleared on full page reload); no persistent cache or complex eviction policy is required

### Open/Close Behavior

- Clicking album art toggles lyrics mode.
- The album-art trigger must be keyboard-activatable in v1 (semantic `<button>` preferred; otherwise equivalent button role, focusability, Enter/Space activation, and accessible labeling are required).
- This intentionally repurposes album-art click away from album navigation for local tracks while lyrics mode exists.
- Album navigation remains available from the now-title/artist/album links already present in the now-playing metadata row.
- If lyrics are opened from the keyboard, focus moves into the lyrics panel close affordance or panel root; closing lyrics restores focus to the album-art trigger.
- If the track changes to another local track while lyrics are open, lyrics state reloads for the new local track.
- If playback changes from a local track to a remote/Tidal track while lyrics are open, immediately invalidate the active request token, clear visible lyrics state, and close the lyrics panel.
- If the current track is not local in v1, album-art click keeps its current album-navigation behavior and the lyrics panel stays closed.
- `track.local_path` is request input only. It may be used to issue the fetch, but it is never the cache key and never becomes the long-lived canonical identity.
- The canonical local-track key is the backend-normalized `track_path` returned by the lyrics API response.
- `track_path` must be the backend's strict resolved absolute path string for the trusted local audio file, matching playback-style resolution semantics rather than the raw query string.
- Each open/track-change fetch captures the current `lyricsRequestToken`; if a response arrives for an older token, or the panel was closed before the response resolves, discard it without mutating visible lyrics state.
- Successful responses populate `lyricsCanonicalTrackPath` and store the payload in `lyricsCache[track_path]`.
- Track change clears `lyricsCanonicalTrackPath` before issuing the next fetch.
- On reopen while the same track is still playing and `lyricsCanonicalTrackPath` is already known from a prior successful response, render `lyricsCache[lyricsCanonicalTrackPath]` immediately with no loading shell and no mandatory refetch.
- Otherwise, clear any previously rendered lyrics and show a lightweight loading shell until the new payload resolves.
- If a background refresh is added later, it must not replace visible cached lyrics with the loading shell.

### Layout

When lyrics mode is open:
- the existing player strip remains the bottom anchor for the experience
- the lyrics UI is a dedicated direct `body` child mounted as a sibling of the existing `#queue-panel` and `<footer class="player">`; it is not a child of the footer internals
- the lyrics overlay is positioned `fixed` relative to the viewport with its bottom edge locked to the top of the current desktop player strip height (prefer a shared CSS variable rather than a duplicated magic number), so it grows upward over main content without causing page reflow
- the overlay owns its own internal scrolling/overflow; body/main layout behavior remains unchanged
- outside clicks on main content do not auto-close lyrics in v1
- lyrics close only via explicit user intent: album-art toggle, visible close affordance, Escape, or opening the queue panel
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
- synced mode is not user-scrollable in v1; the active-line viewport position is controlled by auto-centering only
- wheel/touch scroll gestures inside the synced-lyrics viewport must not leave the view parked away from the active line

Active-line algorithm:
- frontend does **not** infer or repair missing timing metadata; it consumes normalized `start_ms`/`end_ms` from the backend
- the active line is the last line whose `start_ms <= currentTimeMs < end_ms`
- because backend `end_ms` for non-final lines is the next line's `start_ms`, the prior line remains highlighted through inter-line gaps until the next line starts
- on seek, recompute active line immediately from the new `audio.currentTime` and re-center it
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
- reveal the anchored lyrics overlay above the player strip
- gently fade/shift the artwork layer into the background treatment
- reveal lyrics with a soft vertical motion
- avoid a hard route change or modal pop

### Controls

- controls remain available but visually de-emphasized
- when `prefers-reduced-motion: reduce` is active, lyric transitions and artwork-motion effects should degrade to minimal fade/no-motion behavior
- seek/progress and play-pause remain visible in the player strip
- previous/next remain available
- the queue toggle control remains visible while lyrics are open, but queue panel and lyrics panel are mutually exclusive in v1: opening lyrics closes the queue, and opening the queue closes lyrics before showing the queue panel
- closing lyrics must have an obvious affordance beyond re-clicking the album art (for example, a close button or collapse handle)
- keyboard behavior in v1 may remain minimal, but Escape should close whichever of queue or lyrics is currently open
- measurable acceptance criteria for v1 desktop/tablet:
  - the anchored lyrics overlay must expose at least 220px of lyrics viewport height above the player strip
  - the player strip must keep play/pause and seek/progress visible at all times while lyrics are open
  - the overlay must stack above main content but below transient global dialogs/menus
  - the overlay's box must end at the top edge of the player strip so the player strip remains fully visible and clickable without overlay hit-target overlap
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
- fatally invalid `.lrc` synced parsing falls back to unsynced text unless a valid embedded synced source exists
- untimed or effectively invalid `.lrc` falls back to unsynced text unless a valid embedded synced source exists
- timed `©lyr` / `LYRICS` text resolves correctly when no higher-precedence synced source exists
- untimed/plain `.lrc` loses to valid embedded synced lyrics
- embedded unsynced lyrics resolve correctly when no synced source exists
- malformed embedded synced payload falls back correctly
- duplicate timestamps are merged into one rendered lyric item during normalization
- common LRC metadata tags are ignored and `[offset:]` is applied correctly
- normalized synced output guarantees `end_ms > start_ms` for every returned line
- no-lyrics case returns `mode: none`
- ambiguous case-insensitive sidecar matches are ignored and fall back to embedded/none deterministically
- resolver mapping covers `400` bad input, `403` forbidden path, and `404` not-found/not-audio outcomes
- final-line normalization uses the fixed fallback window whenever duration is missing, zero, negative, non-finite, or `<= start_ms`
- final-line normalization discards invalid rows that still cannot satisfy `end_ms > start_ms`
- invalid local path is rejected

### Frontend/Source Tests

- album-art click toggles lyrics mode wiring exists
- album navigation remains available through metadata links after album-art click is repurposed
- remote/non-local tracks do not open the lyrics panel in v1 and album-art click keeps current album navigation behavior
- synced lyrics mode includes active-line rendering path using normalized backend timings
- stale lyric responses are ignored using request-token invalidation plus current open-state checks
- first open for an uncached track clears prior content and shows a loading shell until new data arrives
- reopening lyrics for the same still-playing track reuses cached canonical-track content immediately without flashing the loading shell
- non-success fetch outcomes stop loading and show the distinct error shell without stale lyrics remaining visible
- malformed payload schema is rejected into the distinct error shell
- frontend state distinguishes empty lyrics from transport/payload error state
- user-driven fetch aborts from close/track-change are ignored silently and do not show the error shell
- opening lyrics closes queue, and opening queue closes lyrics
- reduced-motion mode degrades synced-line transitions and artwork motion as specified
- existing now-playing favorite/download buttons hide while lyrics are open
- album-art trigger is keyboard-activatable and focus restores correctly on close
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
- local track where cleaned unsynced text would become empty returns `mode: none`
- local track with lyrics open confirms existing now-playing favorite/download buttons are hidden while transport controls remain usable
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
- keyboard open/close flow on album art and close affordance behaves correctly
- reduced-motion preference disables motion-heavy transitions while preserving readability and active-line correctness

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
