# Build Loop Log

Build site: context/plans/build-site.md

### Iteration 1 — 2026-04-19
- T-001, T-002, T-003, T-004, T-005, T-006, T-007, T-008: Tier 0 — DONE. Files: security.py, bot.py, __init__.py, local_playlist_resolver.py, test_bot_api.py, test_local_playlist_resolver.py, config.ts, config.test.ts, queue.ts, queue.test.ts, player.ts, errors.ts, errors.test.ts. Build P, Tests P (24+31+21=76 total). Next: T-009, T-010, T-011, T-012, T-013

### Iteration 2 — 2026-04-19
- T-009, T-010, T-011, T-012, T-013: Tier 1 — DONE. Files: bot.py (resolve/playable/download/downloads endpoints), playback.py (+bot-stream), auth.ts, musicDlClient.ts + tests. Build P, Tests P (58+47=105 total). Commit a8e652b. Next: T-014 (slash commands), T-015 (audio pipeline)

### Iteration 3 — 2026-04-19
- T-014, T-015: Tier 2 — DONE. Files: commands.ts (11 slash commands + dispatcher), index.ts (entrypoint w/ REST command registration), player.ts (Playback class extending VoiceManager), commands.test.ts, player.test.ts. Build P, Tests P (46 backend + 87 bot = 133 total). Next: Codex review, then T-016 + T-017 (Tier 3)
