---
version: alpha
name: music-dl Listening Room
description: Local-first Tidal music manager with a dark, warm, album-art-forward browser and desktop UI.
colors:
  primary: "#d4a053"
  secondary: "#f0ebe4"
  tertiary: "#161413"
  neutral: "#0f0e0d"
  surface: "#1a1814"
  surface-elevated: "#2a1f14"
  success: "#7ec97a"
  error: "#e06060"
  rare: "#6496dc"
  epic: "#a064dc"
typography:
  display:
    fontFamily: Crimson Pro
    fontSize: 38px
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: 0px
  headline:
    fontFamily: Crimson Pro
    fontSize: 28px
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: 0px
  title:
    fontFamily: Crimson Pro
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.3
    letterSpacing: 0px
  body:
    fontFamily: Outfit
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0px
  body-small:
    fontFamily: Outfit
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: 0px
  label:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0.08em
  badge:
    fontFamily: JetBrains Mono
    fontSize: 9px
    fontWeight: 500
    lineHeight: 1
    letterSpacing: 0.08em
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  player-height: 96px
  sidebar-width: 240px
  queue-width: 380px
rounded:
  xs: 5px
  sm: 8px
  md: 12px
  pill: 999px
  circle: 999px
components:
  app-background:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.secondary}"
    typography: "{typography.body}"
  surface-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.secondary}"
    rounded: "{rounded.md}"
    padding: "{spacing.lg}"
  surface-elevated:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.secondary}"
    rounded: "{rounded.md}"
    padding: "{spacing.xl}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.neutral}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: 12px
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.secondary}"
    typography: "{typography.body-small}"
    rounded: "{rounded.sm}"
    padding: 8px
  nav-active:
    backgroundColor: "{colors.surface-elevated}"
    textColor: "{colors.primary}"
    typography: "{typography.body-small}"
    rounded: "{rounded.sm}"
    padding: 10px
  track-row:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.secondary}"
    typography: "{typography.body-small}"
    rounded: "{rounded.sm}"
    padding: 10px
  track-playing:
    backgroundColor: "{colors.surface-elevated}"
    textColor: "{colors.primary}"
    typography: "{typography.body-small}"
    rounded: "{rounded.sm}"
    padding: 10px
  quality-success:
    backgroundColor: "{colors.success}"
    textColor: "{colors.neutral}"
    typography: "{typography.badge}"
    rounded: "{rounded.xs}"
    padding: 4px
  quality-error:
    backgroundColor: "{colors.error}"
    textColor: "{colors.neutral}"
    typography: "{typography.badge}"
    rounded: "{rounded.xs}"
    padding: 4px
  quality-rare:
    backgroundColor: "{colors.rare}"
    textColor: "{colors.neutral}"
    typography: "{typography.badge}"
    rounded: "{rounded.xs}"
    padding: 4px
  quality-epic:
    backgroundColor: "{colors.epic}"
    textColor: "{colors.neutral}"
    typography: "{typography.badge}"
    rounded: "{rounded.xs}"
    padding: 4px
---

# DESIGN.md

This file is the agent-readable design contract for `music-dl`. The YAML front matter contains the normative tokens. The prose explains how to apply them. The implementation source remains `tidaldl-py/tidal_dl/gui/static/style.css`; the detailed human reference remains `tidaldl-py/docs/design-system.md`.

## Overview

`music-dl` should feel like a private listening room: dark, warm, tactile, local-first, and quiet enough for long library sessions. It is not a SaaS dashboard and not a marketing page. The UI should prioritize browsing, scanning, playback control, and quick confidence about local library state.

The product surface is one shared browser UI used by both `music-dl gui` and the Tauri desktop shell. Do not fork desktop and browser styling. The desktop app is a thin shell around the same localhost FastAPI/static frontend.

Visual hierarchy comes from album art, warm contrast, restrained gold highlights, compact controls, and clear active state. The interface can be rich, but it must stay practical: no decorative sections, no hero marketing blocks, no feature explainer copy inside the app.

## Colors

The palette is a warm near-black room with one primary gold accent.

- **Primary (`#d4a053`):** warm gold for active navigation, important actions, progress, focus rings, and current playback.
- **Secondary (`#f0ebe4`):** warm off-white for primary text and high-contrast controls.
- **Tertiary (`#161413`):** elevated warm black for panels, modals, toasts, and queue surfaces.
- **Neutral (`#0f0e0d`):** app background.
- **Surface (`#1a1814`):** base card and bento tile fill.
- **Surface elevated (`#2a1f14`):** richer brown-black used for gold-forward cards and active rows.
- **Success (`#7ec97a`):** connected, complete, and healthy states.
- **Error (`#e06060`):** destructive, failed, disconnected, and read-only warning states.

