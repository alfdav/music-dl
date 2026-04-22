# Research Brief: binary-release

**Generated:** 2026-04-11
**Agents:** 2 codebase, 3 web
**Sources consulted:** ~25 unique URLs/repos/issues referenced

## Summary

The current build pipeline (PyInstaller onefile + Tauri sidecar) has a critical flaw: PyInstaller's `--onefile` mode is deprecated for macOS `.app` bundles, breaks ad-hoc codesigning on Apple Silicon, and will be blocked entirely in PyInstaller v7.0. The project must switch to `--onedir` before releasing a macOS binary. Distribution without a paid Apple Developer account ($99/yr) is viable but requires clear user-facing instructions for bypassing Gatekeeper, and auto-update is impractical for unsigned builds since every update re-triggers Gatekeeper.

## Key Findings

### Architecture & Patterns

- **Monorepo with three build layers:** `tidaldl-py/` (Python backend), `src-tauri/` (Rust/Tauri shell), `scripts/` (installer). Build order is rigid: PyInstaller first, copy sidecar to `binaries/`, then `tauri build`. [confidence: HIGH] [sources: 2]
- **Sidecar TCP polling:** Tauri polls localhost:8765 with 200ms interval, 30s timeout. No built-in readiness API in Tauri. Loading splash shown until sidecar responds. [confidence: HIGH] [sources: 3]
- **Hidden imports manually maintained:** 66 explicit hidden imports in PyInstaller spec. New route modules under `gui/api/` must be manually added. [confidence: HIGH] [sources: 1]
- **Stale sidecar binary with space in filename** in `src-tauri/binaries/` — build confusion risk. [confidence: HIGH] [sources: 1]
- **40+ bare `except Exception: pass`** — intentional crash suppression, hides debugging info. [confidence: HIGH] [sources: 1]
- **30 test files, 403 functions. Six modules untested:** waveform, library_scanner, metadata, dash, playback, wrapper. [confidence: HIGH] [sources: 1]

### Library Landscape

- **Recommended: PyInstaller v6.19.0 `--onedir`** — Mandatory for macOS. Onefile breaks codesigning, deprecated for `.app`, blocked in v7.0. [confidence: HIGH]
- **Recommended: create-dmg v1.2.3** — Pure shell + hdiutil, 2.5k stars, built-in codesign/notarize flags. Best DMG tool for unsigned distribution. [confidence: HIGH]
- **Alternative: Nuitka v4.0.5** — Native compilation, 28MB binary, 80ms startup. Upgrade path, not for initial release. [confidence: MEDIUM]
- **Avoid: PyInstaller `--onefile` on macOS** — Extracted files lose codesigning, XProtect targets PyInstaller patterns, Apple Silicon enforces signing on all dylibs. [confidence: HIGH]
- **Avoid: notarization** — Free Apple accounts can't notarize. ExternalBin sidecar independently breaks notarization (tauri#11992). [confidence: HIGH]

### Best Practices

- **Ad-hoc signing required on Apple Silicon:** `codesign -s -` must be applied to `.app` and all embedded binaries.
- **Entitlements file needed:** JIT + unsigned executable memory for WebKit renderer.
- **`multiprocessing.freeze_support()` required on macOS** for frozen apps — not just Windows.
- **`SSL_CERT_FILE` must be set manually:** certifi hook was removed from PyInstaller.
- **Locale defaults to US-ASCII** when launched from Finder. Must set `LANG`/`LC_CTYPE` explicitly.
- **SIP strips `DYLD_LIBRARY_PATH`** — cannot rely on dynamic library path manipulation.

### Existing Art

- **dieharders/example-tauri-v2-python-server-sidecar** — Reference implementation for Tauri v2 + FastAPI sidecar. Uses stdin/stdout lifecycle control.
- **tauri#5611** — Window close ≠ app exit; sidecar + Rust process become zombies. Must implement explicit shutdown signaling.

### Pitfalls to Avoid

