## Agent: library-landscape

### Q1 — Tauri v2 Build Tools for macOS

- Found: tauri-cli v2.10.3 (Rust), @tauri-apps/cli v2.10.1 (npm), tauri-bundler v2.8.1, @tauri-apps/api v2.10.1. Coordinated releases. [source: https://v2.tauri.app/release/] Confidence: HIGH
- Found: Tauri v2 stable released October 2024, security audited by Radically Open Security. [source: https://v2.tauri.app/blog/tauri-20/] Confidence: HIGH
- Found: Xcode CLT sufficient for macOS-only targets. macOS uses system WebKit, minimum deployment 10.13. [source: https://v2.tauri.app/start/prerequisites/] Confidence: HIGH
- Found: Universal binary via `tauri build --target universal-apple-darwin`. Needs both rust targets. [source: https://v2.tauri.app/start/prerequisites/] Confidence: HIGH
- Found: Cross-compilation to macOS NOT supported — must build on macOS hardware. [source: https://v2.tauri.app/distribute/dmg/] Confidence: HIGH
- Found: 60k+ GitHub stars, 5.3% developer adoption, 91.7% retention, 35% YoY growth. [source: https://sparkco.ai/blog/tauri] Confidence: HIGH

### Q2 — PyInstaller Alternatives for Python Sidecar

**PyInstaller v6.19.0** (Feb 2026, 12.9k stars):
- Works well with FastAPI/uvicorn in --onedir mode
- --onefile has extraction timing → socket binding delay
- UPX incompatible with ARM64 (Apple Silicon)
- ~65 MB binary, ~650 ms startup
- Confidence: HIGH

**Nuitka v4.0.5** (Mar 2026, 14.7k stars):
- True compilation, smallest binaries (~28 MB), fastest startup (~80 ms)
- 5-15 min compile time, dynamic imports need --follow-imports
- Confidence: HIGH

**cx_Freeze v6.15+** (1.2k stars):
- uvicorn discovery failure, SSL bundling issues
- Confidence: MEDIUM

**PyOxidizer** (4.5k stars):
- Built-in codesign + notarization, universal binary support
- Steep learning curve (Starlark config), development slowing
- Confidence: MEDIUM

**Briefcase** (2.5k stars): Reject for sidecar use case.
**py2app** (500 stars): Deprecated for new projects.

**Recommendation:** PyInstaller v6.19 --onedir (primary), Nuitka v4.0 as upgrade path.

### Q3 — macOS DMG/Unsigned Distribution Tools

**create-dmg v1.2.3** (Nov 2025, 2.5k stars):
- Pure shell + hdiutil, zero deps, Homebrew-installable
- Built-in --codesign and --notarize flags
- Works without Apple Developer cert for DMG creation
- **Winner for this project**
- Confidence: HIGH

**dmgbuild v1.6.7** (Jan 2026): pip-installable, Python-based. Good for Python pipelines.
**node-appdmg**: Last updated ~2023 — avoid.
**hdiutil**: Always available, zero customization without scripting.

**Critical:** macOS Sequoia removed Control-click override for unsigned apps. Users must use System Settings > Privacy & Security > "Open Anyway". Quarantine (`com.apple.quarantine`) applied by browser downloads. [source: https://apple.slashdot.org/story/24/08/07/2129235/]

### Q4 — Notarization and Ad-Hoc Signing

- Found: Ad-hoc signing `codesign -s - --deep` required on Apple Silicon even for local dev. Passes codesign --verify but fails spctl (Gatekeeper). [source: https://stories.miln.eu/graham/2024-06-25-ad-hoc-code-signing-a-mac-app/] Confidence: HIGH
- Found: altool deprecated Nov 2023. All notarization via `xcrun notarytool`. Requires paid Apple Developer ($99/yr) — no workaround. [source: Apple developer docs] Confidence: HIGH
- Found: rcodesign (apple-platform-rs, 743 stars) — pure Rust, can sign+notarize on Linux/Windows/macOS. GitHub Action available. Still requires paid Apple account for notarization. [source: https://github.com/indygreg/apple-platform-rs] Confidence: HIGH
- Found: Tauri v2 has native signing via env vars. Ad-hoc via `signingIdentity: "-"`. [source: https://v2.tauri.app/distribute/sign/macos/] Confidence: HIGH

**For this project:** Ad-hoc sign + strip quarantine in install instructions. Notarization not achievable without paid account.

### Q5 — Tauri Plugins for Python Sidecar

- Found: tauri-plugin-shell v2.3.5. **CVE-2025-31477** (CVSS: High) patched in v2.2.1 — `open` endpoint allowed file://, smb://, nfs:// with untrusted input. Update immediately. [source: https://github.com/tauri-apps/plugins-workspace/security/advisories/GHSA-c9pr-q8gx-3mgp] Confidence: HIGH
- Found: tauri-sidecar-manager (radical-data, 4 stars, Feb 2025) — Arc<Mutex> lifecycle management. Too immature for production. Confidence: MEDIUM
- Found: PyInstaller + Windows kill() bug (tauri#11686) — bootloader PID issue. macOS NOT affected. Confidence: HIGH
- Found: PyTauri (Pyo3 bindings) — experimental, not production-ready. Confidence: HIGH

### Summary Matrix

| Area | Tool | Version | Stars |
|---|---|---|---|
| Tauri CLI | @tauri-apps/cli | 2.10.1 | 60k+ |
| Python bundler | PyInstaller --onedir | 6.19.0 | 12.9k |
| DMG creation | create-dmg | 1.2.3 | 2.5k |
| Ad-hoc signing | codesign -s - | macOS built-in | — |
| Notarization | Not possible without $99/yr | — | — |
| Sidecar mgmt | tauri-plugin-shell | 2.3.5 | — |
