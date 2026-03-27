# Card Inspect — Design Spec

> Replace the inline expand system with a TCG-inspired card inspect overlay. Click a stat tile to lift it from the grid and fan out a deck of detail cards behind it. Browse with keyboard or clicks. Dismiss to collapse back.

## Problem

Stat tiles (genre, listening time, tracks, albums) use an inline expand (`_expandToggle`) that resizes the tile and breaks grid symmetry. The detail rows are cramped, hidden behind a hover-only "More" label, and feel disconnected from the app's visual identity. The bento grid — which the user considers sacred — reflows on every expand/collapse.

## Constraints

- **Layout is sacred.** The bento grid must never reflow during inspect. The original tile stays in its grid slot with `opacity: 0`.
- **Two formats are law.** Format A (image tile) and Format B (stat tile) are the only tile types. Card inspect applies to Format B tiles only — both standalone tiles and the genre half of a split tile.
- **Clone-and-elevate.** The inspect overlay is a self-contained fixed layer. It does not modify the grid DOM.
- **Transform and opacity only.** All animations use compositor-friendly properties. No `width`, `height`, `top`, or `left` animation.
- **Respect `prefers-reduced-motion`.** Checked in JS via `matchMedia('(prefers-reduced-motion: reduce)')`. Duration set to 0 in code — the existing CSS `!important` rule does NOT affect `element.animate()` calls.
- **Animation cleanup.** Every `element.animate()` call must be cleaned up: `animation.finished.then(() => { animation.commitStyles(); animation.cancel(); })` to prevent memory leaks from `fill: 'forwards'` accumulation.

## Design

### 1. Interaction Model

| Action | Result |
|--------|--------|
| Click stat tile (standalone) | Main card clones to fixed overlay, animates from grid position to center. Deck fans behind. Scrim dims grid. Pip dots appear. |
| Click genre half (split tile) | Same behavior — bounding rect measured from the `.bento-half`, not the parent `.bento-split`. Only the genre half is inspectable; the on-repeat half is Format A (plays track on click). |
| Right arrow / D | Next card swaps to front (fan shuffle animation) |
| Left arrow / A | Previous card swaps to front |
| Click background card | That card swaps to front directly |
| Escape / click scrim | Reverse animation — card flies back to grid slot, overlay removed |
| Route change (nav click, `/` search) | Dismiss overlay immediately (no animation) before navigating |

**Keyboard handling:** The overlay's keydown handler calls `e.stopPropagation()` on all captured keys (Left/Right/A/D/Escape/Space/Enter) to prevent the global handler from also processing them (e.g., arrow keys seeking audio ±5s). Additionally, the global keydown handler at the top of the listener checks for `.inspect-scrim` presence and returns early for arrow keys.

### 2. Animation Choreography

**FLIP measurement sequence (critical order to avoid flash):**
1. Measure First — `getBoundingClientRect()` on original tile
2. Set original tile `opacity: 0`
3. Create clone in overlay, position at First rect using `transform: translate(firstX, firstY)`
4. Compute Last position (center of viewport, scaled up)
5. Animate from First transform to Last transform

This order ensures the clone is never visible at the Last position before animation starts.

**Open sequence (~400ms total):**

| Time | What |
|------|------|
| 0ms | Scrim fades in (`opacity: 0 → 1`, 200ms, ease-out). `background: rgba(0, 0, 0, 0.6)` with `backdrop-filter: blur(8px)`. Clone created at original bounding rect. Original tile → `opacity: 0`. |
| 0–300ms | Clone animates from original rect to center screen (`transform: translate() scale()`, 300ms, `cubic-bezier(0.22, 0.61, 0.36, 1)`). |
| 150–400ms | Deck cards stagger in from behind main card. Each fans to its rotation position. Stagger: 50ms per card, 250ms each, bounce easing `cubic-bezier(0.175, 0.885, 0.32, 1.275)`. |
| 350–400ms | Pip dots fade in below the fan (50ms). |

**Card swap animation (~300ms):**

Current front card animates to target background position (gains rotation + translate). Target background card simultaneously animates to center (rotation → 0, scale to full). Pip dots update instantly.

**Close sequence (~350ms):**

| Time | What |
|------|------|
| 0ms | Deck cards stagger out (reverse of open, 200ms, nearest card first). |
| 100–350ms | Main card animates from center back to original grid rect (250ms, ease-in). Re-measures `getBoundingClientRect()` at dismiss time for scroll safety. |
| 200–350ms | Scrim fades out (150ms). |
| 350ms | Remove overlay DOM. Restore original tile `opacity: 1`. |

**Implementation technique:** Web Animations API (`element.animate()`). After each animation completes: `animation.finished.then(() => { animation.commitStyles(); animation.cancel(); })`. Fan layout uses `transform-origin: bottom center` with rotation angles computed from offset: `angle = offset * 6deg`, Y-lift = `Math.abs(offset) * -12px`.

