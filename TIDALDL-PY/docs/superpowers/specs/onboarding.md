# Onboarding

> How do we welcome users who don't have a local library yet?
> Brainstorm doc — not scoped, not committed. Just thinking out loud.

---

## The Problem

music-dl assumes you already have music. But many users are coming from:

1. **Tidal subscribers** — thousands of tracks in their cloud library, zero local files
2. **Spotify/Apple Music refugees** — playlists and history trapped in another service
3. **True neophytes** — never owned a music file, grew up streaming

The app today drops them into an empty Home view. No hero wall, no stats, no tiles. Dead on arrival.

---

## User Profiles

### 1. Tidal Power User (Already Authenticated)
- Has a massive Tidal library (favorites, playlists, history)
- Wants to own their music locally in FLAC/MQA
- **Path:** Tidal library → bulk download → local library grows organically
- **What they need:** A guided "Download your favorites" flow. Pick artists/albums/playlists → queue downloads → watch library populate in real time.

### 2. Cross-Service Migrator (Spotify, Apple Music, Deezer, etc.)
- Has years of listening history locked in another platform
- Needs playlist/library transfer before downloading
- **Soundiiz angle:** Soundiiz transfers playlists between services (not files). Could map Spotify playlists → Tidal playlists → music-dl downloads them.
- **What they need:** "Import from Spotify" → Soundiiz transfers playlist to Tidal → music-dl downloads the tracks. Three-step migration.

### 3. Streaming Neophyte
- Has been renting music their whole life
- Understands the appeal of ownership but doesn't know where to start
- **What they need:** The "first download" moment to feel rewarding. Show the FLAC badge, the file on disk, the "this is yours forever" message. Make ownership tangible.

---

## Questions to Answer

- What does the Home view show when the library is empty? (Not a blank page — something welcoming)
- Can we pull the user's Tidal favorites/playlists and present them as "Ready to download"?
- Is Soundiiz API accessible programmatically, or is it manual-only?
- Should we show a progress view during first bulk download? ("Building your library... 47/312 tracks")
- How do we handle the gap between "downloading" and "library ready"? (Scan runs after download?)
- Do we auto-scan after each download completes, or batch?

---

## Ideas Parking Lot

_Raw ideas. No filtering._

- Empty-state Home view: "Your record collection starts here" with a big download CTA
- Tidal library browser: show user's Tidal favorites as a grid, checkboxes to select what to download
- Download progress as a live feed on Home (tracks appearing on the hero wall as they complete)
- First-run wizard: "Where do you want your music stored?" → "Connect Tidal" → "Pick your first albums"
- Quality selector on first run: explain FLAC vs AAC vs MQA in human terms
- "Import playlist" button that accepts Soundiiz export or Spotify URI
- Achievement unlocks: "First album downloaded", "100 tracks owned", "Your library is bigger than 90% of users"
- Show disk space used vs streaming equivalent cost ("You own 4,000 tracks — that's 3 years of Spotify saved")
- Real waveform bars: pre-compute waveform shape per track server-side (or on first play via `fetch` + `decodeAudioData` on a *separate* buffer — never touch the playback audio element). Store bar heights in DB, render as static SVG/CSS. Bars look alive without polluting the audio signal path. Hard rule: `createMediaElementSource` is banned — audio goes native `<audio>` → DAC, untouched.
