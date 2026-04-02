# Tauri Desktop Auto-Updater — Design Specification

**Date:** 2026-04-02
**Status:** Draft
**Scope:** Add GitHub Releases-backed desktop update detection, background download, and in-app update prompts for the Tauri app, with macOS-first delivery and cross-platform-friendly boundaries

---

## 1. Overview

Add a **desktop updater module** to the Tauri wrapper so packaged desktop builds can:
- check for updates on launch
- let the user manually check for updates from Settings
- automatically download an available update in the background
- prompt the user inside the app when the update is ready to install

This feature is explicitly **desktop-shell behavior**, not Python sidecar behavior.
The Rust/Tauri layer owns update checks, downloads, install/restart, and update state.
The existing web UI renders prompt, progress, and manual trigger.

This feature applies only to **installed packaged desktop builds**.
It is out of scope for `tauri dev`, local browser use against the sidecar, and apps launched directly from a mounted DMG.

---

## 2. User-Approved Decisions

### Release Source

- Use **GitHub Releases** as the desktop update source
- Do not build a custom updater service for v1

### Check Policy

- Check automatically on **app launch**
- Also provide a **manual Check for updates** action
- v1 intentionally performs the launch check on every app start; no launch-cooldown cache is part of this design
- automatic launch checks run at most once per process start and do not retry repeatedly inside the same session after a timeout/failure

### Download Policy

- If an update is found, **download it automatically in the background**
- Do not ask for download confirmation first

### Prompt Surface

- Show update prompts **inside the existing app UI**
- Do **not** use native macOS dialogs for the main update flow

### Platform Scope

- Implement **macOS now**
- Keep module boundaries compatible with Windows/Linux support later
- Do not require full multi-platform release support in v1

---

## 3. Current Project Constraints

### Existing Desktop Shape

The Tauri app is a thin desktop shell that:
- launches a Python/FastAPI sidecar binary
- waits for the local server to become ready
- then navigates the webview to `http://localhost:8765`

Updater behavior must be added to the existing Rust shell without coupling update logic to the Python server lifecycle.

### Existing UI Shape

The frontend is a plain static web app served by the sidecar and already contains:
- a Settings view
- toast helpers
- confirm/overlay UI patterns
- app-level error/banner rendering patterns

The updater UI should reuse these patterns instead of introducing a second UI system.

### Existing Tauri Security Shape

The app already uses a capability file at `src-tauri/capabilities/default.json` for the `main` window and currently grants `core:default` plus sidecar spawn permission.
Updater design must account for Tauri 2 capability/permission requirements instead of assuming plugin access is automatically available.

### Versioning Problem

Current version values are inconsistent:
- `src-tauri/Cargo.toml` uses `0.1.0`
- `src-tauri/tauri.conf.json` uses `3.0.0`

The updater cannot be considered reliable until desktop versioning has one enforced source of truth.

---

## 4. In Scope / Out of Scope

### In Scope

- Add Tauri updater support in the Rust desktop layer
- Add the concrete Tauri 2 updater plumbing required to make that work
- Add launch-time update checks
- Add a manual Settings action to check for updates
- Automatically download updates after detection
- Emit updater state/progress from Rust to the web UI
- Show in-app progress and install-ready prompts
- Support install/restart after a successful download
- Document the GitHub Releases publishing contract and signing requirements
- Unify desktop versioning with an enforced single source of truth

### Out of Scope

- Python-managed DMG download/install logic
- A custom update backend or release API
- Full CI/CD automation for releases in this design phase
- Windows/Linux packaging work beyond preserving clean boundaries
- Silent install without any user-facing prompt
- In-app changelog rendering beyond a simple version/update message
- Enabling updater behavior in dev mode or local browser-only use
- Rollback or delta-update support in v1 unless separately verified and specified

---

## 5. Recommended Architecture

### Chosen Approach

Use a **Rust-owned updater module** in `src-tauri`.

Responsibilities:
- integrate Tauri’s updater support in the Rust app
- check for updates
- start background download
- track updater state and progress
- install the downloaded update when the user accepts restart
- expose a narrow app-owned command/event surface to the frontend

### Why This Approach

