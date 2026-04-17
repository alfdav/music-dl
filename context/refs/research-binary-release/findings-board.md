# Findings Board: Fixing bugs and releasing macOS binary

> Shared coordination state for research agents.
> Later agents read this before searching to avoid duplicates and build on earlier work.

## Wave 1 Results (4 agents complete)

### Codebase: Architecture & Dependencies
- Monorepo: TIDALDL-PY/ (Python), src-tauri/ (Rust/Tauri), scripts/ (installer)
- Build pipeline: PyInstaller onefile → Tauri externalBin sidecar → .app/.dmg
- Tauri polls sidecar TCP on port 8765, 200ms interval, 30s timeout, loading page until ready
- frontendDist = ./loading (splash), actual UI served by FastAPI sidecar at localhost:8765
- beforeBuildCommand runs PyInstaller + verifies app.js markers (mediaSession, _wfHires)
- CI builds Linux only — macOS intentionally local-build-only (commits 7c646d2, e5c6321)
- Installer overrides createUpdaterArtifacts:false to avoid needing TAURI_SIGNING_PRIVATE_KEY
- UPX enabled in PyInstaller spec — incompatible with ARM64 per web research
- Stale binary copy with space in filename in src-tauri/binaries/
- Tauri CLI 2.10.1 vs Rust crate 2.10.3 minor mismatch
- requests~=2.33.0 very tight pin

### Codebase: Patterns & Tests
- 30 test files, 403 test functions. No coverage tool. No CI config locally.
- UNTESTED critical paths: waveform.py, library_scanner.py, metadata.py, dash.py, playback.py
- 40+ except Exception: pass — intentional "never crash" but hides bugs
- _login_state race condition (settings.py:156-200) — dict mutated from request + background thread without lock
- assert db._conn in production handlers (10+ occurrences) — fragile if optimize>0
- CSP null in tauri.conf.json — no Content Security Policy
- _playlist_tracks_cache unbounded — memory leak for long sessions
- Download retry is solid: 3 retries, exponential backoff, retryable vs permanent distinction
- Config loading robust: 3-tier recovery (exact → tolerant merge → backup)
- Frontend: vanilla JS SPA, single global state, innerHTML only for SVG icons (no XSS)

### Web: Library Landscape
- PyInstaller v6.19.0 (12.9k stars) recommended, --onedir mode preferred. UPX incompatible with ARM64.
- Nuitka v4.0.5 (14.7k stars) as upgrade path — 28MB binary, 80ms startup vs 65MB/650ms PyInstaller
- create-dmg v1.2.3 (2.5k stars) winner for DMG creation — zero deps, built-in codesign/notarize
- Notarization impossible without paid Apple Developer account ($99/yr)
- Ad-hoc signing required on Apple Silicon even for local dev (codesign -s -)
- tauri-plugin-shell v2.3.5 — CVE-2025-31477 patched in v2.2.1 (file:// protocol exposure)
- rcodesign can sign on Linux but still needs paid Apple account for notarize
- dieharders/example-tauri-v2-python-server-sidecar is best reference repo

### Web: Best Practices & Existing Art
- macOS Sequoia killed Finder right-click bypass — "Open Anyway" in System Settings only path
- Quarantine xattr added by browser downloads only (not curl/scp/tar)
- ExternalBin sidecar breaks notarization — open bug tauri#11992
- Auto-update impractical for unsigned local installs — every update re-triggers Gatekeeper
- Build sequence order-critical: PyInstaller binary → copy to binaries/ → tauri build
- Binary naming must be exact target triple (rustc --print host-tuple)
- Startup race condition in Pattern B (Python serves UI) — Tauri loads webview before server ready
- Tauri updater needs Ed25519 keypair (independent of Apple signing) — can't disable signatures
