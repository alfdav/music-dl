---
created: 2026-04-19
last_edited: 2026-04-19
---

# Cavekit: Onboarding Backend

## Scope

This kit owns the backend's first-run detection and bot-wizard dispatch behavior at startup: determining whether Discord bot integration is configured, dismissed, or needs setup; prompting the user on an interactive terminal before the HTTP server begins accepting requests; and invoking the bot-side wizard as a child process. It does not own the wizard itself — its prompt copy, preflight checks, masked input, token generation, or environment file format all live in cavekit-onboarding-wizard.md. This kit's only contract with the wizard is existence-and-non-emptiness of the canonical shared-token file and the child-process invocation interface.

## Requirements

### R1: Configuration status detection
**Description:** At startup the backend determines one of three states for the Discord bot integration: configured, dismissed, or needs-setup.
**Acceptance Criteria:**
- [ ] State is "configured" when the shared bot-token file exists and is non-empty
- [ ] State is "dismissed" when a user-set dismissal flag file exists at a canonical location
- [ ] State is "needs-setup" when neither of the above holds
**Dependencies:** shared-token file contract with cavekit-onboarding-wizard.md

### R2: TTY-aware first-run prompt
**Description:** When state is "needs-setup" AND the backend's standard output is attached to an interactive terminal, the backend prompts the user before the HTTP server accepts requests.
**Acceptance Criteria:**
- [ ] With an interactive terminal + state "needs-setup" → prompt is shown
- [ ] Without an interactive terminal (daemon, piped, nohup, GUI-launched) → no prompt, server starts normally
- [ ] State "configured" or "dismissed" → no prompt, server starts normally
- [ ] Prompt is shown before the server begins accepting requests
**Dependencies:** R1

### R3: Response handling
**Description:** The prompt accepts three answers: yes (default), no, or never. Each drives a specific behavior.
**Acceptance Criteria:**
- [ ] "Y" / empty / "yes" answer → wizard is dispatched (R4)
- [ ] "n" / "no" answer → backend proceeds to server startup with no persistent state changes
- [ ] "never" answer → dismissal flag is written, backend proceeds to server startup, wizard is NOT run
- [ ] Unrecognized input → re-prompt up to 3 times, then treat as "n"
**Dependencies:** R2

### R4: Wizard dispatch
**Description:** Backend invokes the bot-side wizard as a child process, waits for it, and never aborts its own startup on wizard failure.
**Acceptance Criteria:**
- [ ] The wizard runs as a child process that inherits the backend's stdio so the user can interact with it directly
- [ ] Backend blocks until the wizard exits
- [ ] Wizard exit 0 → backend prints a brief success message, proceeds to server startup
- [ ] Wizard exit non-zero → backend prints the failure and the command to retry later, proceeds to server startup
- [ ] Backend server startup is never aborted by wizard failure
**Dependencies:** R3, cavekit-onboarding-wizard.md R1

### R5: Force re-run via CLI flag
**Description:** The backend CLI accepts a force flag that triggers the wizard prompt regardless of the detected state.
**Acceptance Criteria:**
- [ ] A force flag (exact name an implementation detail) triggers the prompt regardless of current state
- [ ] When forced, the dismissal flag is ignored for that invocation
- [ ] The force flag does NOT modify the dismissal flag — a previously-dismissed user is not permanently re-enrolled just because they ran the force flag once
- [ ] The force flag triggers the prompt even when configuration already exists — the wizard itself (cavekit-onboarding-wizard.md R2) decides whether to overwrite
**Dependencies:** R2, R3

## Out of Scope

- The wizard's prompt copy, breadcrumbs, masked input, and preflight checks
- Token generation and the shared-token file format
- GUI invocation (deferred)

## Cross-References

- cavekit-onboarding-wizard.md — this kit dispatches that wizard and reads the shared-token file the wizard writes
- cavekit-bot-api.md — the backend auth this configuration feeds into (R1 of that kit)
- Canonical shared-token path is defined by cavekit-onboarding-wizard.md R4; this kit only checks existence+non-empty

## Changelog