This is preferred because:
- update install is a desktop-shell concern, not a Python API concern
- Tauri already owns app lifecycle and packaging
- the existing web UI can stay focused on presentation
- the design keeps a clean path for later Windows/Linux support
- keeping updater plugin usage in Rust minimizes the permissions exposed to the sidecar-served frontend

### Rejected Alternatives

#### Frontend-owned updater

Not recommended for v1 because the frontend is not currently structured as a Tauri-first JS app with an updater integration layer, and direct plugin exposure would widen the frontend capability surface.

#### Python-owned updater

Rejected because it would duplicate platform-specific installer behavior outside Tauri and create the wrong long-term ownership boundary.

---

## 6. Tauri 2 Integration Requirements

This design is not complete unless the implementation includes the actual Tauri 2 updater plumbing.

### Required Rust/Config Work

Implementation must include all of the following:
- pin the updater plugin to the same Tauri 2 generation as the app runtime already in this repo
- scaffold the updater plugin wiring with `bun x tauri add updater` and treat the generated dependency/config/capability shape as the authoritative integration contract for this codebase
- note that the current plugin scaffolder adds Rust/plugin dependencies, plugin registration, and a capability file granting `updater:default`; v1 must not ship that frontend permission unchanged because updater access stays Rust-owned
- run one real packaged test build with updater artifacts enabled before implementation work starts, then copy the exact generated updater config shape and emitted artifact filenames into project docs as a frozen contract for this repo/version line
- run one end-to-end dry-run against a throwaway release repo/channel before implementation work starts, proving how the pinned updater source discovers releases, interprets stable/prerelease behavior, and consumes the emitted metadata/assets
- add the `tauri-plugin-updater` dependency to `src-tauri/Cargo.toml`
- register the updater plugin in `src-tauri/src/lib.rs`
- enable updater artifact generation in `src-tauri/tauri.conf.json` via `bundle.createUpdaterArtifacts`
- keep the updater source configuration in one explicit place, using the exact config object required by the pinned plugin version rather than hand-rolled field names copied from other Tauri versions
- review and update `src-tauri/capabilities/default.json` so the `main` window has the minimum permissions needed for the chosen command/plugin surface

### Capability Strategy

Preferred design:
- keep updater plugin operations inside Rust
- expose only a minimal app-owned command/event surface to the frontend
- avoid granting broader updater/plugin permissions directly to the sidecar-served frontend unless implementation proves that direct plugin access is necessary
- treat the localhost-served frontend as a real privilege boundary, not implicitly trusted content
- review all existing invoke/event commands reachable from the localhost-served frontend before adding updater commands, so updater hardening is not undermined by a weaker pre-existing command surface

The v1 frontend command surface should be limited to:
- `get_updater_state()`
- `check_for_updates()`
- `install_staged_update()`

Constraints:
- do not grant `updater:default` to the sidecar-served frontend in the shipped app
- do not use the JavaScript updater guest bindings in the shipped frontend path
- no updater command accepts arbitrary URL, repo, asset, version, or filesystem path parameters from the frontend
- `install_staged_update()` is allowed only when Rust state is `ready_to_install`, install context is supported, and the invoking window is the trusted main window
- updater commands are rejected unless the invoking window label is `main` and the app has already marked that window as navigated to the hardcoded sidecar URL `http://localhost:8765`
- no remote capability URLs are configured for updater-related permissions
- updater events are outbound status snapshots only, not command channels

### Localhost Frontend Release Gate

Updater commands must not ship until all of the following are true:
- the existing invoke/event surface reachable from the localhost-served frontend has been inventoried
- every reachable command is classified as safe, restricted, or removed
- updater commands enforce both window-label checks and Rust-state preconditions before doing privileged work
- `check_for_updates()` performs no filesystem, endpoint, or version selection based on frontend input
- `install_staged_update()` only acts on Rust-owned updater state created by the current app session
- the user-facing web UI that can reach updater commands has passed a focused XSS/command-surface review

If this gate is not passed, updater support is not shippable even if the rest of the implementation works.

If direct frontend plugin access is used anyway, the capability file must be expanded deliberately and documented as a security tradeoff.

### Build Gating

Updater wiring must be disabled or no-op in dev/local browser contexts.
The app should only perform update checks when running as a packaged desktop build in a supported install context.
Unsigned or ad-hoc local desktop builds are not part of the supported updater path for v1.

