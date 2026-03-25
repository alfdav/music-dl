# Quality Upgrade Scanner

> Scan your local library against Tidal's catalog and find tracks available at higher quality.
> We don't touch the music. We only replace it with something better.

---

## The Problem

Users accumulate music over years from various sources — old MP3 rips, AAC downloads, lossy conversions. They now have Tidal access with FLAC/MQA/HiRes available. But they don't know which of their 10,000 tracks could be upgraded.

---

## What It Does

1. **Scan** — Walk the local library, read each file's current quality (codec, bitrate, bit depth, sample rate)
2. **Match** — Look up each track on Tidal by ISRC, or fall back to artist + title fuzzy match
3. **Compare** — Check if Tidal offers a higher quality version (FLAC > MP3, HiRes > CD, MQA > lossy)
4. **Report** — Present a list: "247 tracks upgradeable" with before/after quality comparison
5. **Upgrade** — User picks which tracks to re-download. Old file replaced (or kept as backup)

---

## Quality Hierarchy (highest to lowest)

1. HiRes FLAC (24-bit / 96kHz+)
2. MQA (24-bit, folded)
3. CD-quality FLAC (16-bit / 44.1kHz)
4. AAC 320kbps
5. AAC 256kbps
6. MP3 320kbps
7. MP3 256kbps
8. MP3 < 256kbps

---

## Matching Strategy

- **ISRC first** — read ISRC tag from file metadata, match against Tidal catalog. Exact match, no ambiguity.
- **Fuzzy fallback** — artist + title + album + duration match. Accept only high-confidence matches to avoid wrong-version swaps.
- **Duration sanity check** — reject matches where duration differs by more than 5 seconds (different edit/version).

---

## Questions to Answer

- Do we replace in-place or download to a staging area for user approval?
- Preserve original file as `.bak` or trust the user reviewed the upgrade list?
- How do we handle albums where only some tracks are upgradeable? (Partial album upgrade)
- Rate limiting — Tidal API calls per track. For 10k tracks, need batching and throttling.
- Should this run automatically after every scan, or on-demand only?
- Can we show quality distribution stats on Home? ("78% FLAC, 15% MP3, 7% AAC — 247 upgradeable")

---

## Ideas Parking Lot

_Raw ideas. No filtering._

- Quality badges in library view: color-coded by tier (gold = HiRes, silver = FLAC, red = MP3)
- "Upgrade All" button with progress bar
- Side-by-side A/B comparison: play 10s of old vs new quality before committing
- Weekly quality digest: "12 new upgrades available since last scan"
- Priority sort: upgrade most-played tracks first (you listen to these — they deserve the best)
- Space impact calculator: "Upgrading 247 tracks will use 3.2 GB additional storage"
- Tag preservation: ensure all custom tags, play counts, and ratings survive the file swap