### 3. Card Dimensions

All inspect cards have a **fixed aspect ratio of 2:3** (playing card proportion).

- **Width:** `min(240px, 70vw)` — fits comfortably on mobile
- **Height:** computed from width × 1.5
- **Content overflow:** `overflow: hidden` — content is designed to fit. If it doesn't, it clips. No scrolling inside cards.
- **All cards in a deck are the same dimensions.** The front card and background cards are identical in size; the front card is visually distinguished by shadow and z-index, not size.

### 4. Card Content Per Deck

Each stat tile becomes a deck of 3–4 cards. Card 0 is always what the bento tile already shows — no new data needed for the default view.

**Listening Time (4 cards):**

| # | Title | Stat Label | Content | Data Source |
|---|-------|-----------|---------|-------------|
| 0 | `11h` | LISTENING TIME | Weekly bar chart + insight text | Existing: `listening_time_hours`, `weekly_activity` |
| 1 | `9pm` | PEAK HOUR | Peak hour number + `peak_hours` array rendered as 24-bar mini chart | Existing: `peak_hours` (24-element array) |
| 2 | `3 days` | STREAK | Current streak + best-ever streak + key-value stats | **New query:** best-ever streak (scan full `play_events` date series for longest consecutive run) |
| 3 | `+23%` | VS LAST WEEK | This week mins, last week mins, % change | Existing: `week_vs_last` |

**Genre (3 cards):**

| # | Title | Stat Label | Content | Data Source |
|---|-------|-----------|---------|-------------|
| 0 | `Pop` | RECENT GENRE | Bar chart breakdown | Existing: `genre_breakdown` / `this_week.genre_breakdown` |
| 1 | `12%` | DEEP CUT | Rarest genre with plays > 0, % of total | Existing: last item in `genre_breakdown` (already sorted by count desc) |
| 2 | `Pop → Electronic` | SHIFTING | All-time top genre vs this-week top genre | Existing: compare `genre_breakdown[0]` vs `this_week.genre_breakdown[0]` — no new query, just frontend comparison |

**Tracks (3 cards):**

| # | Title | Stat Label | Content | Data Source |
|---|-------|-----------|---------|-------------|
| 0 | `847` | TRACKS | Format bar chart | Existing: `track_count`, `format_breakdown` |
| 1 | `FLAC 62%` | QUALITY | Format distribution with RPG tier color per bar | Existing: `format_breakdown` + existing `_qualityTier()` function for colors |
| 2 | `231` | UNPLAYED | Tracks never played, % of library | Existing: `unplayed_count` |

**Albums (3 cards):**

| # | Title | Stat Label | Content | Data Source |
|---|-------|-----------|---------|-------------|
| 0 | `94` | ALBUMS | Top artist by album count | Existing: `album_count`, `album_artists` |
| 1 | `7 / 94` | COMPLETIONIST | Albums where every track has been played | **New query:** count albums where all tracks in `scanned` have at least one `play_events` entry |
| 2 | `3 new` | RECENT | Most recently scanned albums (names + artist) | **New query:** `SELECT album, artist, MAX(rowid) FROM scanned GROUP BY album, artist ORDER BY MAX(rowid) DESC LIMIT 3` |

**New queries required (3 total):**
1. **Best-ever streak:** Walk the full `play_events` date series, find longest consecutive-day run. Returns integer.
2. **Completionist albums:** Count of albums where `COUNT(DISTINCT path) in play_events >= COUNT(*) in scanned` for that album. Returns integer + total.
3. **Recently scanned albums:** 3 most recent albums by rowid. Returns list of `{album, artist}`.

All other card content is derived from existing fields or computed in frontend JS.

### 5. Visual Treatment

**Card structure (Format B in overlay context):**

```
div.inspect-card
  div.card-corner.top-left        ← SVG music note, rarity color, 0.3 opacity
  div.card-corner.bottom-right    ← SVG music note, rotated 180°
  span.card-rarity                ← rarity label (top-right, mono, tiny)
  div.bento-body                  ← same Format B layout
    div.bento-label               ← big value (serif, 1.5rem, accent or rarity color)
    div.bento-stat-label          ← descriptor (muted, uppercase)
    div.card-content              ← detail specific to this card
    div.card-stats                ← key-value pairs (bottom, border-top separator)
    div.card-flavor               ← italic flavor text, very low opacity
```

Corner marks use SVG (consistent with design system rule: no emoji as icons).

**Rarity system (per-card, tied to existing RPG quality tiers):**

Each card computes its own rarity independently. If multiple thresholds match, the highest tier wins.