---

## 7. Release Source and Publishing Contract

“Use GitHub Releases” is not specific enough. v1 needs an explicit release contract.

### Release Source Contract

For v1:
- use **public GitHub Releases** only
- create and use one dedicated public **stable desktop release repository** for updater traffic
- do not support private-release authentication in v1
- do not support custom mirrors in v1
- do not use the GitHub Releases API directly as the updater contract
- use a **static JSON manifest** published as a GitHub Release asset as the updater contract

The pinned v1 endpoint shape is:
- `plugins.updater.endpoints = ["https://github.com/alfdav/music-dl-desktop-releases/releases/latest/download/latest.json"]`

This follows the Tauri updater static-JSON endpoint model instead of an app-defined GitHub parsing layer.
The dedicated stable-release repository is a precondition for implementation.

### Release Selection Policy

- only stable releases are eligible for auto-update
- draft and pre-release GitHub entries are outside the auto-update channel for v1
- do not rely on ad-hoc client-side filtering logic in the app
- stable-channel correctness is enforced by repository isolation: the dedicated stable desktop release repository publishes stable releases only
- prerelease/canary work, if added later, must use a different repo/channel and must not reuse the stable `latest.json` endpoint
- do not allow downgrade installs through the updater flow
- recommended tag format: `v<version>` where `<version>` exactly matches the desktop app version

### Required Release Assets

Every desktop release must include:
- the packaged app artifact for the platform
- updater artifacts/signatures generated by Tauri for that version
- the exact updater metadata files required by the pinned updater source
- complete asset coverage for every platform currently exposed on the stable update channel

Publishing a DMG alone is not sufficient.

For macOS specifically:
- the DMG remains the human-download/install artifact for first install
- the updater downloads the Tauri-generated `.app.tar.gz` updater bundle plus its `.sig`, not the DMG
- `latest.json` must point at the `.app.tar.gz` URL and inline the matching signature contents for the target platform
- v1 currently supports `darwin-aarch64` only; if x86_64 or universal macOS artifacts are added later, the manifest contract and release checklist must be expanded before those assets are published on the stable channel

The release procedure must capture one real example release in docs with asset filenames copied verbatim from build output for the pinned Tauri/updater version. The project should treat those emitted filenames as the contract instead of inventing its own naming scheme.

A release must not be published to the stable update channel until the checklist confirms that signatures, metadata, and platform-specific assets are all present and internally consistent.
Stable release assets and `latest.json` must be treated as immutable once published.
Only designated release maintainers may publish stable releases, and stable releases must not be edited in place; fixes require publishing a newer stable release.

### Updater Source Wiring

The implementation must define one explicit place where release source configuration lives.
For v1, use static Tauri config with the updater plugin’s documented fields:
- `bundle.createUpdaterArtifacts: true`
- `plugins.updater.pubkey: <public key contents>`
- `plugins.updater.endpoints: ["https://github.com/<owner>/<stable-release-repo>/releases/latest/download/latest.json"]`

Do not scatter repo/URL parsing across frontend code or ad-hoc runtime string building.

For v1, the updater repository/endpoint is immutable application configuration. Changing it is a release-channel migration and must be treated as explicit follow-up work, not an incidental per-release edit.

### Static Manifest Contract

The stable endpoint must return the Tauri updater static JSON shape, not a custom response.
For the macOS target currently in scope, `latest.json` must contain:
- `version`
- `notes` (optional)
- `pub_date` (optional RFC 3339)
- `platforms.darwin-aarch64.url`
- `platforms.darwin-aarch64.signature`

The manifest must include only valid and complete platform entries for the stable channel because Tauri validates the whole file before version comparison.
The exact asset filenames and final published `latest.json` field names must be copied from the dry-run release and frozen in release docs before implementation starts.

---

## 8. Versioning Rule

The updater requires one enforced version source of truth.

### Source of Truth

Use a committed root file `TIDALDL-PY/VERSION` as the authoritative desktop release version.
Both `src-tauri/tauri.conf.json.version` and `src-tauri/Cargo.toml` must be mechanically rewritten from that file.

### Sync Rule

