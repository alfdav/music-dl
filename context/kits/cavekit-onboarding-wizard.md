---
created: 2026-04-19
last_edited: 2026-04-19
---

# Cavekit: Onboarding Wizard

## Scope

This kit owns the interactive CLI wizard a user runs (or is dropped into) to configure the Discord bot for the first time or to reconfigure it later. It collects the user's Discord credentials and identifiers, validates each value against Discord and the backend via preflight checks, generates the shared backend token automatically, and atomically writes both the bot's environment file and the shared-token file. It does not own the backend's first-run detection, the bot's runtime behavior, or any GUI invocation path — those live in cavekit-onboarding-backend.md, cavekit-discord-bot.md, and future kits respectively.

## Requirements

### R1: Entry points
**Description:** The wizard is invokable in two ways.
**Acceptance Criteria:**
- [ ] Invokable directly by the user as a standalone command in the bot project
- [ ] Invokable by the onboarding-backend kit's R4 wizard dispatch with no additional arguments
- [ ] Wizard prints a one-line header on start that identifies itself and the application
**Dependencies:** none

### R2: Returning-user path
**Description:** Before touching any file, the wizard detects existing configuration and offers to preserve it. Existing configuration is considered "valid" when the bot environment file exists and contains all seven values referenced by cavekit-discord-bot.md R1, AND the shared-token file exists and is non-empty.
**Acceptance Criteria:**
- [ ] Valid existing configuration (as defined above) → prompt "Keep / Reconfigure / Cancel"
- [ ] "Keep" → wizard exits 0 without changing any files
- [ ] "Reconfigure" → proceed to the prompt sequence (R3) with existing values prefilled as defaults
- [ ] "Cancel" → wizard exits non-zero, no files changed
- [ ] The returning-user path is taken whenever valid configuration exists, regardless of how the wizard was invoked (including invocation via the onboarding-backend force flag). The force flag forces the prompt; it never forces overwrite.
**Dependencies:** R1

### R3: Prompt sequence for user-supplied values
**Description:** The wizard collects five user-supplied values in this order: Discord bot token, Discord application identifier, allowed guild identifier, allowed text channel identifier, allowed user identifier.
**Acceptance Criteria:**
- [ ] Each prompt prints a one-line breadcrumb above the input showing exactly where to find that value (URL + concise steps)
- [ ] The Discord bot token input is masked (characters are not echoed back)
- [ ] All other identifier inputs are echoed normally
- [ ] In "Reconfigure" mode each prompt shows the existing value as a default the user can accept by pressing Enter
- [ ] Empty input on a required field when no default exists → re-prompt with a message explaining the field is required
**Dependencies:** R1, R2

### R4: Shared-token generation and storage
**Description:** The wizard generates the backend-facing shared token automatically. The user never types or sees this token.
**Acceptance Criteria:**
- [ ] The token is generated with a cryptographically strong random source (effective entropy of at least 256 bits)
- [ ] The token is written to a canonical shared-token file at mode 0600
- [ ] Parent directories for the shared-token file are created if they do not exist
- [ ] The write is atomic — a crash mid-write does not leave a truncated file
- [ ] In "Reconfigure" mode, the existing token is reused rather than regenerated unless the user explicitly requests rotation
**Dependencies:** R3

### R5: Bot environment file generation
**Description:** The wizard persists the user-supplied values (plus the backend base URL) to the bot's environment file.
**Acceptance Criteria:**
- [ ] The file contains all seven values the bot requires at startup (see cavekit-discord-bot.md R1)
- [ ] The backend base URL defaults to a local-loopback address on a well-known port and the user may override it
- [ ] The file is written at mode 0600
- [ ] The write is atomic
- [ ] A pre-existing environment file is preserved untouched when the user chose "Keep" in R2
- [ ] A pre-existing environment file is overwritten only when both (a) the user explicitly chose "Reconfigure" AND (b) preflight (R6) passed
- [ ] If preflight fails during reconfigure the original file remains untouched
**Dependencies:** R3, R4, R6

