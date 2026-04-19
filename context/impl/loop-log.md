# Build Loop Log

Build site: context/plans/build-site.md

### Iteration 1 — 2026-04-19
- T-001, T-002, T-003, T-004, T-005, T-006, T-007, T-008: Tier 0 — DONE. Files: security.py, bot.py, __init__.py, local_playlist_resolver.py, test_bot_api.py, test_local_playlist_resolver.py, config.ts, config.test.ts, queue.ts, queue.test.ts, player.ts, errors.ts, errors.test.ts. Build P, Tests P (24+31+21=76 total). Next: T-009, T-010, T-011, T-012, T-013

### Iteration 2 — 2026-04-19
- T-009, T-010, T-011, T-012, T-013: Tier 1 — DONE. Files: bot.py (resolve/playable/download/downloads endpoints), playback.py (+bot-stream), auth.ts, musicDlClient.ts + tests. Build P, Tests P (58+47=105 total). Commit a8e652b. Next: T-014 (slash commands), T-015 (audio pipeline)

### Iteration 3 — 2026-04-19
- T-014, T-015: Tier 2 — DONE. Files: commands.ts (11 slash commands + dispatcher), index.ts (entrypoint w/ REST command registration), player.ts (Playback class extending VoiceManager), commands.test.ts, player.test.ts. Build P, Tests P (46 backend + 87 bot = 133 total). Next: Codex review, then T-016 + T-017 (Tier 3)

### Codex review — Tier 2 — 2026-04-19
- Converged after 5 rounds. 11 findings addressed total:
  - F-T2-001 (P1): /play rollback on playCurrent failure (queue wedge)
  - F-T2-002 (P2): /download disambiguation + playlist iteration
  - F-T2-003 (P3): /queue marker by position, not item id
  - F-T2-004 (P2): batch download summary (prevent editReply race)
  - F-T2-005 (P2): classify trigger errors, not hard-code BackendUnavailable
  - F-T2-006 (P1): transient poll errors preserve status
  - F-T2-007 (P2): per-tick fan-out via Promise.allSettled (superseded by F-T2-009)
  - F-T2-008 (P1): differentiate transient vs permanent MusicDlError in poll
  - F-T2-009 (P2): per-job poll loops (replace tick-based)
  - F-T2-010 (P1): serialize batch edits + coalesce via dirty flag
  - F-T2-011 (P2): restore "(stopped polling)" suffix on timeout
- Final: 46 backend + 98 bot = 144 tests passing. Commits 09509ac → 01a7c3f.
