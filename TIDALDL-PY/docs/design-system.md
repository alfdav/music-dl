# music-dl Design System Reference

> Single source of truth for all UI decisions. Every component must follow these patterns.
> If it's not in this document, it's not a decision — it's a bug.

## 1. Design Tokens

### Colors

| Token | Value | Purpose |
|-------|-------|---------|
| `--bg` | `#0f0e0d` | Primary background (near-black warm) |
| `--bg-warm` | `#161413` | Elevated surfaces (toasts, modals, queue) |
| `--surface` | `rgba(255, 245, 235, 0.04)` | Card/surface fill |
| `--surface-hover` | `rgba(255, 245, 235, 0.07)` | Surface on hover |
| `--surface-active` | `rgba(255, 245, 235, 0.10)` | Surface on press |
| `--glass` | `rgba(22, 20, 19, 0.75)` | Glass-morphism base |
| `--glass-border` | `rgba(255, 245, 235, 0.06)` | Subtle divider/border everywhere |
| `--text` | `#f0ebe4` | Primary text (warm off-white) |
| `--text-secondary` | `rgba(240, 235, 228, 0.65)` | Secondary text (subtitles) |
| `--text-muted` | `rgba(240, 235, 228, 0.45)` | Muted text (labels, hints) |
| `--accent` | `#d4a053` | Primary accent — warm gold |
| `--accent-dim` | `rgba(212, 160, 83, 0.15)` | Accent background tint |
| `--accent-glow` | `rgba(212, 160, 83, 0.08)` | Subtle accent glow |
| `--green` | `#7ec97a` | Success/connected |
| `--green-dim` | `rgba(126, 201, 122, 0.12)` | Green tint |
| `--red` | `#e06060` | Error/danger |

### Typography

| Token | Value | Usage |
|-------|-------|-------|
| `--serif` | `'Crimson Pro', Georgia, serif` | Titles, track names, album names, headings, bento-label |
| `--sans` | `'Outfit', system-ui, sans-serif` | Body text, UI labels, buttons (body default) |
| `--mono` | `'JetBrains Mono', monospace` | Badges, quality tags, nav labels, bento-sub, bento-stat |

### Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius` | `12px` | Cards, bento tiles, modals |
| `--radius-sm` | `8px` | Track rows, nav items, album art |
| `--radius-xs` | `5px` | Small elements, quality tags |

### Z-index Stack

| Layer | Z | Element |
|-------|---|---------|
| Ambient | 0 | `.ambient` |
| App | 1 | `.app` |
| Sticky headers | 2 | `.artist-group-header` |
| Bento hints | 3 | `.bento-hint`, `.bento-chevron` |
| Player | 10 | `.player` |
| Queue | 50 | `.queue-panel` |
| Toasts | 100 | `.toast-container` |
| Overlays | 200 | `.confirm-overlay`, `.shortcuts-overlay` |
| Wizard | 1000 | `.setup-wizard` |
| Context menu | 9999 | `.ctx-menu` |

---

## 2. Bento Grid — The Sacred Layout

**The layout is sacred. Never change grid structure, tile positions, or visual hierarchy.**

### Grid

- Columns: `repeat(var(--cols), 1fr)` — cols set dynamically via ResizeObserver: `Math.max(2, Math.min(6, Math.floor(width / 280)))`
- Gap: `12px`
- Density classes on `.home-wrap`: `home-sparse` (≤4), `home-moderate` (5-6), `home-dense` (7+)

### Tile Size Classes

| Class | Grid Span | Used For |
|-------|-----------|----------|
| Hero | `span 2` | Top artist, most replayed |
| Standard | `span 1` | Genre, listening time, tracks, albums |
| Half | 50% of a standard tile | Two cards stacked in one compartment |

### The Compartment Model

Tiles are compartments. New features go into existing compartments by subdivision, not by adding rows or sections. A subdivided tile becomes a transparent container holding two cards.

---

## 3. Tile Formats — THE LAW

There are exactly **two** tile formats. Every tile must use one of them.

### Format A: Image Tile (Artists, Most Replayed, On Repeat)

Content sits at the bottom over a background image. Used when the tile represents an entity with cover art.

**DOM:**
```
div.bento-tile
  img.bento-bg-art          ← absolute, full cover, opacity 0.4
  div.bento-overlay          ← absolute, gradient scrim for readability
  div.bento-body             ← relative, z:1, flex column, justify-end, padding 16px
    div.bento-label          ← name (serif, large)
    div.bento-sub            ← key metric (mono, accent color)
    div.bento-stat           ← detail line (muted)
```

