# Card Inspect — Design Spec

> Replace the inline expand system with a TCG-inspired card inspect overlay. Click a stat tile to lift it from the grid and fan out a deck of detail cards behind it. Browse with keyboard or clicks. Dismiss to collapse back.

## Problem

Stat tiles (genre, listening time, tracks, albums) use an inline expand (`_expandToggle`) that resizes the tile and breaks grid symmetry. The detail rows are cramped, hidden behind a hover-only "More" label, and feel disconnected from the app's visual identity. The bento grid — which the user considers sacred — reflows on every expand/collapse.

## Constraints

- **Layout is sacred.** The bento grid must never reflow during inspect. The original tile stays in its grid slot with `opacity: 0`.
- **Two formats are law.** Format A (image tile) and Format B (stat tile) are the only tile types. Card inspect applies to Format B tiles only.
- **Clone-and-elevate.** The inspect overlay is a self-contained fixed layer. It does not modify the grid DOM.
- **Transform and opacity only.** All animations use compositor-friendly properties. No `width`, `height`, `top`, or `left` animation.
- **Respect `prefers-reduced-motion`.** Duration drops to 0 when the user prefers reduced motion.

## Design

### 1. Interaction Model

| Action | Result |
|--------|--------|
| Click stat tile | Main card clones to fixed overlay, animates from grid position to center. Deck fans behind. Scrim dims grid. Pip dots appear. |
| Right arrow / D | Next card swaps to front (fan shuffle animation) |
| Left arrow / A | Previous card swaps to front |
| Click background card | That card swaps to front directly |
| Escape / click scrim | Reverse animation — card flies back to grid slot, overlay removed |

Keyboard trap while overlay is open: only Left/Right/A/D/Escape active. Space/Enter on a focused background card also swaps it.

### 2. Animation Choreography

**Open sequence (~400ms total):**

| Time | What |
|------|------|
| 0ms | Scrim fades in (`opacity: 0 → 0.7`, 200ms, ease-out). Clone created at original bounding rect via `getBoundingClientRect()`. Original tile → `opacity: 0`. |
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

**Implementation technique:** Web Animations API (`element.animate()`) with `fill: 'forwards'`. FLIP pattern (First, Last, Invert, Play) for the origin-to-center transition. Fan layout uses `transform-origin: bottom center` with rotation angles computed from offset: `angle = offset * 6deg`, Y-lift = `Math.abs(offset) * -12px`.

### 3. Card Content Per Deck

Each stat tile becomes a deck of 3–4 cards. Card 0 is always what the bento tile already shows.

**Listening Time (4 cards):**

| # | Title | Stat Label | Content |
|---|-------|-----------|---------|
| 0 | `11h` | LISTENING TIME | Weekly bar chart + insight text |
| 1 | `9pm` | PEAK HOUR | When you listen most, hourly breakdown |
| 2 | `3 days` | STREAK | Current streak, best ever, this-month calendar grid |
| 3 | `+23%` | VS LAST WEEK | This week vs last week, trend direction |

**Genre (3 cards):**

| # | Title | Stat Label | Content |
|---|-------|-----------|---------|
| 0 | `Pop` | RECENT GENRE | Bar chart breakdown |
| 1 | `12%` | DEEP CUT | Rarest genre you listen to vs most common |
| 2 | `Pop → Electronic` | SHIFTING | Genre this week vs all-time |

**Tracks (3 cards):**

| # | Title | Stat Label | Content |
|---|-------|-----------|---------|
| 0 | `847` | TRACKS | Format bar chart |
| 1 | `FLAC 62%` | QUALITY | Format/quality distribution with RPG tier colors |
| 2 | `231` | UNPLAYED | Tracks never played, % of library |

**Albums (3 cards):**

| # | Title | Stat Label | Content |
|---|-------|-----------|---------|
| 0 | `94` | ALBUMS | Top artist by album count |
| 1 | `7 / 94` | COMPLETIONIST | Albums with every track played |
| 2 | `3 new` | RECENT | Most recently scanned albums |

