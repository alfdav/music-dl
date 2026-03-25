# DJAI Feature Backlog

> Centralized list of features to brainstorm and build for DJAI (Lab section).
> Add ideas here as they come up. Each gets brainstormed properly before implementation.

## Core Identity

DJAI is the user's personal AI DJ. It knows your library, your taste, your history. It doesn't recommend like Spotify — it narrates, curates, and celebrates what you already own. BYOK API key.

---

## Features

### 1. Mood-Based Picks
**Status:** Placeholder in UI
**What:** User picks a mood → DJAI selects 5-6 tracks from their local library that match. Expands the existing "I'm feeling lucky" button.
**Data needed:** Genre tags, tempo (BPM), energy level, track metadata.

### 2. Rotating Hero Card Fun Facts
**Status:** Idea
**What:** DJAI generates fun facts about artists shown on Home hero cards. Pre-generated, stored in DB, rotate on each visit.
**Examples:**
- "Adele's *21* spent 24 weeks at #1"
- "*NSYNC sold 2.4M copies of No Strings Attached in its first week"
- "Aerosmith's *I Don't Want to Miss a Thing* was written by Diane Warren, not the band"

### 3. New / Upcoming Releases
**Status:** Idea
**What:** Surface new disc releases from artists the user plays. Tidal API may already expose this (user is authenticated). Show as a section below bento grid — "New from your artists."
**Dependency:** Tidal API investigation needed.

### 4. Detailed Stats View ("Check My Stats")
**Status:** Button exists, navigates to DJAI placeholder
**What:** Full-page breakdown of listening identity. Top artists over time, genre evolution, quality tier distribution, most played tracks, listening streaks, day/hour heatmap.

### 5. Sweet Fades / Track Blending (Plexamp-style)
**Status:** Researched
**What:** Tracks crossfade naturally based on their audio content — not a fixed timer. Inspired by Plexamp's "Sweet Fades" (derived from MPD's MixRamp).
**How it works:**
- Dual `<audio>` elements with separate `GainNode`s — one plays current, one pre-loads next
- Equal power crossfade curve: `Math.cos(percent * 0.5 * Math.PI)` — avoids volume dip
- Exponential gain ramps via `exponentialRampToValueAtTime` for natural sound
- Smart overlap: pre-decode last ~10s, find where energy drops below -30dB, start fade there
- Same-album detection: skip crossfade for consecutive album tracks (true gapless)
- Default 3-5 seconds if analysis is skipped
**Complexity:** High — dual audio pipeline, pre-buffering, gain scheduling, album boundary detection.
**Research source:** Plexamp uses server-side EBU R128 loudness analysis + MixRamp tags. We'd approximate client-side.

### 6. Concerts & Live Events
**Status:** Parked for future
**What:** Show upcoming concerts for artists the user plays. Requires external API (Ticketmaster, Bandsintown, Songkick). High maintenance — park until a clean free API is found.

---

## Ideas Parking Lot

_Drop raw ideas here. No filtering, no judgment. Brainstorm later._

- Artist comparison: "You have more Linkin Park than 97% of users" (needs anonymized benchmarks — may not be feasible)
- "On this day" — what you were listening to a year ago (needs play history depth)
- Playlist generator from mood/activity prompt
- "Discover your own library" — surfaces tracks you own but never played
- Genre journey visualization — how your taste evolved over time
- Volume normalization (ReplayGain 2 / EBU R128) — level loudness across tracks so transitions are smooth even without crossfade
- Pre-buffer next track 10s before current ends — eliminates gap even without crossfade
