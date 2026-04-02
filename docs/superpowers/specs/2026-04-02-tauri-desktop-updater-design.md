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
The existing web UI renders the prompt, progress, and manual trigger.

---

## 2. User-Approved Decisions

### Release Source

- Use **GitHub Releases** as the desktop update source
- Do not build a custom updater service for v1

### Check Policy

- Check automatically on **app launch**
- Also provide a **manual Check for updates** action

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

This means updater behavior should be added to the existing Rust shell without coupling update logic to the Python server lifecycle.

### Existing UI Shape

The frontend is a plain static web app served by the sidecar and already contains:
- a Settings view
- toast helpers
- confirm/overlay UI patterns
- app-level error/banner rendering patterns

The updater UI should reuse these patterns instead of introducing a second UI system.

### Versioning Problem

Current version values are inconsistent:
- `src-tauri/Cargo.toml` uses `0.1.0`
- `src-tauri/tauri.conf.json` uses `3.0.0`

The updater cannot be considered reliable until desktop versioning has one authoritative source.

---

## 4. In Scope / Out of Scope

### In Scope

- Add Tauri updater support in the Rust desktop layer
- Add launch-time update checks
- Add a manual Settings action to check for updates
- Automatically download updates after detection
- Emit updater state/progress from Rust to the web UI
- Show in-app progress and install-ready prompts
- Support install/restart after a successful download
- Document the GitHub Releases publishing requirements
- Unify desktop versioning

### Out of Scope

- Python-managed DMG download/install logic
- A custom update backend or release API
- Full CI/CD automation for releases in this design phase
- Windows/Linux packaging work beyond preserving clean boundaries
- Silent install without any user-facing prompt
- In-app changelog rendering beyond a simple version/update message

---

## 5. Recommended Architecture

### Chosen Approach

Use a **Rust-owned updater module** in `src-tauri`.

Responsibilities:
- check for updates via Tauri’s updater support
- start background download
- track updater state and progress
- install the downloaded update when the user accepts restart
- expose commands/events to the frontend

### Why This Approach

This is preferred because:
- update install is a desktop-shell concern, not a Python API concern
- Tauri already owns app lifecycle and packaging
- the existing web UI can stay focused on presentation
- the design keeps a clean path for later Windows/Linux support

### Rejected Alternatives

#### Frontend-owned updater

Not recommended for v1 because the frontend is not currently structured as a Tauri-first JS app with an updater integration layer.

#### Python-owned updater

Rejected because it would duplicate platform-specific installer behavior outside Tauri and create the wrong long-term ownership boundary.

---

## 6. Module Boundaries

### Rust Desktop Module

Add a dedicated updater module in `src-tauri/src`, for example:
- `src-tauri/src/updater.rs`

Responsibilities:
- initialize updater state
- run automatic launch check
- handle manual checks
- prevent duplicate concurrent checks/downloads
- publish updater state changes to the window
- install a staged update after user confirmation

### Rust Integration Surface

Update the Tauri app entrypoint to:
- register updater commands
- initialize updater state during app setup
- trigger the launch-time check without blocking normal app startup

### Frontend Update UI Module

Add a focused updater section in `tidal_dl/gui/static/app.js`.

Responsibilities:
- subscribe to updater events from Tauri
- render a persistent progress banner while downloading
- render an install-ready prompt with **Restart and install** / **Later** actions
- expose a manual **Check for updates** action from Settings
- surface “You’re up to date” and error toasts for manual checks

### Settings Integration

The Settings page should gain a small updater section with:
- current app version
- **Check for updates** button
- optional updater status text if a check/download is already active

---

## 7. Updater State Model

Use a small explicit state machine shared conceptually between Rust and the UI.

Suggested states:
- `idle`
- `checking`
- `up_to_date`
- `update_available`
- `downloading`
- `downloaded`
- `error`

Suggested state payload fields:
- current version
- available version
- status message
- progress percentage or transferred bytes when available
- whether install is ready
- last error message

Rules:
- only one check/download job may run at a time
- repeated manual checks during an active job should return existing state, not start duplicates
- automatic checks should stay quiet unless an update is actually found or an actionable error matters to the user
- manual checks should always result in visible user feedback

---

## 8. User Experience Design

### Automatic Check on Launch

Flow:
1. app starts normally
2. sidecar startup proceeds as it does today
3. updater runs a non-blocking background check
4. if no update exists, show nothing
5. if an update exists, begin background download automatically
6. show an in-app banner with download progress
7. when the update is fully staged, show an install-ready prompt

