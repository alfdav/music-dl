---
created: 2026-04-19
last_edited: 2026-04-20
---

# Cavekit: Onboarding Backend

## Scope

This kit owns the backend's awareness of the Discord bot integration state and the CLI surface for launching the bot-side wizard. It deliberately does NOT hijack the `music-dl gui` startup path with an interactive prompt — normal users running `music-dl gui` get the web UI they asked for. Discord-bot setup is an opt-in action triggered by an explicit CLI flag. It does not own the wizard itself — its prompt copy, preflight checks, masked input, token generation, and environment file format all live in cavekit-onboarding-wizard.md. This kit's only contract with the wizard is existence-and-non-emptiness of the canonical shared-token file and the child-process invocation interface.

## Requirements

### R1: Configuration status detection
**Description:** At startup the backend determines whether the Discord bot integration is configured or not.
**Acceptance Criteria:**
- [ ] State is "configured" when the shared bot-token file exists and is non-empty
- [ ] State is "needs-setup" when the shared bot-token file is absent or empty
**Dependencies:** shared-token file contract with cavekit-onboarding-wizard.md

### R2: Non-blocking startup hint
**Description:** When state is "needs-setup" the backend prints a one-line hint pointing users at the setup command. The hint never blocks startup, never asks a question, and never pauses for user input.
**Acceptance Criteria:**
- [ ] State "needs-setup" → a single hint line is printed to stdout before the HTTP server starts listening
- [ ] State "configured" → no hint, no output
- [ ] The hint mentions the exact command the user can run to launch the wizard (e.g. "run `music-dl gui --setup-bot` to set it up")
- [ ] The hint never waits for user input — server startup proceeds immediately regardless of terminal, state, or environment
- [ ] The hint is suppressed on non-TTY startups (daemon, piped, nohup, systemd) so logs are not cluttered with interactive copy
**Dependencies:** R1

### R3: Force-run via CLI flag
**Description:** The backend CLI accepts a force flag that launches the bot-side wizard as a child process. The flag is the only path that ever triggers the wizard from the backend — there is no implicit prompt on normal startup.
**Acceptance Criteria:**
- [ ] A force flag (exact name an implementation detail, suggestion: `--setup-bot`) launches the wizard as a child process that inherits the backend's stdio so the user can interact with it directly
- [ ] The backend blocks until the wizard exits
- [ ] Wizard exit 0 → backend prints a brief success message, proceeds to server startup
- [ ] Wizard exit non-zero → backend prints the failure and the retry command, proceeds to server startup
- [ ] The force flag triggers the wizard regardless of current state (including "configured") — the wizard itself (cavekit-onboarding-wizard.md R2) decides whether to overwrite
- [ ] Backend server startup is never aborted by wizard failure
- [ ] When bun is unavailable the backend falls back to a runnable Node interpreter (e.g. `node --import tsx`) so the force flag works in deployments that only have Node
**Dependencies:** R1, cavekit-onboarding-wizard.md R1

### R4: Shared-token pickup and startup canary
**Description:** The backend reads the shared bot secret the wizard writes, and logs at startup where that secret was resolved from. Replaces the wizard's prior R6 "backend reachable" probe — since the backend reads the wizard's file directly, no round-trip HTTP check is required to verify the plumbing is connected.
**Acceptance Criteria:**
- [ ] Bot bearer-token validation resolves the expected secret from the ``MUSIC_DL_BOT_TOKEN`` environment variable if set and non-empty, otherwise from the canonical shared-token file written by the wizard
- [ ] Environment variable takes precedence so container/CI deployments can inject the secret without relying on disk
- [ ] When neither source yields a non-empty value the auth path fails closed (returns 401 for every bot request)
- [ ] Startup prints one line naming the resolution source (env var / file path) without disclosing the secret itself
- [ ] When both sources are empty, startup emits no misleading "loaded" line (the R2 hint already covers the needs-setup case)
**Dependencies:** R1, cavekit-onboarding-wizard.md R4

## Out of Scope

- Any interactive prompt on normal `music-dl gui` startup (was R2/R3 in prior kit revision; deleted after normie-UX feedback)
- Dismissal flag and "never" answer handling (dead weight without an interactive prompt)
- The wizard's prompt copy, breadcrumbs, masked input, and preflight checks
- Token generation and the shared-token file format
- GUI invocation path (deferred to a later version; will replace the startup hint with a dismissable GUI card)

## Cross-References

- cavekit-onboarding-wizard.md — this kit dispatches that wizard and reads the shared-token file the wizard writes
- cavekit-bot-api.md — the backend auth this configuration feeds into (R1 of that kit)
- Canonical shared-token path is defined by cavekit-onboarding-wizard.md R4; this kit only checks existence+non-empty

## Changelog

- 2026-04-20: Removed prior R2 (interactive TTY prompt), R3 (Y/n/never handling), and R4 (wizard dispatch as a result of interactive prompt). These hijacked `music-dl gui` with a terminal questionnaire and alienated normal users. Replaced with R2 (one-line non-blocking hint) and R3 (explicit force flag is the only wizard-launch path). Dismissal state removed from R1 (no prompt → no dismissal semantics needed).
- 2026-04-20 (later): Added R4 (shared-token pickup + startup canary) in response to a real architectural gap surfaced during first live wizard test — the wizard wrote a token to disk but the backend read ``MUSIC_DL_BOT_TOKEN`` only from env, so every authenticated bot request returned 401 after a "successful" wizard run. Moved the wizard's prior R6 "backend reachable" AC here; the backend now reads the file directly and a runtime HTTP probe is no longer needed. This unblocks the single-terminal, one-command setup flow.