| Rarity | Border Glow | Example Triggers |
|--------|------------|-----------------|
| Common | `rgba(240,235,228,0.15)` | Default — stat exists but nothing special |
| Uncommon | `rgba(126,201,122,0.25)` | Streak ≥ 3 days, unplayed < 10% of library |
| Rare | `rgba(100,160,220,0.25)` | Streak ≥ 7 days, lossless formats > 80% of library |
| Epic | `rgba(160,120,210,0.25)` | Streak ≥ 14 days, completionist > 50% of albums |
| Legendary | `rgba(212,160,83,0.25)` | Streak ≥ 30 days, completionist = 100% |

Card 0 (the bento tile summary) is always **Common** — it's the face card showing aggregate data, not an achievement.

Front card gets enhanced shadow: `0 20px 60px rgba(0,0,0,0.5)`. Background cards use standard `var(--surface)` with `var(--glass-border)`, dimmed to 0.4 opacity.

**Flavor text:** 7–8px italic, `rgba(240,235,228,0.2)`. Examples:
- Streak 30+ days: *"Gotta catch 'em all."*
- Peak hour 2am: *"Nothing good happens after midnight. Except music."*
- 100% completionist: *"Achievement unlocked: No stone unturned."*
- Rarest genre < 5%: *"A person of refined and unusual taste."*

**Pip dots:** Centered below the fan, fixed position. 8px circles, `rgba(255,255,255,0.35)` default, active dot `rgba(255,255,255,0.95)` with `scale(1.3)` transition.

**Empty/insufficient data:** If a card's data is unavailable (e.g., no `week_vs_last` because the app is brand new), that card is omitted from the deck. The deck shows only cards with data. Minimum deck size: 1 (the bento tile summary, which always has data). If the deck has only 1 card, the fan and pip dots don't render — the card just lifts to center and back.

### 6. Scrim and Overlay Layer

```css
.inspect-scrim {
  position: fixed;
  inset: 0;
  z-index: 150;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(8px);
}
```

Z-index 150 — **below** confirm overlay (200) and shortcuts overlay (200). If a confirm dialog or shortcuts overlay opens, inspect is visually behind it. On route change (`navigate()` calls), inspect dismisses immediately without animation before the view transition fires.

### 7. What Gets Removed

| Remove | Reason |
|--------|--------|
| `_expandToggle()` function in app.js | Replaced by card inspect |
| `_detailBlock()` function in app.js | Detail data moves into deck cards |
| `.bento-expanded` class + all CSS rules | No more inline expand |
| `.bento-detail`, `.bento-detail-row`, `.bento-detail-key`, `.bento-detail-val` CSS | No more hidden rows |
| `.bento-chevron` element + CSS | No more dropdown arrow |
| "More" `bento-hint` text on stat tiles | No more expand hint |
| All `_expandToggle(tile)` calls in `_genreTile`, `_listeningTimeTile`, `_tracksTile`, `_albumsTile` | Tiles no longer expand inline |

**What stays unchanged:**
- `.bento-hint` on image tiles ("View albums", "Play") — those are navigation, not expand
- All bento tile structure (Format A and Format B)
- Split tile compartment model (genre half becomes inspectable; on-repeat half stays Format A)
- All existing data queries in `home_stats()` and `_windowed_stats()`

### 8. Files Changed

| File | Change |
|------|--------|
| `tidal_dl/gui/static/app.js` | New `_cardInspect` module: open/dismiss/swap/keyboard/pip dots. Remove `_expandToggle`, `_detailBlock`. New deck card renderers per tile type. Remove expand calls from stat tile builders. Add `stopPropagation` guard for keyboard events. Add dismiss-on-navigate hook. |
| `tidal_dl/gui/static/style.css` | New `.inspect-scrim`, `.inspect-clone`, `.inspect-card`, `.card-corner`, `.card-rarity`, `.card-stats`, `.card-flavor`, `.pip-dots`, `.pip-dot` styles. Remove `.bento-expanded`, `.bento-detail`, `.bento-detail-row`, `.bento-detail-key`, `.bento-detail-val`, `.bento-chevron` styles. |
| `tidal_dl/helper/library_db.py` | 3 new queries: best-ever streak, completionist album count, recently scanned albums. Extend `home_stats()` return dict with `best_streak`, `completionist_albums`, `recent_albums`. |
| `tidal_dl/gui/api/home.py` | Pass new fields through to API response. |

### 9. What This Does NOT Change

- Grid structure, column count, tile positions, or responsive behavior
- Hero tile visual weight or span
- Image tiles (artist, replayed, on-repeat) — they don't expand, they navigate/play
- Recently played strip
- Player, queue, search, library, or any other view
- Any database schema or tables (all new queries use existing tables)

### 10. Future: Touch/Mobile

Touch support (swipe left/right to navigate cards, larger pip dot hit targets, responsive card sizing) is parked for a future iteration. The current design targets desktop with keyboard and mouse. The card dimensions (`min(240px, 70vw)`) ensure cards don't overflow on small viewports, but the fan layout may need adaptation for mobile — out of scope for this spec.