All data from existing `home_stats()` queries or trivial additions to the same function.

### 4. Visual Treatment

**Card structure (Format B in overlay context):**

```
div.inspect-card
  div.card-corner.top-left        ← ♪ glyph, rarity color, low opacity
  div.card-corner.bottom-right    ← ♪ glyph, rotated 180°
  span.card-rarity                ← rarity label (top-right, mono, tiny)
  div.bento-body                  ← same Format B layout: label → stat-label → content
    div.bento-label               ← big value (serif, 1.5rem, accent or rarity color)
    div.bento-stat-label          ← descriptor (muted, uppercase)
    div.card-content              ← detail specific to this card (stats, charts, calendar)
    div.card-stats                ← key-value pairs (bottom, border-top separator)
    div.card-flavor               ← italic flavor text, very low opacity (easter egg)
```

**Rarity system (tied to existing RPG quality tiers):**

| Rarity | Border Glow | Trigger |
|--------|------------|---------|
| Common | `rgba(240,235,228,0.15)` | Default — stat exists but nothing special |
| Uncommon | `rgba(126,201,122,0.25)` | Streak ≥ 3 days, unplayed < 10% |
| Rare | `rgba(100,160,220,0.25)` | Streak ≥ 7 days, quality > 80% lossless |
| Epic | `rgba(160,120,210,0.25)` | Streak ≥ 14 days, genre shift > 50% |
| Legendary | `rgba(212,160,83,0.25)` | Streak ≥ 30 days, 100% completionist |

Front card gets enhanced shadow: `0 20px 60px rgba(0,0,0,0.5)`. Background cards use standard `var(--surface)` with `var(--glass-border)`, dimmed opacity.

**TCG corner marks:** `♪` glyphs in top-left and bottom-right corners, rarity color at 0.3 opacity. Decorative signature.

**Flavor text:** 7–8px italic at the bottom of each card, `rgba(240,235,228,0.2)`. Generated from actual listening data. Examples:
- Streak 30+ days: *"Gotta catch 'em all."*
- Peak hour 2am: *"Nothing good happens after midnight. Except music."*
- 100% completionist: *"Achievement unlocked: No stone unturned."*
- Rarest genre < 5%: *"A person of refined and unusual taste."*

**Pip dots:** Centered below the fan, fixed position. 8px circles, `rgba(255,255,255,0.35)` default, active dot `rgba(255,255,255,0.95)` with `scale(1.3)` transition.

### 5. Scrim

```css
.inspect-scrim {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(8px);
}
```

Same z-index layer as confirm overlay and shortcuts overlay. Clicking the scrim dismisses.

### 6. What Gets Removed

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
- Split tile (genre + on repeat compartment)
- All existing data queries in `home_stats()` and `_windowed_stats()`

### 7. Files Changed

| File | Change |
|------|--------|
| `tidal_dl/gui/static/app.js` | New `_cardInspect` module: open/dismiss/swap/keyboard. Remove `_expandToggle`, `_detailBlock`. New deck card renderers per tile type. Remove expand calls from stat tile builders. |
| `tidal_dl/gui/static/style.css` | New `.inspect-scrim`, `.inspect-clone`, `.inspect-card`, `.card-corner`, `.card-rarity`, `.card-stats`, `.card-flavor`, `.pip-dots`, `.pip-dot` styles. Remove `.bento-expanded`, `.bento-detail`, `.bento-detail-row`, `.bento-detail-key`, `.bento-detail-val`, `.bento-chevron` styles. |
| `tidal_dl/helper/library_db.py` | Add queries for new card data: unplayed count, completionist albums, recently scanned, genre shift comparison. Extend `home_stats()` return with these fields. |
| `tidal_dl/gui/api/home.py` | Pass new fields through to API response. |

### 8. What This Does NOT Change

- Grid structure, column count, tile positions, or responsive behavior
- Hero tile visual weight or span
- Image tiles (artist, replayed, on-repeat) — they don't expand
- Recently played strip
- Split tile compartment model
- Player, queue, search, library, or any other view
- Any database schema or tables (all new queries use existing tables)