- add a dedicated sync script such as `TIDALDL-PY/scripts/sync-desktop-version.sh` that reads `TIDALDL-PY/VERSION` and rewrites the Cargo and Tauri version fields
- desktop build entrypoints must run that sync step before building
- release work must not rely on two manual edits staying in sync
- CI or release verification must fail immediately if the repo is dirty after the sync step or if generated versions differ from `VERSION`
- manual dual-editing of versions is forbidden

### Release Rule

The `VERSION` file, GitHub Release tag, and updater release metadata must match exactly.

---

## 9. Module Boundaries

### Rust Desktop Module

Add a dedicated updater module in `src-tauri/src`, for example:
- `src-tauri/src/updater.rs`

Responsibilities:
- initialize updater state
- run automatic launch check
- handle manual checks
- prevent duplicate concurrent checks/downloads/installs
- cache the latest updater snapshot in Rust state
- publish updater state changes to the window
- install a staged update after user confirmation
- coordinate orderly shutdown of the sidecar before restart/install

### Rust Integration Surface

Update the Tauri app entrypoint to:
- register updater commands
- initialize updater state during app setup
- register the updater plugin
- create the main window and start the sidecar as normal
- start the launch-time updater check immediately after app setup/window initialization, in parallel with sidecar startup, without blocking normal app startup

### Frontend Update UI Module

Add a focused updater section in `tidal_dl/gui/static/app.js`.

Responsibilities:
- request the current updater snapshot from Rust on startup
- subscribe to updater events from Tauri after the web UI is ready
- render a persistent progress banner while downloading
- render an install-ready prompt with **Restart and install** / **Later** actions
- expose a manual **Check for updates** action from Settings
- surface “You’re up to date” and error toasts for manual checks
- treat updater state as app-global and render prompts only in the main window

### Settings Integration

The Settings page should gain a small updater section with:
- current app version reported by Rust/Tauri
- **Check for updates** button
- updater status text if a check/download is already active

---

## 10. Updater State Model

Use a small explicit state model shared conceptually between Rust and the UI.

### Core States

Suggested states:
- `idle`
- `unsupported_install_context`
- `checking`
- `up_to_date`
- `update_available`
- `downloading`
- `ready_to_install`
- `installing`
- `error`

### Required Metadata

Each snapshot should include enough metadata for UI policy:
- current version
- available version
- trigger source: `automatic` or `manual`
- status message
- progress percentage or transferred bytes when available
- whether progress is determinate or only an indeterminate download/install status is available
- whether install is ready in the current session
- last error message

### Rules

- only one check/download/install job may run at a time
- repeated manual checks during an active job should return existing state, not start duplicates
- if an update has already been downloaded in the current session, manual check should return `ready_to_install` and reopen the install prompt instead of starting a second download
- repeated install clicks must be ignored once install has started
- automatic checks should stay quiet unless an update is actually found
- manual checks should always result in visible user feedback
- Rust state is authoritative; the frontend must not infer updater truth from missed events
- `Later` is session-local only; v1 does not require persisted staged-update reuse across app relaunches
- after `Later`, the install prompt stays suppressed for the rest of the current session unless the user explicitly runs manual check, navigates to an updater-specific action in Settings, or the current-session updater state changes
- if install context is unsupported, both automatic and manual checks resolve to `unsupported_install_context`

### Required Transition Rules

- `idle -> checking` on launch or manual check in a supported install context
- `idle -> unsupported_install_context` on launch in an unsupported context
- `unsupported_install_context -> unsupported_install_context` on manual check until install context changes
- `checking -> up_to_date | update_available | error`
- `update_available -> downloading | ready_to_install | error` within the current app session
- `downloading -> ready_to_install | error`
- `ready_to_install -> installing | ready_to_install` (`Later` keeps the state ready for the current session)
- `installing -> error` only if failure occurs before control is handed to the updater runtime; after handoff, current-process recovery is not guaranteed
- `error -> checking | ready_to_install | unsupported_install_context` based on the next explicit state re-query

---

## 11. Startup Timing and State Delivery

Because the frontend is loaded only after the Python sidecar is ready, it can miss early updater events.
The design must handle that explicitly.

### Required Timing Model

