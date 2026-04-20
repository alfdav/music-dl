---
created: 2026-04-19
last_edited: 2026-04-19
---

# Cavekit: Discord Bot

## Scope

The thin Discord bot process that handles slash commands, manages a runtime queue, controls voice lifecycle, and streams audio into Discord voice channels. The bot delegates all media resolution, playback source generation, and download execution to the bot API (see cavekit-bot-api.md). The bot is a single-tenant, private bot authorized for exactly one guild, one text channel, and one user.

## Requirements

### R1: Startup Configuration Validation

**Description:** The bot must validate all required configuration values at startup and refuse to start if any are missing or invalid.

**Acceptance Criteria:**
- [ ] The bot requires a Discord authentication token and fails to start without it
- [ ] The bot requires a Discord application identifier and fails to start without it
- [ ] The bot requires an allowed guild identifier and fails to start without it
- [ ] The bot requires an allowed text channel identifier and fails to start without it
- [ ] The bot requires an allowed user identifier and fails to start without it
- [ ] The bot requires a backend base URL and fails to start without it
- [ ] The bot requires a backend bearer token and fails to start without it
- [ ] Startup failure produces a clear error message naming the missing value
- [ ] Whitespace-only values are treated as missing

**Dependencies:** None

### R2: Authorization Gate

**Description:** Every incoming slash command must be checked against the allowed guild, channel, and user. Commands from unauthorized contexts are rejected.

**Acceptance Criteria:**
- [ ] A command from a guild ID that does not match the allowed guild is rejected with a private error response
- [ ] A command from a channel ID that does not match the allowed channel is rejected with a private error response
- [ ] A command from a user ID that does not match the allowed user is rejected with a private error response
- [ ] All three checks (guild, channel, user) must pass for a command to proceed
- [ ] Rejection responses are ephemeral (visible only to the invoking user)

**Dependencies:** R1

### R3: Runtime Queue

**Description:** The bot maintains a single runtime queue of resolved items with a current position index and repeat mode.

**Acceptance Criteria:**
- [ ] Items can be appended to the queue
- [ ] The queue tracks a current item index
- [ ] Advancing the queue in repeat mode `off` moves to the next item and stops when the queue is exhausted
- [ ] Advancing the queue in repeat mode `one` replays the current item indefinitely
- [ ] Advancing the queue in repeat mode `all` wraps to the first item after the last item
- [ ] The default repeat mode is `all`
- [ ] The queue can be cleared
- [ ] The queue can report its current contents and current item

**Dependencies:** None

### R4: Slash Commands

**Description:** The bot registers and handles exactly 11 slash commands. Each command has a single well-defined behavior.

**Acceptance Criteria:**
- [ ] `/summon` -- bot joins the voice channel the invoking user is currently in; responds with an error if the user is not in a voice channel
- [ ] `/leave` -- bot disconnects from the current voice channel and clears playback state
- [ ] `/play <query>` -- sends the query to the backend resolve endpoint; for free-text results, presents up to 5 choices as visible messages in the text channel; for direct track or playlist results, queues items immediately; never triggers a download
- [ ] `/pause` -- pauses the current audio playback
- [ ] `/resume` -- resumes paused audio playback
- [ ] `/skip` -- advances to the next queue item according to current repeat mode
- [ ] `/queue` -- displays the current queue contents and highlights the current item
- [ ] `/nowplaying` -- displays metadata for the currently playing item (title, artist, duration at minimum)
- [ ] `/volume <level>` -- adjusts the bot's audio playback volume
- [ ] `/repeat <mode>` -- sets the repeat mode to off, one, or all
- [ ] `/download <query>` -- resolves the query through the backend, triggers an explicit download, and reports job status by polling
- [ ] All commands enforce the authorization gate (R2) before executing
- [ ] No commands other than these 11 are registered

**Dependencies:** R2, R3, bot-api R2, bot-api R3, bot-api R6

### R5: Audio Playback

**Description:** The bot creates audio resources from playable URLs provided by the backend and streams them into the active Discord voice connection.

**Acceptance Criteria:**
- [ ] The bot requests a playable source URL from the backend for the current queue item before playback begins
- [ ] Audio plays through the active voice connection
- [ ] When a track ends, the bot automatically advances the queue according to the current repeat mode and begins playing the next item (if any)
- [ ] When the queue is exhausted (repeat mode off, last item finished), playback stops
- [ ] If a track fails during playback, the bot logs the failure and advances to the next item
- [ ] The bot never accesses media files directly from disk
- [ ] The bot never contacts remote music services directly

**Dependencies:** R3, R6, bot-api R3

### R6: Voice Lifecycle

**Description:** The bot manages its Discord voice connection with join, leave, and reconnect behaviors.

**Acceptance Criteria:**
- [ ] The bot joins the voice channel the invoking user occupies when `/summon` is issued
- [ ] The bot leaves the voice channel and stops playback when `/leave` is issued
- [ ] If the voice connection drops unexpectedly, the bot attempts to reconnect with a bounded number of retries
- [ ] If all reconnect attempts fail, the bot reports the failure in the text channel
- [ ] The bot is in at most one voice channel at a time

**Dependencies:** None

### R7: Typed Backend Client

**Description:** The bot communicates with the bot API through a typed HTTP client that handles authentication, request formatting, and response parsing.

**Acceptance Criteria:**
- [ ] All requests to the backend include the bearer token in the Authorization header
- [ ] The client exposes methods for: resolve, playable source, download trigger, and download status
- [ ] If the backend is unreachable, the client returns a clear error (not an unhandled exception)
- [ ] Response parsing failures produce clear errors (not unhandled exceptions)

**Dependencies:** R1, bot-api R1

### R8: Visible Picker for Free-Text Search

**Description:** When `/play` resolves a free-text query, the bot displays up to 5 choices as visible messages in the private text channel for the user to select from.

**Acceptance Criteria:**
- [ ] Free-text search results are displayed as a numbered or labeled list in the text channel
- [ ] The user can select one of the displayed choices
- [ ] The selected choice is queued for playback
- [ ] If only one result is returned, it is queued directly without requiring selection

**Dependencies:** R4, bot-api R2

### R9: Error Reporting

**Description:** The bot reports failures clearly in the text channel rather than failing silently.

**Acceptance Criteria:**
- [ ] If input resolution fails, the bot reports the failure in the text channel
- [ ] If the backend is unavailable, commands respond with a clear backend-unavailable message
- [ ] If voice connection fails, the bot reports the failure in the text channel
- [ ] Error messages do not expose internal details (tokens, URLs, stack traces)

**Dependencies:** None

## Out of Scope

- Queue persistence across bot restarts (runtime-only in v1)
- Multi-guild or multi-channel support
- AI DJ or mood-based selection
- Voice commentary or spoken track intros
- Direct communication with remote music services
- Direct filesystem or library path access
- Social moderation features
- Public webhook endpoints
- Embedded rich media previews beyond text metadata

## Cross-References

- See also: [cavekit-bot-api.md](cavekit-bot-api.md) -- the backend API this bot consumes
- R4 `/play` and `/download` depend on bot-api R2 (input resolution)
- R5 audio playback depends on bot-api R3 (playable source generation)
- R4 `/download` depends on bot-api R6 (download gateway)
- R7 implements the client side of bot-api R1 (bearer token auth)
- R8 presents choices produced by bot-api R2 (free-text resolution returning up to 5 candidates)
