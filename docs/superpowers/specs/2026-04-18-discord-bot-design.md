# Discord Bot Design

Date: 2026-04-18
Status: Approved for planning

## Goal

Build a private Discord music bot for a single trusted user in a private server, using `music-dl` as the backend and source of truth.

The bot is not a second music platform. It is a Discord-facing transport layer for media resolution and playback that `music-dl` already knows how to manage.

## Product Shape

`v1` is a local-first, single-tenant Discord bot that:

- joins a voice channel on demand
- plays audio into Discord voice
- uses `music-dl` to resolve tracks and playlists
- does not download implicitly from `/play`
- supports explicit `/download`
- supports local and Tidal-backed playback through `music-dl`

`v1` is not:

- a public multi-user bot
- a general-purpose self-hosted Discord SaaS
- a direct Tidal client inside the bot
- an AI DJ

`muse` is reference material only for Discord UX and voice lifecycle patterns. It is not the scaffold or runtime base for this feature.

## Constraints

- Keep the implementation simple and releaseable.
- Use `music-dl` as the brains of the operation.
- Keep the Discord bot thin.
- Treat local-only deployment as a convenience, not as a security model.
- Slash commands only.
- The bot is authorized only for one guild, one text channel, and one trusted Discord user.

## High-Level Architecture

The system runs as two local processes:

1. `music-dl`
2. `apps/discord-bot`

### `music-dl` responsibilities

- resolve `/play` inputs
- determine local versus remote track availability
- resolve local playlists
- resolve Tidal tracks and playlists
- manage Tidal authentication and session state
- expose bot-facing playback and download APIs
- generate playable stream handles or URLs
- own `/download` execution and progress

### Discord bot responsibilities

- register and handle slash commands
- render visible picker interactions in the private text channel
- manage Discord voice connection lifecycle
- manage runtime queue state
- request playable media from `music-dl`
- stream audio into Discord voice

### Ownership boundary

The bot:

- does not talk to Tidal directly
- does not scan the music library directly
- does not receive Tidal credentials
- does not decide how a source is resolved

All media intelligence stays in `music-dl`.

## Deployment Model

`v1` is local-first:

- the bot runs on the same machine as `music-dl`
- bot-facing APIs bind to `127.0.0.1` only
- the feature may later be released for wider self-hosted use, but `v1` is optimized for local development and validation

## Supported Inputs

`/play` accepts:

- free-text search
- direct Tidal track URL
- direct Tidal playlist URL
- local playlist name

Free-text search returns a short visible choice list of 5 items in the private text channel.

## Command Surface

Mandatory `v1` slash commands:

- `/summon`
- `/leave`
- `/play`
- `/pause`
- `/resume`
- `/skip`
- `/queue`
- `/nowplaying`
- `/volume`
- `/repeat`
- `/download`

Command rules:

- `/play` is read-only and never triggers downloads implicitly
- `/download` is the only command that mutates library contents
- `/summon` joins the caller's current voice channel
- `/volume` adjusts the playback level used by the Discord bot

## Playback Behavior

The bot maintains one private runtime queue.

Queue state includes:

- current voice channel
- pending queue entries
- current item index or pointer
- playback state
- volume
- repeat mode

Repeat modes:

- `off`
- `one`
- `all`

Default repeat mode:

- `all`

Stop behavior:

- playback stops when the queue is exhausted and repeat behavior no longer keeps playback alive

Playback flow:

1. User runs `/play`.
2. Bot sends the raw input to `music-dl`.
3. `music-dl` resolves the input.
4. Bot presents a 5-item picker for free-text searches, or directly queues resolved items for direct track or playlist inputs.
5. When playback should start, the bot asks `music-dl` for a playable source for the current queue item.
6. Bot streams that source into Discord voice.
7. On end-of-track, the bot advances according to repeat mode.

## Source Resolution Rules

Resolution behavior must support both local and non-local material without turning the bot into a downloader.

### Local material

If `music-dl` knows a track is available locally, it may still expose playback through a bot-facing stream endpoint. The bot should not touch the library path directly in `v1`.

### Remote Tidal-backed material

If a track is not local, `music-dl` may still resolve it into a playable source by using its existing Tidal session and playback knowledge.