- Rust owns the authoritative updater snapshot in managed app state
- Rust may emit live events, but the frontend cannot rely on receiving every early event
- when the web UI loads, it must request the current updater snapshot from Rust
- after that initial snapshot, the UI subscribes to live updater events

This avoids losing updater state if a launch-time check starts before the sidecar-served UI is available.

---

## 12. User Experience Design

### Automatic Check on Launch

Flow:
1. app starts normally
2. sidecar startup proceeds as it does today
3. updater runs a non-blocking background check in parallel
4. if no update exists, show nothing
5. if an update exists, begin background download automatically
6. when the frontend is available, show an in-app banner with download progress
7. when the update is fully staged, show an install-ready prompt

The launch experience must not be delayed by the update check, and updater UI must wait until the normal app chrome is available rather than interrupting the loading screen itself.

### Manual Check in Settings

The Settings view gets a **Check for updates** action.

Behavior:
- if install context is unsupported, the action returns the typed `unsupported_install_context` state and explanatory text instead of attempting network work
- if already checking or downloading, reuse the current updater state and surface visible feedback in Settings
- if an update is already downloaded in the current session, return the existing `ready_to_install` state and re-open the install prompt
- if no update is available, show a success toast such as **You’re up to date**
- if an update is available, reuse the same auto-download flow as launch checks
- if the check fails, show a clear error toast

### Downloading UI

Use a lightweight persistent banner rather than a blocking modal while the update downloads.

Banner content should include:
- target version
- current status text
- byte/progress updates from the real updater `Started` / `Progress` / `Finished` callbacks when available
- an indeterminate loading state when total content length is unknown

### Install-Ready UI

When the update is staged, show a stronger prompt inside the app with:
- new version number
- **Restart and install** action
- **Later** action

Choosing **Later** dismisses the current prompt but does not discard the update downloaded in the current session.
If the pinned updater/runtime later proves that staged updates survive relaunch and remain queryable, the prompt may reappear on next launch, but that is not a v1 requirement.

### Install Context Guardrails

This is a deliberate **v1 support policy**, not a claim that every other macOS bundle location is technically impossible.
The goal is to keep auto-update support narrow enough to test reliably.

v1 intentionally supports only installed macOS app bundles whose canonicalized bundle parent is one of:
- `/Applications`
- `~/Applications`

Detection rules:
- resolve the current executable path in Rust and walk up to the containing `.app` bundle root before classification
- canonicalize that bundle path before comparison
- read the bundle identifier from the app bundle metadata and require `com.alfdav.music-dl`
- detect translocation by canonical path patterns associated with AppTranslocation/temp launch paths and treat those as unsupported
- treat bundle filename renames as acceptable if the canonical bundle location and bundle identifier still match the supported install contract
- if any bundle-path or bundle-id check is ambiguous, fail closed to `unsupported_install_context`

Treat these contexts as unsupported for auto-update:
- app bundle path under `/Volumes/` (mounted DMG)
- app translocation or quarantine-derived temporary path
- ad-hoc bundle locations such as Downloads/Desktop/custom folders
- symlinked launch locations whose canonical target does not resolve into `/Applications` or `~/Applications`

### Install Context Truth Table

| Observed launch context | Expected classification | Auto-check | Manual check result | Notes |
| --- | --- | --- | --- | --- |
| Canonical bundle under `/Applications` with bundle id `com.alfdav.music-dl` | supported | run | normal updater flow | primary supported path |
| Canonical bundle under `~/Applications` with bundle id `com.alfdav.music-dl` | supported | run | normal updater flow | secondary supported path |
| Bundle launched from mounted DMG under `/Volumes/...` | unsupported_install_context | no-op | explicit unsupported message | first-install only |
| AppTranslocation/temp path | unsupported_install_context | no-op | explicit unsupported message | likely quarantine/translocation case |
| Bundle in Downloads/Desktop/custom folder | unsupported_install_context | no-op | explicit unsupported message | outside v1 support policy |
| Symlinked app whose canonical target resolves into `/Applications` or `~/Applications` and bundle id matches | supported | run | normal updater flow | canonical target decides |
| Symlinked app whose canonical target resolves elsewhere | unsupported_install_context | no-op | explicit unsupported message | fail closed |
| Bundle id mismatch or bundle root cannot be resolved confidently | unsupported_install_context | no-op | explicit unsupported message | fail closed |

