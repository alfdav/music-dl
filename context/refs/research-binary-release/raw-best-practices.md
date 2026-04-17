## Agent: best-practices-existing-art

### Q1. Tauri v2 macOS Build Best Practices — Code Signing, Notarization, Gatekeeper

- Found: Two certificate types exist for outside-App-Store distribution. `Developer ID Application` requires paid Apple Developer account ($99/year). Ad-hoc signing (`signingIdentity: "-"`) is fallback for local/dev builds. [source: https://v2.tauri.app/distribute/sign/macos/] Confidence: HIGH
- Found: Free Apple Developer accounts cannot notarize. [source: https://v2.tauri.app/distribute/sign/macos/] Confidence: HIGH
- Found: macOS Sequoia (15) closed the Finder right-click bypass. Users must now go to System Settings > Privacy & Security > "Open Anyway". [source: https://eclecticlight.co/2025/04/26/a-brief-history-of-code-signing-on-macs/] Confidence: HIGH
- Found: Required entitlements for Tauri WebView — JIT and unsigned executable memory entitlements in Entitlements.plist. [source: https://dev.to/0xmassi/shipping-a-production-macos-app-with-tauri-20-code-signing-notarization-and-homebrew-mc3] Confidence: HIGH
- Found: Active bug — ExternalBin sidecar breaks notarization. Open issue #11992. Workaround: explicitly target login.keychain-db during codesign and/or use --deep flag. [source: https://github.com/tauri-apps/tauri/issues/11992] Confidence: HIGH

### Q2. PyInstaller + Tauri Sidecar Integration — Reference Implementations

- Found: Official Tauri v2 docs name PyInstaller as canonical Python sidecar pattern. [source: https://v2.tauri.app/develop/sidecar/] Confidence: HIGH
- Found: Binary naming convention is `<name>-<target-triple>`. Get triple from `rustc --print host-tuple`. [source: https://v2.tauri.app/develop/sidecar/] Confidence: HIGH
- Found: Reference implementation — `example-tauri-v2-python-server-sidecar` (dieharders). Uses stdin/stdout for lifecycle control instead of SIGKILL. [source: https://github.com/dieharders/example-tauri-v2-python-server-sidecar] Confidence: HIGH
- Found: Build sequence is order-critical: PyInstaller binary first, copy to src-tauri/binaries/, then tauri build. [source: https://aiechoes.substack.com/p/building-production-ready-desktop] Confidence: HIGH
- Found: PyInstaller spec files required for non-trivial Python backends. [source: https://aiechoes.substack.com/p/building-production-ready-desktop] Confidence: HIGH

### Q3. macOS Distribution Without Apple Developer ID

- Found: Ad-hoc signed code only works without user intervention on local machine. [source: https://gist.github.com/rsms/929c9c2fec231f0cf843a1a746a416f5] Confidence: HIGH
- Found: Quarantine xattr (com.apple.quarantine) is primary friction. Browser downloads add it; curl/scp/tar do NOT. Removal: `xattr -d com.apple.quarantine /path/to/YourApp.app` [source: https://gist.github.com/rsms/929c9c2fec231f0cf843a1a746a416f5] Confidence: HIGH
- Found: Tauri ad-hoc config key is `signingIdentity: "-"`. [source: https://v2.tauri.app/distribute/sign/macos/] Confidence: HIGH

### Q4. Auto-Update in Tauri v2 for Unsigned macOS Apps

- Found: Tauri v2 updater plugin requires Ed25519 signatures — cannot be disabled. Works independently of Apple code signing. [source: https://v2.tauri.app/plugin/updater/] Confidence: HIGH
- Found: For unsigned local installs, updater is effectively unusable — every update triggers Gatekeeper again. Recommend skipping updater plugin. [source: inferred from Sequoia quarantine + updater behavior] Confidence: HIGH

### Q5. Static Assets Bundling

- Found: Two patterns — Pattern A (Tauri serves assets natively via frontendDist) vs Pattern B (Python FastAPI serves via HTTP). This project uses Pattern B. [source: https://v2.tauri.app/start/frontend/ + https://github.com/dieharders/example-tauri-v2-python-server-sidecar] Confidence: HIGH
- Found: Startup race condition in Pattern B — Tauri loads WebView before Python server is ready. Mitigations: splash screen, retry loop in JS, or wait for /health endpoint. [source: inferred from architecture pattern] Confidence: HIGH

### Q6. Tauri v2 macOS Build Configuration

- Found: Build commands — `.app` only: `npm run tauri build -- --bundles app`, `.dmg`: `npm run tauri build -- --bundles dmg`. [source: https://v2.tauri.app/distribute/macos-application-bundle/] Confidence: HIGH
- Found: Sidecar binary placed in `<product-name>.app/Contents/MacOS/` automatically when externalBin is set. [source: https://v2.tauri.app/develop/sidecar/] Confidence: HIGH

### Critical Action Items

1. Sidecar + notarization bug open — tauri-apps/tauri#11992
2. Sequoia killed Finder bypass — "Open Anyway" is the only path for unsigned apps
3. Auto-update impractical for unsigned local installs — disable createUpdaterArtifacts
4. Binary naming must be exact — wrong target triple = silent build failure
5. Best reference repo: github.com/dieharders/example-tauri-v2-python-server-sidecar