This allows:

- playback of Tidal-only tracks
- playback of Tidal playlists whose items are not fully present locally
- fallback behavior when the local music volume is unavailable

This does not allow:

- implicit downloading during `/play`

## Bot-Facing API

The bot should not reuse GUI endpoints directly. `music-dl` should expose a small API designed specifically for Discord-bot use.

### `POST /api/bot/play/resolve`

Purpose:

- resolve a `/play` input into either a choice list or queueable items

Accepted inputs:

- free text
- Tidal track URL
- Tidal playlist URL
- local playlist name

Expected outputs:

- up to 5 candidate matches for free-text search
- one resolved item for direct track input
- an ordered list of resolved queue items for playlist input

### `POST /api/bot/playable`

Purpose:

- turn a resolved queue item into a bot-consumable playable source

Expected output:

- short-lived stream URL or handle
- content type if known
- duration if known
- display metadata for `now playing`

### `POST /api/bot/download`

Purpose:

- submit an explicit download request through the same backend that powers the GUI and CLI

Expected output:

- accepted job state and identifier

### `GET /api/bot/downloads/:id`

Purpose:

- allow the bot to poll job status for visible command responses

Expected output:

- current download state
- progress if available
- completion or failure details

## Data Shapes

Resolved queue item fields should stay minimal:

- stable item identifier
- title
- artist
- source type
- local availability flag
- duration
- artwork URL if available
- canonical backend reference used later for playback

Playable source fields should stay minimal:

- short-lived playable URL or tokenized handle
- content type if known
- expiration timestamp if relevant
- display metadata

## Security Model

Local-only deployment reduces exposure but does not remove the need for access control.

### Transport and access

- bot API binds to `127.0.0.1` only in `v1`
- bot requests use a dedicated bearer token
- bot API does not reuse the GUI CSRF model
- tokens are loaded from environment variables

### Discord authorization

The bot rejects commands unless all checks pass:

- guild id matches the allowed guild
- text channel id matches the allowed channel
- user id matches the trusted user

### Media and secrets

- the bot never receives raw Tidal credentials
- logs must not print tokens, session material, or full signed stream URLs
- playable stream URLs or handles should be short-lived
- stream access should be single-use or bounded where practical

### Input validation

- `/download` uses the same resolver path as `/play`
- the bot never accepts arbitrary filesystem paths from Discord
- the backend remains responsible for validating source inputs and playable handles

## Reliability and Failure Handling

Expected `v1` behavior:

- if resolution fails, the bot reports the failure in channel and does nothing else
- if a track fails during playback, the bot logs the item failure and advances
- if voice disconnects, the bot retries reconnect with bounded attempts
- if `music-dl` is unavailable, commands fail fast with a clear backend-unavailable message
- `/download` remains owned by `music-dl`; the bot observes status only

Recovery expectation:

- runtime reconnect behavior is mandatory
- full queue persistence across bot restarts is optional for `v1`

## Testing Scope

### Backend tests

- resolver endpoint for all supported input forms
- playable-source endpoint for local and remote-backed items
- authorization validation for bot-facing APIs
- download trigger and polling behavior

### Bot tests

- command allowlist enforcement
- queue state transitions
- repeat-mode behavior
- picker flow for free-text search
- error handling for backend and voice failures

### Local integration path

- summon bot into voice
- play local track
- play remote Tidal-backed track without downloading
- play Tidal playlist
- skip, pause, resume, volume, repeat
- explicit `/download`
- backend unavailable response
- Discord voice reconnect behavior

## Out of Scope

Out of scope for `v1`:

- AI DJ behavior
- voice commentary or spoken intros
- public multi-guild support
- social moderation features
- public webhooks
- direct disk reads by the bot
- public deployment hardening beyond the local-first model

## Why This Design

This design keeps complexity in the right place.

- `music-dl` already owns media resolution and Tidal knowledge
- the bot remains a transport and control layer
- the API surface is small and task-specific
- `muse` can inform interaction and playback patterns without dragging in its runtime, persistence, and source assumptions

This is the simplest design that still supports:

- local playback
- remote Tidal-backed playback
- explicit downloads
- private Discord control
- later open-source packaging of the Discord feature