If the app is running from an unsupported install context, automatic update checks should resolve to `unsupported_install_context` and the Settings action should show this exact copy:

> Auto-update only works after you move music-dl.app into Applications.

---

## 13. Sidecar Shutdown and Install Lifecycle

The app currently manages a long-lived Python sidecar child process.
Install/restart behavior must define shutdown ordering explicitly.

### Restart-and-Install Flow

Use the Rust updater API’s split download/install flow, not a combined immediate install path.

When the user chooses **Restart and install**:
1. transition updater state to `installing`
2. ignore duplicate install requests
3. stop emitting `ready_to_install` prompts
4. use the managed sidecar child handle to terminate the Python sidecar before install proceeds
5. wait for the child to exit or for a bounded shutdown timeout to expire
6. if the child spawned descendants, terminate the process tree or abort install before updater handoff
7. if the sidecar is still alive after that timeout, abort before updater handoff, return to an error state, and keep the current app session running rather than racing install against a live child process
8. only after the sidecar process tree is confirmed stopped, call the updater install step for the already-downloaded artifact
9. after successful install handoff, restart the app when required by the updater/runtime path

### Failure Rule

If failure occurs before updater handoff:
- return to a non-installing state
- keep the app usable
- leave or clear the staged payload according to the updater layer’s actual post-failure state, then re-derive UI from that state instead of guessing
- if the updater layer exposes a supported way to discard a bad staged payload, use it after repeated pre-handoff install failures or known-invalid staged state
- if staged-payload discard is not supported, suppress automatic re-prompting for the rest of the current session and show manual reinstall guidance instead of looping endlessly
- show an install error prompt/toast

If failure occurs after updater handoff, the current app process may not be able to recover the session in-place; in that phase, the updater runtime’s behavior is authoritative.

Updater failure must not leave an orphaned sidecar process behind.
The implementation plan must include a small spike to verify the exact Rust updater API sequence used for `check -> download -> later install -> restart` on the pinned plugin version.

---

## 14. Error Handling and Policy

### Network / GitHub Unavailable

- launch checks remain asynchronous and use a bounded network timeout
- v1 timeout budget: 30 seconds maximum for metadata/check requests before surfacing failure
- background artifact download uses a separate longer timeout appropriate for release-sized downloads
- automatic checks: fail quietly unless a visible updater UI is already active
- manual checks: show an explicit error toast/banner

### Invalid Release Metadata or Signature Failure

- do not install anything
- surface a user-visible update error
- keep the app usable

### Duplicate Trigger Protection

If a user clicks manual check during an active check/download/install:
- do not spawn parallel updater work
- return current state and keep one in-flight job

### Downgrade / Unsupported Release Protection

- reject downgrade installs
- release publishing must keep draft/prerelease entries outside the updater channel used by clients
- ignore malformed or incomplete release metadata

### Sidecar Independence

Updater failure must not block the Python sidecar from starting or the app UI from loading.

---

## 15. Signing and Operational Requirements

Signing is a release requirement, not a future footnote.

### Required Operational Deliverables

Before the feature can be called shippable, the project must document:
- how updater signing keys are generated
- where the public verification key is configured in the shipped app
- that the shipped app uses a compile-time-fixed public verification key rather than an environment-injected runtime key
- where the private signing key lives for release builds
- how local releases are tested without exposing production secrets
- who owns release credentials
- how keys are rotated if needed
- how Apple code-signing and notarization continuity is preserved across the downloaded update artifacts and installed app bundle on macOS

### Scope for v1

This design does not require full CI automation yet, but it does require a documented manual or semi-manual release procedure that can produce valid signed updater artifacts repeatedly.

Release/install docs must explicitly warn users to move the app into Applications before expecting auto-update to work.
Release docs must also state that the macOS updater consumes the generated `.app.tar.gz` updater bundle, while the DMG is only for first-time installation.

---

## 16. File-Level Change Plan

Expected code areas:

### Rust / Tauri
- Modify: `TIDALDL-PY/src-tauri/Cargo.toml`
- Modify: `TIDALDL-PY/src-tauri/tauri.conf.json`
- Modify: `TIDALDL-PY/src-tauri/src/lib.rs`
- Modify: `TIDALDL-PY/src-tauri/capabilities/default.json`
- Create: `TIDALDL-PY/src-tauri/src/updater.rs`

