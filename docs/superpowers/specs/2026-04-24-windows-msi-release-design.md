# Windows MSI Release Design

Date: 2026-04-24

## Goal

Ship a first native Windows desktop artifact for `music-dl` as an unsigned MSI built by GitHub Actions. The artifact targets Windows 10 and Windows 11. A real Windows machine is used for manual smoke testing before calling Windows support release-ready.

WSL is not the product release path. It can remain a developer workaround later, but the supported Windows experience should be a normal desktop installer.

## Decisions

- Build a native Tauri Windows MSI.
- Use GitHub Actions as the repeatable release builder.
- Use the user's Windows machine for install and smoke validation.
- Support Windows 10 and Windows 11 only for the first release.
- Keep the first MSI unsigned. SmartScreen warnings are expected until code signing is added later.
- Extend the existing desktop release workflow instead of creating a separate release process.

## Why Not Simpler?

Could this be implemented by extending an existing module?

Yes. The existing Tauri desktop app and `.github/workflows/build-desktop.yml` release workflow are the right extension points. No new app, backend, or release system is needed.

What concrete complexity does a new module introduce?

A separate release system would duplicate dependency setup, sidecar packaging, artifact upload, and release-note behavior. It would make Linux, macOS, and Windows release behavior drift.

What becomes harder to understand, debug, or maintain because a new module exists?

Release failures would need to be debugged across multiple workflows with different assumptions. Sidecar naming and Tauri bundling would be easier to break on one platform while passing on another.

What is the simplest possible alternative, and why was it rejected?

WSL or manual source installation is simpler to document, but it is not a desktop release. It would push setup complexity onto users and make file paths, browser integration, and app startup feel like a developer workflow.

## Architecture

The Windows release uses the existing app architecture:

- Tauri provides the native desktop shell.
- PyInstaller packages the Python/FastAPI backend as a sidecar executable.
- The Tauri app starts the sidecar and waits for the existing daemon health metadata.
- The browser UI is served by the local backend, same as Linux and macOS.

No backend rewrite is part of this release. Windows work should be limited to packaging, workflow, docs, and targeted compatibility fixes found by smoke testing.

## Build Flow

The existing `.github/workflows/build-desktop.yml` workflow should add Windows support through a `windows-latest` path.

Windows build steps:

1. Check out the repository.
2. Install Python 3.12 with `uv`.
3. Install Node tooling, using Bun for package/build commands where practical.
4. Install Python test/build dependencies in `tidaldl-py`.
5. Build the PyInstaller sidecar on Windows.
6. Rename the sidecar for the Rust host triple, expected to be `music-dl-server-x86_64-pc-windows-msvc.exe`.
7. Verify bundled static assets.
8. Build the Tauri MSI with `tauri build --bundles msi`.
9. Upload the MSI as a workflow artifact.
10. On tagged releases, attach the MSI to the GitHub release.

The current `tauri.conf.json` `beforeBuildCommand` is Bash-based and Unix-shaped. Windows CI should not rely on it unchanged. The implementation should prefer explicit workflow steps for sidecar building and asset verification, then disable or override the Tauri `beforeBuildCommand` for CI builds as needed.

## Release Assets

Tagged releases should include:

- Linux: `.AppImage`, `.AppImage.sig`, `.deb`, and `latest.json`.
- macOS: `.dmg` when manually attached.
- Windows: unsigned `.msi`.

The first Windows MSI does not need updater manifest support. If updater support for Windows is added later, it must be validated separately and should not block the first installable MSI.

## Documentation

Update the canonical release install instructions and README references so Windows users see:

- Windows 10/11 support.
- Download the `.msi` from GitHub Releases.
- The first MSI is unsigned.
- SmartScreen warnings are expected for early builds.
- WSL is not required.

Documentation should include a short smoke checklist for the user's Windows machine:

1. Install the MSI.
2. Launch `music-dl`.
3. Complete or recover Tidal authentication.
4. Choose a local library/download path.
5. Search for one track.
6. Download one track.
7. Play that track in the desktop app.
8. Quit and reopen the app.
9. Confirm settings, auth, and library state persist.

## Error Handling

If Windows build fails because Tauri cannot create an MSI, inspect the WiX-related failure first. MSI creation must run on Windows.

If the app launches but the UI never loads, inspect sidecar startup:

- Confirm the sidecar executable exists in the bundled resources.
- Confirm the sidecar filename includes the Windows target triple and `.exe`.
- Confirm daemon metadata is written to the expected config directory.
- Confirm `/api/server/health` returns ready status.

If the app starts but downloads fail, isolate whether the failure is Windows path handling, ffmpeg availability, or Tidal auth.

## Testing

Automated checks before publishing a Windows artifact:

- Existing Python release-smoke tests from `tidaldl-py`.
- PyInstaller sidecar build on `windows-latest`.
- Static asset verification.
- Tauri MSI build artifact exists.

Manual Windows smoke test:

- Install unsigned MSI.
- Launch app.
- Complete setup wizard.
- Authenticate with Tidal.
- Download and play one track.
- Restart app and verify persisted state.

## Non-Goals

- No WSL-first release.
- No Windows 7 or Windows 8 support.
- No code signing in the first artifact.
- No Windows Store packaging.
- No backend rewrite.
- No new installer framework outside Tauri.
- No offline WebView2 runtime bundling unless smoke testing proves it is needed.

## Open Risks

- The Bash-based Tauri `beforeBuildCommand` may need a CI override.
- Windows sidecar naming may require exact `.exe` handling.
- PyInstaller may expose Windows-only hidden import or data-file issues.
- Windows path handling may need small fixes after smoke testing.
- Unsigned installers will show SmartScreen warnings.
