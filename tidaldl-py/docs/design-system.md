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
| Overlays | 200 | `.confirm-overlay`, `.shortcuts-overlay`, `.home-fan-overlay` |
| Wizard | 1000 | `.setup-wizard` |
| Context menu | 9999 | `.ctx-menu` |

---

## 2. Bento Grid — The Sacred Layout

**The layout is sacred. Never change grid structure, tile positions, or visual hierarchy.**

### Grid

- Columns: `repeat(var(--cols), 1fr)` — cols set dynamically via ResizeObserver: `Math.max(2, Math.min(6, Math.floor(width / 280)))`
- Gap: `12px`
- Compact mode: `density-compact` is applied to `.home-grid` at two columns
  and hides lower-priority tiered tiles

### Tile Size Classes

| Class | Grid Span | Used For |
|-------|-----------|----------|
| Hero | `span 2` | Top artist, most replayed |
| Standard | `span 1` | Genre, listening time, tracks, albums |
| Half | 50% of a standard tile | Two cards stacked in one compartment |

### The Compartment Model

**Tiles are compartments. Cards are entities.**

A tile (compartment) is a fixed grid slot. It never moves, never resizes, never changes. A card is what lives inside it — an independent entity with its own format, behavior, data, and interactions.

- A compartment can hold one card, two half-cards, or any subdivision we decide.
- A card does NOT know what compartment it lives in. It follows its own format (A or B), has its own click behavior, its own inspect deck.
- When a card animates (e.g., inspect), only that card is affected. Sibling cards in the same compartment are untouched.
- New features go into existing compartments by subdivision, not by adding rows or sections. A subdivided compartment becomes a transparent container holding independent cards.
- Card sizes can change within a compartment. The compartment is the constraint; the card is the content.

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
| Artist tile | Navigate to artist view (`artist:`). Do not open the insight fan. |
| Most Replayed tile | Play track |
| On Repeat half | Play track (does not open the fan) |
| Genre tile | Open the local insight fan overlay |
| Listening time / tracks / albums tiles | Open the local insight fan overlay |

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
- Home fan spring: CSS `linear()` sampled from GSAP `elastic.out(1.05, .78)`, 1.2s, 0.06s stagger. No GSAP.

**Reduced motion:** All animations reduced to 0.01ms via `prefers-reduced-motion: reduce`. The Home insight fan also skips the elastic arc and shows one static centered card plus chevrons.

---

## 7. Component Reference

### Player Bar
- 96px height, 3-column grid: `1fr 1fr 1fr`
- Glassmorphism: `backdrop-filter: blur(60px) saturate(1.3)`
- Play button: 42px circle, `--text` bg, `--bg` icon
- `#now-download` is hidden when the playing track is already on disk (`is_local`, `path` / `local_path`, or audio src `/api/playback/local`). No extra player chrome.
- `#now-source` reuses the track-row `source-tag` / `local-tag` / `tidal-tag` chip and names `local` or `tidal` from the audio src (`/api/playback/local` vs `/api/playback/stream/`), then on-disk flags vs Tidal id. Hidden when idle.

### Home insight fan
- Quiet overlay on `.main` (not a hash view). Data tiles stash the already-loaded `GET /home` payload on `_homeData` and open `_openHomeInsightFan`. No extra network call. Play history never leaves the machine.
- Cards are number/label portraits built only from fields present on that payload: `total_plays`, `listening_time_hours`, `top_artist` / `top_artists`, `most_replayed`, `track_count`, `album_count`, `genre_breakdown`, `weekly_activity`, `this_week`, `recent_albums` (names only). Skip empty cards. Do not invent stats. First-paint `/home` uses `extras=False`, so `recent_albums` is usually absent and that card is skipped.
- Hierarchy on each card: gold serif hero, uppercase label, optional detail, then 1–3 left-aligned `.home-fan-fact` lines in the middle. Facts come from unused `/home` fields already on the payload (`streak`, `most_replayed`, collection size, `this_week.most_replayed` / `genre_breakdown`, `top_artist.genre` / `album_count` / `track_count`, weekly peak). Skip a fact when the value is missing or zero. Empty library stays empty.
- Motion: max 7 visible, center slot 3, published FAN_POSITIONS. Entrance from a stacked deck (`y: 12rem`, `scale: 0.5`) into the arc. Chevrons cycle `centerIndex`. Dots only when there are more than 7 cards. Counts ease; they do not snap.
- Dismiss: Escape, overlay click, `.home-fan-back`, and `navigate(view, opts)` (sidebar `{ jump: true }` included). `.nav-back` stays the drill-in stack control. Artist tiles stay `navigate('artist:' + name)`.

### Queue Panel
- Fixed right, 380px wide, slide-in
- Background: `rgba(22, 20, 19, 0.95)` + blur(40px)

### Track List
- Grid: `40px 44px 1fr 1fr 72px 52px 44px 52px 84px 32px`
- `.track-actions` is a flex row (`gap: 12px`, same as the track grid) so the source-tag (`tidal` / `local`) does not sit flush against the download icon. The 84px column is label + gap + 40px `.dl-btn`. Do not letter-space the source word.
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
- Focus: accent border glow (`0 0 0 4px var(--accent-glow)`). `.search-area` keeps a 16px column gap; `.filter-pills` adds `padding: 8px 2px 0` so a 36px active chip cannot kiss that gold rail.
- Filter / Library sort chips: shared `.pill` is a flex-centered 36px capsule (`align-items` + `justify-content: center`). Do not give `.pill.active` a different height or padding. Album search chips stay smaller (`.album-search-filters .pill` min-height 28px). `button.pill` uses the same chrome.

### Nav Back
- Quiet 24px chevron (`.nav-back`) on drill-in views (`artist:`, `localalbum:`, `localrelease:`, `album:`) when the nav stack is non-empty
- Hidden on top-level sidebar views, including `recent-added`, and when the stack is empty
- Muted color, gold accent on hover; `aria-label="Back"`
- Sits on the existing breadcrumb/header row — not a toolbar
- Sidebar nav items and Sync Library are jumps (clear the stack). They do not walk it.

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