### Frontend
- Modify: `TIDALDL-PY/tidal_dl/gui/static/app.js`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/index.html` if a mount point or settings slot is needed
- Modify: `TIDALDL-PY/tidal_dl/gui/static/style.css`

### Documentation / Release Process
- Modify: `TIDALDL-PY/README.md` or release docs as needed
- Optionally add a focused desktop release/updater document if the README becomes too noisy

---

## 17. Observability Requirements

Updater behavior must be diagnosable from Rust logs.

Log at minimum:
- check start and trigger source
- current version and candidate release version
- install-context classification
- state transition name
- no-update result
- download start and completion
- install start
- install failure reason
- signature/metadata validation failures

Do not rely on frontend toasts as the only troubleshooting signal.

---

## 18. Testing Strategy

### Rust-Level Tests / Verification

Verify:
- updater state transitions are valid
- duplicate manual checks do not spawn parallel jobs
- duplicate install clicks are ignored
- install action is unavailable before download completion
- launch-time check does not block normal app startup
- sidecar shutdown occurs before restart/install path proceeds
- install is aborted if the sidecar cannot be confirmed stopped before the bounded timeout

### Frontend Verification

Verify:
- Settings shows a **Check for updates** action
- current version displayed in Settings comes only from Rust/Tauri, not from frontend constants, Node metadata, or Python
- unsupported install context returns the typed unsupported state and message
- manual check shows success feedback when current version is latest
- available updates show a progress banner
- downloaded updates show a restart/install prompt
- choosing **Later** dismisses the prompt without losing the current-session downloaded update
- updater errors do not break the rest of Settings or the app shell

### Release Verification

Before calling the feature complete, verify against a real GitHub Release-backed build:
- current app version is detected correctly
- newer stable release is detected correctly
- the updater channel only exposes the intended stable release artifacts to clients
- bad or missing signature is rejected
- malformed/incomplete release metadata is rejected
- interrupted download recovers or fails cleanly within the same session
- background download completes even when progress is indeterminate
- restart/install path works on macOS packaged app
- behavior is validated from an installed app, not just from a mounted DMG
- behavior is validated for supported install paths (`/Applications` and `~/Applications`) and rejected for unsupported paths

---

## 19. Acceptance Criteria

The feature is complete when all of the following are true:

- the Tauri desktop app includes the real Tauri 2 updater plumbing required to function
- the app checks GitHub Releases for updates on launch in packaged desktop builds
- the Settings view includes a manual **Check for updates** action
- when an update exists, the app downloads it automatically in the background
- the user sees in-app progress/status while the update is downloading
- when the update is ready, the app shows an in-app prompt to restart and install
- the user can defer installation with **Later** for the current session without losing the downloaded update in that session
- duplicate checks/downloads/installs are prevented
- updater failures do not block normal app usage
- the sidecar is shut down cleanly before restart/install proceeds
- desktop versioning is unified with an enforced single source of truth
- the localhost frontend release gate is completed and documented before ship
- the release process documents signing, frozen updater config/artifact contract, release selection policy, Apple signing/notarization continuity, and GitHub Releases requirements

---

## 20. Design Freeze Blockers

Do not start implementation until all of the following are verified and written down:

- the pinned Rust updater API flow needed for `check -> download -> later install -> restart`
- the exact generated updater asset filenames for the pinned Tauri/updater versions
- the exact `latest.json` shape actually published by the dry-run release flow
- the real progress callback behavior available on the pinned updater path
- the process-tree shutdown approach for the Python sidecar on macOS
- the reachable invoke/event command inventory for the localhost-served frontend

---

## 21. Recommended Implementation Phasing

### Phase 1

- unify versioning and add a mismatch check
- add updater plugin/config plumbing
- enable updater artifact generation
- add Rust updater module
- add launch-time background check
- add manual Settings check
- add updater snapshot + event delivery model
- add in-app banner/modal states
- verify against a real installed macOS packaged release

### Phase 2

- automate signed GitHub Releases publishing
- extend support to Windows/Linux release targets when needed

This keeps the first implementation minimal while preserving a clean path for broader desktop support later.
