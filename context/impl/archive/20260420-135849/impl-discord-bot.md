---
created: 2026-04-19
last_edited: 2026-04-19
---
# Implementation Tracking: discord-bot

Build site: context/plans/build-site.md

| Task | Status | Notes |
|------|--------|-------|
| T-005 | DONE | Bun scaffold + parseConfig() validates 7 env vars |
| T-006 | DONE | QueueState: append/advance/clear, repeat off/one/all (default: all) |
| T-007 | DONE | VoiceManager: join/leave, bounded reconnect (3 retries), single-channel |
| T-008 | DONE | Error reporting: ErrorKind classification, safe user messages |
| T-012 | DONE | Authorization gate: ensureAuthorized() checks guild+channel+user with discriminated result |
| T-013 | DONE | Typed backend client with bearer auth, AbortController timeouts, MusicDlError taxonomy |
| T-014 | DONE | 11 slash commands + dispatcher with auth gate; /play never downloads; index.ts entrypoint |
| T-015 | DONE | Playback class: playCurrent/skip/pause/resume/setVolume; auto-advance on Idle+error; bounded failure chain |
| T-016 | DONE | picker.ts: buttons-based visible picker with 30s timeout, component-clearing on finalize |
| T-016 | PENDING | Visible picker for free-text search |