- **Onefile + codesigning incompatibility** — Extracted temp files are unsigned, Apple Silicon refuses to run them. Switch to `--onedir`. Confirmed by 3 agents. [confidence: HIGH]
- **Cold start latency:** 5-15 seconds on Apple Silicon for uvicorn in frozen mode. 30s polling timeout appropriate but splash screen essential. [confidence: HIGH]
- **Port conflict on 8765:** No dual-instance guard. Second sidecar fails silently. [confidence: MEDIUM]
- **Unbounded `_playlist_tracks_cache`** — Memory leak in long sessions. [confidence: HIGH]
- **`assert db._conn` in production (10+ occurrences)** — Stripped with `python -O`, become no-ops. [confidence: HIGH]
- **`_login_state` race condition** — No lock on settings.py:156-200. [confidence: MEDIUM]
- **Blocking lifespan handler → unkillable zombie** — Sidecar ignores SIGTERM/SIGINT. [confidence: HIGH]
- **Tauri WebviewMessage ObjC leak (tauri#15210)** and unbounded memory on continuous events (tauri#12724). [confidence: MEDIUM]
- **macOS 15.4 strict `LC_RPATH` validation** — Duplicate rpaths in compiled extensions cause load failures. [confidence: MEDIUM]
- **Tauri CLI 2.10.1 vs Rust crate 2.10.3 mismatch.** Pin to same version. [confidence: MEDIUM]

## Contradictions & Open Questions

- **Sequoia Gatekeeper bypass:** Best-practices agent said right-click bypass was removed. Pitfalls agent corrected this. **Assessment: Right-click → Open still works on Sequoia.** What changed is the double-click flow — no inline "Open Anyway" button. Users must right-click → Open, use System Settings → Open Anyway, or `xattr -d com.apple.quarantine`. Three web agents converge on this.
- **Auto-update viability:** Installer script correctly disables updater (`createUpdaterArtifacts:false`). But `tauri.conf.json` default is `true` — footgun for anyone running `npx tauri build` directly. **Should flip default to `false`, CI overrides to `true`.**
- **UPX on macOS ARM:** Codebase agent flagged UPX enabled. Web agent confirmed incompatible with ARM64. **Disable UPX for macOS ARM builds.**
- **CI for macOS:** Full macOS CI workflow exists on `fix/ci-manifest-paths` (unmerged). Current CI is Linux-only. `blank | needs user input on CI strategy`

## Codebase Context

- **Architecture:** Tauri desktop shell wraps Python FastAPI backend as sidecar. Frontend is vanilla JS SPA (6952 lines) served by FastAPI, not Tauri's frontendDist (which holds loading splash only). 11 API route modules under gui/api/.
- **Key patterns:** `sys._MEIPASS` frozen detection. CSRF auto-refresh with dedup. Download queue in localStorage. 3-tier config recovery. 40+ bare except-pass blocks.
- **Dependencies:** Python >=3.12,<3.14. FastAPI 0.135.2. uvicorn 0.42.0. tidalapi 0.8.11. Tauri 2.10.3. requests ~=2.33.0 (tight pin).
- **Test coverage:** 403 tests across 30 files. No coverage tool. No CI locally. Six modules completely untested: waveform, library_scanner, metadata, dash, playback, wrapper.
- **Known tech debt:** tidalapi hi_res silent mapping. Two TODOs in download.py. CSP null in tauri.conf.json.

## Implications for Design

1. **Must switch PyInstaller to `--onedir` before release.** Non-negotiable. Changes sidecar packaging — becomes a directory, not single file.
2. **Updater must be disabled for unsigned builds.** Flip `tauri.conf.json` default to `false`.
3. **User-facing Gatekeeper bypass instructions are mandatory.** Three methods: right-click → Open, System Settings → Open Anyway, or `xattr -d com.apple.quarantine`.
4. **Entitlements file must be created** with JIT and unsigned-executable-memory for WebView.
5. **SSL, locale, and freeze_support must be handled explicitly** in sidecar entry — silent failures only in production `.app`.
6. **Sidecar lifecycle needs explicit shutdown signaling** — without it, closing window leaves zombie processes.
7. **Port 8765 needs dual-instance guard** to prevent silent failure.
8. **UPX should be disabled** for macOS ARM builds.
9. **Clean up stale binary** with space in filename from `src-tauri/binaries/`.
10. **Pin Tauri CLI and crate to same version** (2.10.3).

## Sources

- [Tauri v2 macOS Signing](https://v2.tauri.app/distribute/sign/macos/) — Signing config, ad-hoc, Developer ID
- [Tauri v2 Sidecar Docs](https://v2.tauri.app/develop/sidecar/) — ExternalBin, binary naming, target triple
- [Tauri v2 Updater Plugin](https://v2.tauri.app/plugin/updater/) — Ed25519 signatures, update artifacts
- [Tauri v2 macOS Bundle](https://v2.tauri.app/distribute/macos-application-bundle/) — .app config, entitlements
- [Tauri v2 DMG](https://v2.tauri.app/distribute/dmg/) — DMG creation, config
- [tauri#11992](https://github.com/tauri-apps/tauri/issues/11992) — ExternalBin sidecar breaks notarization
- [tauri#5611](https://github.com/tauri-apps/tauri/issues/5611) — Window close leaves sidecar zombies
- [tauri#15210](https://github.com/tauri-apps/tauri/issues/15210) — WebviewMessage ObjC memory leak
- [tauri#12724](https://github.com/tauri-apps/tauri/issues/12724) — Continuous events unbounded memory
- [tauri#13878](https://github.com/tauri-apps/tauri/issues/13878) — Production .app blocks network calls
- [CVE-2025-31477](https://github.com/tauri-apps/plugins-workspace/security/advisories/GHSA-c9pr-q8gx-3mgp) — tauri-plugin-shell command injection
- [dieharders/example-tauri-v2-python-server-sidecar](https://github.com/dieharders/example-tauri-v2-python-server-sidecar) — Reference implementation
- [create-dmg](https://github.com/create-dmg/create-dmg) — DMG creation tool v1.2.3
- [PyInstaller CHANGES](https://pyinstaller.org/en/stable/CHANGES.html) — Onefile + .app deprecation
- [PyInstaller#5434](https://github.com/pyinstaller/pyinstaller/issues/5434) — Codesigning breaks on extraction
- [PyInstaller#4629](https://github.com/pyinstaller/pyinstaller/issues/4629) — Entitlements don't propagate
- [PyInstaller#7229](https://github.com/pyinstaller/pyinstaller/issues/7229) — SSL certifi hook removed
- [PyInstaller#3592](https://github.com/pyinstaller/pyinstaller/issues/3592) — Locale defaults to US-ASCII
- [PyInstaller#8080](https://github.com/pyinstaller/pyinstaller/issues/8080) — freeze_support on macOS
- [PyInstaller#7973](https://github.com/pyinstaller/pyinstaller/issues/7973) — SIP strips DYLD_LIBRARY_PATH
- [Building Desktop Apps with Tauri + FastAPI](https://aiechoes.substack.com/p/building-production-ready-desktop) — Build sequence, spec files
- [Shipping macOS App with Tauri 2.0](https://dev.to/0xmassi/shipping-a-production-macos-app-with-tauri-20-code-signing-notarization-and-homebrew-mc3) — Entitlements, signing
- [macOS Code Signing History](https://eclecticlight.co/2025/04/26/a-brief-history-of-code-signing-on-macs/) — Sequoia Gatekeeper changes
- [XProtect in 2024](https://eclecticlight.co/2024/12/27/xprotect-ascendant-macos-security-in-2024/) — PyInstaller as heuristic target
- [Ad-hoc Signing Guide](https://gist.github.com/rsms/929c9c2fec231f0cf843a1a746a416f5) — Quarantine, xattr
