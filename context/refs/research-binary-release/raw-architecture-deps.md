## Agent: codebase-architecture-dependencies

### RQ1: Directory Structure, Module Boundaries, Entry Points

- Finding: Monorepo — Python package under `tidaldl-py/`, Rust/Tauri shell in `src-tauri/`, installer scripts at repo root `scripts/`.
- Evidence: `tidal_dl/{cli.py, api.py, config.py, download.py, hifi_api.py, metadata.py, gui/, helper/, model/}`, 11 route modules under `gui/api/`
- Implication: New files added to `tidal_dl/gui/api/` must be manually listed in PyInstaller spec's `tidal_hidden` array.
- Confidence: HIGH

- Finding: FastAPI `create_app` in `gui/__init__.py` handles frozen vs dev mode via `sys._MEIPASS` detection for static files.
- Evidence: `gui/__init__.py:22-25`
- Implication: Correctly implemented, tested in `test_static_assets.py`.
- Confidence: HIGH

- Finding: Entry points `music-dl` and `tidal-dl` both map to `tidal_dl.cli:main`. Sidecar entry is `sidecar_entry.py` → uvicorn with `tidal_dl.gui:create_app` factory.
- Evidence: `pyproject.toml:35-37`, `sidecar_entry.py`
- Confidence: HIGH

### RQ2: Tauri + PyInstaller Build Pipeline

- Finding: Build order: (1) PyInstaller packages Python→single binary, (2) Tauri bundles as externalBin sidecar, (3) Tauri wraps in .app/.dmg.
- Evidence: `tauri.conf.json:9,31-32` — `beforeBuildCommand` runs pyinstaller, renames to target-triple suffix, then tauri build runs.
- Confidence: HIGH

- Finding: Tauri polls sidecar readiness via TCP on port 8765, every 200ms, 30s timeout. Shows loading page until ready, then navigates webview to `http://localhost:8765`.
- Evidence: `src-tauri/src/lib.rs:20-26,63-84`, `tauri.conf.json:7` — `frontendDist: "./loading"`
- Implication: If sidecar fails to start/listen, loading screen shows indefinitely.
- Confidence: HIGH

- Finding: PyInstaller spec uses `onefile` mode, bundles all tidal_dl submodules as explicit hiddenimports, bundles static assets as datas. UPX enabled (`upx=True`).
- Evidence: `build/pyinstaller/music-dl-server.spec` — 66 explicit hidden imports, `tidal_datas` for static dir
- Implication: UPX on macOS ARM is a known risk — can cause Gatekeeper issues. If UPX not installed, PyInstaller falls back gracefully.
- Confidence: HIGH

- Finding: Two copies of sidecar binary in `src-tauri/binaries/` — one with space in name (`music-dl-server-aarch64-apple-darwin 2`). Stale artifact.
- Evidence: `ls -la src-tauri/binaries/`
- Implication: Tauri ignores the space-name file but should be cleaned up.
- Confidence: HIGH

### RQ3: Dependency Versions

**Python (pyproject.toml):**
- Python: >=3.12,<3.14
- FastAPI: >=0.115.0 (resolved: 0.135.2)
- uvicorn: >=0.34.0 (resolved: 0.42.0)
- tidalapi: >=0.8.11 (resolved: 0.8.11) — pinned at floor
- requests: ~=2.33.0 — very tight tilde pin
- pycryptodome: >=3.20.0
- python-ffmpeg: >=2.0.12

**Rust (Cargo.toml):**
- tauri: 2.10.3 (exact)
- tauri-plugin-updater: 2.10.1
- tauri-plugin-process: 2.3.1
- rust-version minimum: 1.77.2

**JS (package.json):**
- @tauri-apps/cli: ^2 (resolved: 2.10.1) — one patch behind Rust crate 2.10.3
- Only two runtime deps (Tauri plugins). No frontend framework.

- Implication: `requests~=2.33.0` is very tight — could block installs. Tauri CLI/crate version mismatch minor but worth noting.
- Confidence: HIGH

### RQ4: CI/CD Setup

- Finding: CI workflow `.github/workflows/build-desktop.yml` exists only on remote — NOT in local working tree. Builds Linux only (ubuntu-22.04). macOS intentionally removed.
- Evidence: Commits `7c646d2` (make desktop updates linux-only), `e5c6321` (block unsigned mac builds)
- Implication: macOS release is intentionally local-build-only. Updater manifest has only linux-x86_64.
- Confidence: HIGH

- Finding: `check_install_context()` in `updater.rs` gates updates on being in `/Applications` — additional safety for local builds.
- Confidence: HIGH

- Finding: Full macOS-capable CI workflow exists on `fix/ci-manifest-paths` branch (not merged) — available as reference if macOS CI ever re-enabled.
- Confidence: HIGH

### RQ5: Static Asset Bundling

- Finding: Dual bundling: (1) PyInstaller datas entry bundles `tidal_dl/gui/static/**` into _MEIPASS, (2) pyproject.toml package-data for pip/uv installs.
- Evidence: spec file lines 16-17, pyproject.toml lines 50-52
- Confidence: HIGH

- Finding: `frontendDist` points to `./loading` (loading page), NOT the actual UI. Full UI served by FastAPI sidecar dynamically.
- Evidence: `tauri.conf.json:7`, `lib.rs:69`
- Implication: Tauri's normal frontend bundling is bypassed — sidecar must start for any UI to appear.
- Confidence: HIGH

- Finding: `beforeBuildCommand` has inline verification that asserts `mediaSession` and `_wfHires` in app.js — quality gate.
- Confidence: HIGH

### RQ6: Installer Scripts (feat/macos-local-installer branch)

- Finding: `scripts/install-macos-local.sh` — checks macOS/arm64/XcodeCLT/Rust/uv/Node, clones repo, builds with `npx tauri build --config '{"bundle":{"createUpdaterArtifacts":false}}'`, copies .app to /Applications.
- Evidence: Full installer script read
- Implication: `createUpdaterArtifacts:false` override is critical — without it, build fails needing TAURI_SIGNING_PRIVATE_KEY. Fixed in commit bb84952.
- Confidence: HIGH

- Finding: Installer syncs to remote default branch HEAD — rolling release, no pinned tags.
- Implication: macOS installs always get latest master. By design but no reproducible release.
- Confidence: HIGH

- Finding: Shell test harness `tests/test_macos_local_installer.sh` at repo root — NOT picked up by pytest in tidaldl-py/.
- Implication: Must be run explicitly as `bash tests/test_macos_local_installer.sh`.
- Confidence: HIGH

### Concerning Findings

1. `test_venv/` with Python 3.14 packages exists locally — project requires <3.14. Confusing.
2. `tauri.conf.json` has `createUpdaterArtifacts: true` globally — footgun for local builds without the config override.
3. Tauri CLI (2.10.1) vs Rust crate (2.10.3) minor version mismatch.
4. UPX enabled in PyInstaller spec — risk on macOS ARM.
5. Stale sidecar binary copy with space in filename in `src-tauri/binaries/`.