**CSS anatomy:**
- `.bento-bg-art`: `position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0.4`
- `.bento-overlay`: `position: absolute; inset: 0; background: linear-gradient(180deg, rgba(0,0,0,0.1), rgba(0,0,0,0.5))`
- `.bento-body`: `position: relative; z-index: 1; display: flex; flex-direction: column; justify-content: flex-end; padding: 16px`

**Text hierarchy:**
| Element | Font | Size | Color | Example |
|---------|------|------|-------|---------|
| `.bento-label` | `--serif` | 1.1rem (hero: 1.5rem) | `--text` | "Daft Punk", "Soul Creation" |
| `.bento-sub` | `--mono` | 0.8rem (hero: 0.95rem) | `--accent` | "34 plays", "9 plays this week" |
| `.bento-stat` | default | 0.65rem | `--accent` | "89 tracks · 8 albums · Dance" |

**Reference implementations:** `_artistTile()`, `_replayedTile()`, `_onRepeatHalf()`

### Format B: Stat Tile (Genre, Listening Time, Tracks, Albums)

Content starts at the top. Chart/visualization pushed to the bottom. Used for aggregate data.

**DOM:**
```
div.bento-tile.bento-stat-tile
  div.bento-body             ← flex column, justify-start, padding 14px
    div.bento-label          ← big value (serif, accent, 1.5rem)
    div.bento-stat-label     ← descriptor (muted, uppercase-ish)
    div.bento-insight        ← contextual text (optional)
    div.mini-bar-chart       ← visualization, margin-top: auto (pushed to bottom)
    div.bento-detail         ← expandable details (optional)
```

**CSS anatomy:**
- `.bento-stat-tile`: `background: var(--surface); border: 1px solid var(--glass-border)`
- `.bento-stat-tile .bento-body`: `justify-content: flex-start; padding: 14px`
- `.bento-stat-tile .mini-bar-chart, .mini-weekly-chart`: `margin-top: auto` (pushes chart to bottom)

**Text hierarchy:**
| Element | Font | Size | Color | Example |
|---------|------|------|-------|---------|
| `.bento-label` | `--serif` | 1.5rem | `--accent` | "Pop", "11h", "847" |
| `.bento-stat-label` | default | 0.75rem | `--text-muted` | "RECENT GENRE", "LISTENING TIME", "TRACKS" |
| `.bento-insight-line` | default | 0.8rem | `--text-muted` | "You listen most on Tuesdays" |
| `.insight-gold` | default | inherit | `--accent`, weight 500 | "Tuesdays" (keyword highlight) |

**Reference implementations:** `_genreTile()`, `_listeningTimeTile()`, `_tracksTile()`, `_albumsTile()`

---

## 4. Split Tile (Two Cards in One Compartment)

When a standard tile is subdivided, the outer tile becomes a transparent compartment and each half becomes its own card.

**Outer container (`.bento-split`):**
```css
display: flex;
flex-direction: column;
gap: 6px;
background: transparent;
border: none;
padding: 0;
```

**Each half (`.bento-half`):**
- Gets its own `background: var(--surface)`, `border`, `border-radius: var(--radius)`
- Is a self-contained card that follows Format A or Format B exactly
- `flex: 1` to split space equally

**Rules:**
- Genre half follows **Format B** (stat tile pattern — content top, chart bottom)
- On-repeat half follows **Format A** (image tile pattern — bg art, content bottom)
- Each half must be independently correct — you should be able to extract it and it looks like a proper tile

**CSS cascade warning:** The outer tile has class `bento-stat-tile` (for the genre half). This means `.bento-stat-tile .bento-label { color: var(--accent) }` bleeds into the on-repeat half. The on-repeat half must explicitly reset: `.bento-on-repeat .bento-label { color: var(--text) }`.

**Format A half (on-repeat) specifics:**
```css
.bento-split .bento-half.bento-on-repeat {
  position: relative;   /* anchor for absolute bg-art/overlay */
  padding: 0;           /* bg-art fills edge to edge */
  cursor: pointer;
}
.bento-split .bento-half.bento-on-repeat .bento-body {
  flex: 1;              /* fill the half */
  justify-content: flex-end;  /* text at bottom */
  padding: 14px;        /* text breathing room */
  position: relative;
  z-index: 1;           /* above bg-art and overlay */
}
```

**Format B half (genre) specifics:**
```css
.bento-split .bento-half .bento-body {
  padding: 0;           /* half provides padding */
  flex: 1;              /* fill the half so margin-top:auto works on chart */
  display: flex;
  flex-direction: column;
}
/* .mini-bar-chart already has margin-top:auto from .bento-stat-tile rule */
```

