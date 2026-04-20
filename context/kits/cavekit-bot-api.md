---
created: 2026-04-19
last_edited: 2026-04-19
---

# Cavekit: Bot API

## Scope

Backend API surface that music-dl exposes exclusively for the Discord bot. Covers authentication, input resolution, playable source generation, download gating, and local playlist resolution. This API is separate from the GUI-facing API and uses its own authentication model.

## Requirements

### R1: Dedicated Bearer Token Authentication

**Description:** Bot-facing API endpoints must authenticate requests using a dedicated bearer token loaded from an environment variable. This authentication model must not reuse the GUI's session or CSRF token mechanism.

**Acceptance Criteria:**
- [ ] A request to any bot API endpoint without an `Authorization` header returns HTTP 401
- [ ] A request with a malformed or incorrect bearer token returns HTTP 401
- [ ] A request with the correct bearer token (matching the environment-configured value) returns a non-401 response
- [ ] An empty or whitespace-only environment variable for the token causes all bot API requests to return HTTP 401
- [ ] GUI endpoints continue to use their existing authentication and are unaffected by bot auth configuration

**Dependencies:** None

### R2: Input Resolution Endpoint

**Description:** A single endpoint accepts a text query and determines its type, then resolves it into structured results. Four input forms are supported: free text, Tidal track URL, Tidal playlist URL, and local playlist name.

**Acceptance Criteria:**
- [ ] Free-text input returns at most 5 candidate matches, each containing at minimum: identifier, title, artist, and source type
- [ ] A valid Tidal track URL returns exactly 1 resolved item
- [ ] A valid Tidal playlist URL returns an ordered list of resolved items preserving playlist order
- [ ] A local playlist name returns an ordered list of resolved items matching the playlist's track order
- [ ] An unrecognized or empty query returns an error response with a client-level status code (4xx), not a server error
- [ ] Each resolved item includes at minimum: stable identifier, title, artist, source type, local availability flag, and duration
- [ ] The endpoint requires valid bearer token authentication (see R1)

**Dependencies:** R1, R5

### R3: Playable Source Endpoint

**Description:** Given a resolved item identifier, this endpoint returns a short-lived, bot-consumable stream URL that the bot can use to play audio. The URL may serve local files or proxy remote streams, but the bot is not told which.

**Acceptance Criteria:**
- [ ] A valid resolved item identifier returns a response containing: playable URL, content type (if known), and display metadata (title, artist, duration)
- [ ] The playable URL is short-lived (expires after a bounded time window)
- [ ] An expired or invalid playable URL returns HTTP 403 when accessed
- [ ] The endpoint works for both locally-available and remote-backed items
- [ ] The playable URL does not expose raw library filesystem paths to the caller
- [ ] The playable URL does not expose raw remote service credentials or session tokens
- [ ] The endpoint requires valid bearer token authentication (see R1)

**Dependencies:** R1, R4

### R4: Stream Token Signing and Verification

**Description:** Playable source URLs must be protected by short-lived signed tokens. The backend signs tokens when generating playable URLs and verifies them when serving stream content.

**Acceptance Criteria:**
- [ ] A signed token encodes at minimum the item reference and an expiration timestamp
- [ ] A token that has passed its expiration is rejected on verification
- [ ] A token with a tampered payload is rejected on verification
- [ ] Token contents do not appear in application logs
- [ ] Token lifetime is bounded (not indefinite)

**Dependencies:** None

### R5: Local Playlist Resolution

**Description:** The backend can locate and parse local playlist files (.m3u and .m3u8) by name. Name matching is case-insensitive. Parsed playlists yield an ordered list of track references.

**Acceptance Criteria:**
- [ ] A playlist name matching an existing .m3u file (case-insensitive) returns the file's tracks in order
- [ ] A playlist name matching an existing .m3u8 file (case-insensitive) returns the file's tracks in order
- [ ] Comment lines (starting with `#`) and blank lines in playlist files are skipped during parsing
- [ ] A playlist name with no matching file returns an empty result or an error response with a client-level status code (4xx), not a server error
- [ ] Name matching ignores case differences (e.g., "Night Drive" matches "night drive.m3u8")

**Dependencies:** None

### R6: Download Gateway

**Description:** The bot can trigger explicit downloads and poll their status through dedicated bot API endpoints. Download execution is delegated to the existing download subsystem.

**Acceptance Criteria:**
- [ ] A download trigger request with a valid item reference returns an accepted job state with a job identifier
- [ ] A download status request with a valid job identifier returns the current state (queued, in-progress, completed, or failed)
- [ ] A download status request for an in-progress job includes progress information when available
- [ ] A download status request for a completed job includes completion details
- [ ] A download status request for a failed job includes failure details
- [ ] Both endpoints require valid bearer token authentication (see R1)

**Dependencies:** R1

### R7: Logging Safety

**Description:** Bot API logs must not leak sensitive material.

**Acceptance Criteria:**
- [ ] Bearer tokens are not printed in application logs
- [ ] Signed stream tokens/URLs are not printed in full in application logs
- [ ] Remote service session material is not printed in application logs

**Dependencies:** None

## Out of Scope

- GUI endpoint modifications (bot API is additive, not a replacement)
- Multi-tenant or multi-bot authentication
- Rate limiting or abuse prevention (single trusted user, local deployment)
- Persistent download queue (uses existing download subsystem as-is)
- Direct filesystem access by the bot (all access is mediated by this API)
- WebSocket or SSE push for download progress (polling only in v1)
- Remote service credential management (stays in existing backend modules)

## Cross-References

- See also: [cavekit-discord-bot.md](cavekit-discord-bot.md) -- the bot runtime that consumes this API
- R2 produces the resolved items that the discord-bot's queue holds (discord-bot R3)
- R3 produces the playable URLs that the discord-bot's audio playback consumes (discord-bot R5)
- R1 is consumed by the discord-bot's typed backend client (discord-bot R7)
- R6 is triggered exclusively by the discord-bot's `/download` command (discord-bot R4)