Current CSS uses translucent surface tokens such as `rgba(255, 245, 235, 0.04)` and `rgba(212, 160, 83, 0.15)`. Keep those as alpha treatments of the tokens above; do not introduce a new color family for hover, pressed, or glass states.

## Typography

Three type families define the interface:

- **Crimson Pro:** titles, album names, track names, bento labels, modal headings. It gives the app its listening-room character.
- **Outfit:** default UI text, buttons, settings rows, helper text, and body copy.
- **JetBrains Mono:** badges, status labels, timestamps, quality tiers, nav labels, progress times, and technical metadata.

Use display sizes only for true page or home greetings. Dense surfaces such as settings rows, queue entries, track lists, and cards should stay compact. Letter spacing is `0` for normal text and only increases on mono labels or badges.

## Layout

The app uses a fixed control shell:

- Sidebar: `240px` desktop navigation.
- Topbar: `48px`.
- Player bar: `96px`, always anchored at the bottom on desktop.
- Queue panel: `380px` slide-in panel on desktop, full width on mobile.
- Main view: scrolls independently inside the shell.

The home view uses the existing bento grid from `tidaldl-py/docs/design-system.md`. Treat the bento grid as a constrained operating surface, not a place to keep adding rows. New home data should reuse existing tile formats or subdivide existing compartments.

Responsive behavior should remove chrome before shrinking content into unreadability. On small screens, hide the sidebar, stack the player controls, and make the queue panel full width.

## Elevation & Depth

Depth is built with translucent layers, borders, blur, and album-art glow. Heavy shadows are reserved for overlay cards, player artwork, and hover lift. Most hierarchy should come from contrast and containment.

Use:

- `1px` translucent borders for panels and cards.
- Backdrop blur for sidebar, topbar, player, queue, overlays, and update banners.
- Subtle hover lift for bento cards and album cards.
- Accent glow only around current playback, progress, and focus.

Avoid bright drop shadows, neon glows, and generic gradient decoration. Album art can be atmospheric; anonymous decorative blobs should not carry the visual identity.

## Shapes

Default shape language is softly squared:

- `5px` for tiny affordances, quality tags, and small artwork.
- `8px` for nav items, track rows, album art, and compact controls.
- `12px` for panels, bento tiles, modals, and cards.
- Full radius only for circles, pills, toggles, progress thumbs, and round transport controls.

Do not mix sharp and highly rounded components in the same small surface. Cards are allowed, but nested card stacks should be avoided.

## Components

### Shell

The sidebar is quiet and utility-first: mono section labels, compact nav rows, SVG icons, and a gold active rail. The current view is indicated by gold text, a tinted background, and a 3px left marker.

The player is the primary persistent control surface. Keep the three-zone desktop structure: now playing, transport/progress, and volume/secondary controls. The play button stays a filled circle; secondary transport controls stay icon-only.

### Search And Lists

Search input is pill-shaped with an inline icon and gold focus glow. Result rows are dense, scannable, and stable: artwork, track metadata, album, quality, format, play count, duration, and actions should not shift layout on hover.

Track names and album titles use Crimson Pro. Metadata, counts, durations, and quality tags use JetBrains Mono where precision matters.

### Bento Tiles

Only two tile formats are approved:

- **Image tiles:** background artwork, gradient scrim, text anchored at bottom.
- **Stat tiles:** value and descriptor at top, chart or insight content pushed to bottom.

Split tiles are compartments containing independent cards. The container is not itself a visual card.

### Badges And Status

Quality tiers are intentionally muted so they inform without overpowering album art. Gold is reserved for the highest quality and primary activity; blue and purple appear only in quality or rarity contexts.

Connection dots, download status, server health, and update status should use semantic green/red/gold consistently.

### Overlays

Queue, lyrics, shortcuts, inspect cards, setup wizard, and modals use the same dark surface, translucent border, blur, and compact control language. Overlay text must stay useful and brief.

## Do's and Don'ts

- Do keep `DESIGN.md`, `tidaldl-py/docs/design-system.md`, and `style.css` aligned when changing visual tokens or core component patterns.
- Do use the existing vanilla JS and CSS variable system. No frontend framework or build step for styling.
- Do keep browser and Tauri desktop styling identical.
- Do use SVG icons for controls and status affordances. Do not use emoji as icons.
- Do preserve direct `<audio>` playback. No Web Audio API or visual design that implies audio processing.
- Do keep surfaces dense and scannable; this is a music manager, not a landing page.
- Do make every hover-only action available on touch or keyboard.
- Don't add new tile formats without replacing this file and `tidaldl-py/docs/design-system.md`.
- Don't add decorative orbs, generic gradients, or stock-style imagery.
- Don't introduce a second accent color for primary actions.
- Don't let text wrap unpredictably inside track rows, queue rows, badges, or transport controls.
- Don't create separate desktop-only design rules unless the Tauri shell truly requires them.