---

## 5. Interaction Patterns

### Hover States

| Element | Hover Effect |
|---------|-------------|
| Bento tile | `translateY(-4px)`, shadow `0 8px 20px rgba(0,0,0,0.35)` |
| Stat tile border | `rgba(212, 160, 83, 0.15)` |
| Nav item | `var(--surface-hover)` bg, `--text` color |
| Track row | `var(--surface-hover)` bg |

### Active States

| Element | Active Effect |
|---------|--------------|
| Bento tile | `translateY(-1px) scale(0.99)`, 0.1s |
| Nav item (current) | `--accent` color, `--accent-dim` bg, 3px left bar |

### Click Behaviors

| Element | Action |
|---------|--------|
| Artist tile | Navigate to artist view |
| Most Replayed tile | Play track |
| On Repeat half | Play track |
| Genre tile | Expand detail |
| Stat tile with detail | Toggle expand |

### Accessibility

- `a11yClick(el)`: adds `tabindex="0"`, `role="button"`, Enter/Space keydown
- Applied to all clickable non-button elements
- `:focus-visible`: `2px solid var(--accent)`, `outline-offset: 2px`

---

## 6. Animation Tokens

| Duration | Use |
|----------|-----|
| 0.1s | Active press states |
| 0.12s | Context menu entrance |
| 0.15s | Overlays |
| 0.2-0.3s | Hover transitions, micro-interactions |
| 0.4-0.6s | View transitions, fadeUp |

**Easing curves:**
- Primary: `cubic-bezier(0.22, 0.61, 0.36, 1)` — nav, view transitions
- Bounce: `cubic-bezier(0.34, 1.56, 0.64, 1)` — download button animations
- Expand: `cubic-bezier(0.16, 1, 0.3, 1)` — bento detail reveal

**Reduced motion:** All animations reduced to 0.01ms via `prefers-reduced-motion: reduce`.

---

## 7. Component Reference

### Player Bar
- 96px height, 3-column grid: `1fr 1fr 1fr`
- Glassmorphism: `backdrop-filter: blur(60px) saturate(1.3)`
- Play button: 42px circle, `--text` bg, `--bg` icon

### Queue Panel
- Fixed right, 380px wide, slide-in
- Background: `rgba(22, 20, 19, 0.95)` + blur(40px)

### Track List
- Grid: `40px 44px 1fr 1fr 72px 52px 52px 40px 32px`
- Playing state: `--accent-glow` bg, gold left bar, accent track name
- Min height: 44px per row

### Quality Tiers (RPG-inspired)

| Tier | Class | Description |
|------|-------|-------------|
| Common | `.quality-common` | LOW / unknown — grey |
| Uncommon | `.quality-uncommon` | HIGH 320kbps — green |
| Rare | `.quality-rare` | LOSSLESS / CD 16-bit — blue |
| Epic | `.quality-epic` | HI_RES / MQA — purple |
| Legendary | `.quality-legendary` | HI_RES_LOSSLESS / 24-bit — gold |
| Mythic | `.quality-mythic` | DOLBY ATMOS / Spatial — gold-cream |

### Toast Notifications
- Position: bottom-right, 112px from bottom
- Auto-dismiss: 3s (5s for errors)
- Variants: default, `.error` (red), `.success` (green)

### Search
- Debounce: 300ms
- Input: pill-shaped, 40px radius
- Focus: accent border glow

---

## 8. Security Conventions

- All user data flows through `textContent` / `textEl()` — never `innerHTML`
- `innerHTML` only for static SVG icon constants
- CSRF token via `<meta name="csrf-token">`, sent as `X-CSRF-Token` header
- Global 409 handler for operation-in-progress conflicts

---

## 9. Sacred Rules

1. **Layout is sacred.** Grid structure, tile positions, visual hierarchy never change.
2. **Tiles are compartments.** New features subdivide existing tiles, never add rows.
3. **No new sections or labels.** Data gets fresher silently — no "This Week" / "All Time" headers.
4. **Two formats only.** Image tiles (Format A) and stat tiles (Format B). Everything must be one or the other.
5. **Symmetry is non-negotiable.** Visual balance calms anxiety. Never break it.
6. **Audio path is sacred.** No Web Audio API, no signal processing — bit-perfect to DAC.
7. **Copy must sound human.** Warm, not mechanical or corporate.
8. **No emoji as icons.** SVG only.