The launch experience must not be delayed by the update check.

### Manual Check in Settings

The Settings view gets a **Check for updates** action.

Behavior:
- if already checking or downloading, reuse the current updater state
- if no update is available, show a success toast such as **You’re up to date**
- if an update is available, reuse the same auto-download flow as launch checks
- if the check fails, show a clear error toast

### Downloading UI

Use a lightweight persistent banner rather than a blocking modal while the update downloads.

Banner content should include:
- target version
- current status text
- progress when available

### Install-Ready UI

When the update is staged, show a stronger prompt inside the app with:
- new version number
- **Restart and install** action
- **Later** action

Choosing **Later** should dismiss the prompt but preserve the staged update state so the user can install on a later prompt/opportunity.

---

## 9. Error Handling

### Network / GitHub Unavailable

- automatic checks: fail quietly unless a visible status is already open
- manual checks: show an explicit error toast/banner

### Invalid Release Metadata or Signature Failure

- do not install anything
- surface a user-visible update error
- keep the app usable

### Duplicate Trigger Protection

If a user clicks manual check during an active check or download:
- do not spawn parallel updater work
- return current state and keep one in-flight job

### Sidecar Independence

Updater failure must not block the Python sidecar from starting or the app UI from loading.

---

## 10. Release and Publishing Design

### Source of Truth

GitHub Releases becomes the canonical source for desktop update discovery.

### Release Requirements

Desktop releases must include:
- versioned Tauri updater artifacts
- updater signatures/metadata required by Tauri
- release publication to GitHub Releases

### Signing

Updater signing keys must be generated and stored securely for release builds.

### Versioning Rule

Unify desktop versioning before enabling updater checks.
A single version must be used consistently by the packaged app and release artifacts.

Recommended rule:
- use the Tauri app version as the desktop release version
- keep Cargo and Tauri config aligned for every release

---

## 11. File-Level Change Plan

Expected code areas:

### Rust / Tauri
- Modify: `TIDALDL-PY/src-tauri/Cargo.toml`
- Modify: `TIDALDL-PY/src-tauri/tauri.conf.json`
- Modify: `TIDALDL-PY/src-tauri/src/lib.rs`
- Create: `TIDALDL-PY/src-tauri/src/updater.rs`

### Frontend
- Modify: `TIDALDL-PY/tidal_dl/gui/static/app.js`
- Modify: `TIDALDL-PY/tidal_dl/gui/static/index.html` if a mount point or settings slot is needed
- Modify: `TIDALDL-PY/tidal_dl/gui/static/style.css`

### Documentation / Release Process
- Modify: `TIDALDL-PY/README.md` or release docs as needed
- Optionally add release-specific docs if the current README would become too noisy

---

## 12. Testing Strategy

### Rust-Level Tests / Verification

Verify:
- updater state transitions are valid
- duplicate manual checks do not spawn parallel jobs
- install action is unavailable before download completion
- launch-time check does not block normal app startup

### Frontend Verification

Verify:
- Settings shows a **Check for updates** action
- manual check shows success feedback when current version is latest
- available updates show a progress banner
- downloaded updates show a restart/install prompt
- choosing **Later** dismisses the prompt without breaking future install flow
- updater errors do not break the rest of Settings or the app shell

### Release Verification

Before calling the feature complete, verify against a real GitHub Release-backed build:
- current app version is detected correctly
- newer release is detected correctly
- background download completes
- restart/install path works on macOS packaged app

---

## 13. Acceptance Criteria

The feature is complete when all of the following are true:

- the Tauri desktop app checks GitHub Releases for updates on launch
- the Settings view includes a manual **Check for updates** action
- when an update exists, the app downloads it automatically in the background
- the user sees in-app progress/status while the update is downloading
- when the update is ready, the app shows an in-app prompt to restart and install
- the user can defer installation with **Later**
- duplicate checks/downloads are prevented
- updater failures do not block normal app usage
- desktop versioning is unified so update comparisons are reliable
- the release process documents the signing and GitHub Releases requirements

---

## 14. Recommended Implementation Phasing

### Phase 1

- unify versioning
- add Rust updater module
- add launch-time background check
- add manual Settings check
- add in-app banner/modal states
- verify against a real macOS packaged release

### Phase 2

- automate signed GitHub Releases publishing
- extend support to Windows/Linux release targets when needed

This keeps the first implementation minimal while preserving a clean path for broader desktop support later.