### R6: Preflight checks
**Description:** Before writing any configuration the wizard validates every value against reality. Every failure reports which check failed, what went wrong, and a one-line remediation hint.
**Acceptance Criteria:**
- [ ] Environment checks: runtime version meets the bot's minimum, the cipher required for voice negotiation is available, an external media tool required for audio decoding is present, the Opus binding used for voice encoding is loadable
- [ ] Discord token validity: the token resolves to a valid bot identity
- [ ] Application identifier matches the bot token
- [ ] Allowed guild is reachable: the bot is a member of that guild (catches "bot not invited" and "wrong guild id")
- [ ] Allowed text channel exists, is a text channel, is in the allowed guild, and the bot can view+send messages in it
- [ ] Allowed user identifier belongs to a member of the allowed guild
- [ ] The bot's role has both Connect and Speak in the guild's voice permissions
- [ ] Each failure reports: which check failed, the underlying error summary, and a single remediation hint

**2026-04-20 revision:** The previous "backend reachable" and "backend accepted the shared token" criteria were moved out of this kit. Rationale: those checks required the backend to be running concurrently with the wizard — two-terminal UX, exactly the "seamless" failure we already revised away for the Y/n/never prompt. The plumbing is now closed directly: the backend's ``validate_bot_bearer`` reads the wizard-written shared-token file (``MUSIC_DL_BOT_TOKEN`` env var takes precedence), so no runtime HTTP probe is required. The corresponding startup canary moved to cavekit-onboarding-backend.md R4.

**Dependencies:** R3

### R7: Retry-single-field on preflight failure
**Description:** When a preflight check fails for a specific user-supplied field, the wizard offers to re-enter only that field rather than restart the full sequence.
**Acceptance Criteria:**
- [ ] Field-identifiable failure (e.g. invalid token, wrong guild id, wrong channel id, wrong user id) → the wizard offers re-entry of that specific field and then re-runs the relevant preflight checks
- [ ] Field-unidentifiable failure (e.g. backend unreachable, media tool missing) → the wizard prints remediation, then offers a retry / abort choice
- [ ] User abort → the wizard exits non-zero and no configuration is written
**Dependencies:** R6

### R8: Success path
**Description:** On preflight pass the wizard commits both files atomically and tells the user how to start the bot.
**Acceptance Criteria:**
- [ ] Either both the environment file and the shared-token file land on disk, or neither does (no partial-commit state)
- [ ] The wizard prints the exact command to start the bot
- [ ] The wizard does NOT automatically start the bot (V1 terminal scope — auto-start deferred)
- [ ] Exit code is 0 on success
**Dependencies:** R5, R6

### R9: Logging safety
**Description:** The wizard never surfaces sensitive material in its output or log streams.
**Acceptance Criteria:**
- [ ] The Discord bot token never appears in stdout, stderr, or log output produced by the wizard
- [ ] The generated shared backend token never appears in output produced by the wizard
- [ ] Error messages for failed preflight use generic phrasing when the underlying error may contain a secret (e.g. "token rejected" rather than a full HTTP response body)
**Dependencies:** R3, R4, R6

## Out of Scope

- GUI invocation path (deferred to a later version)
- Auto-launching the bot after setup
- Auto-starting or managing the backend process (the backend onboarding kit handles first-run backend flow)
- Tidal login / library scan path setup (out of scope until the wizard broadens to a full first-run experience)
- Token rotation UX beyond the "Reconfigure" flow

## Cross-References

- cavekit-onboarding-backend.md — that kit invokes this wizard and reads the shared-token file this wizard writes
- cavekit-discord-bot.md — this wizard produces the environment file that kit's R1 validates at bot startup
- cavekit-bot-api.md — the shared token written here is what that kit's R1 bearer auth validates against

## Changelog
