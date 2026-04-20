---
created: 2026-04-19
last_edited: 2026-04-19
---
# Implementation Tracking: bot-api

Build site: context/plans/build-site.md

| Task | Status | Notes |
|------|--------|-------|
| T-001 | DONE | Bearer auth middleware + validate_bot_bearer(), CSRF bypass for /api/bot/ |
| T-002 | DONE | HMAC-SHA256 stream token sign/verify with bounded TTL (120s default) |
| T-003 | DONE | Local playlist resolver: resolve_playlist_name() + parse_playlist_file() |
| T-004 | DONE | Bot API doesn't log tokens by design; verified via test |
| T-009 | DONE | Input resolution — all 4 forms (Tidal track/playlist URLs, local playlist name, free text with 5-choice cap, locals prioritized) |
| T-010 | DONE | Playable endpoint + /api/playback/bot-stream/{token} for local and Tidal-backed streaming |
| T-011 | DONE | Download gateway — trigger via /api/bot/download, poll via /api/bot/downloads/{job_id} |
