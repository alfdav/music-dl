## Agent: pitfalls

### Q1: PyInstaller Onefile Pitfalls on macOS

- Found: Ad-hoc codesigning does NOT survive extraction to /tmp. Extracted components in _MEIxxxxxx/ are unsigned — Apple Silicon enforces signing on all dylibs. [source: https://github.com/pyinstaller/pyinstaller/issues/5434] Confidence: HIGH
- Found: PyInstaller has officially DEPRECATED onefile + .app bundle, will BLOCK in v7.0. Quote: "Onefile app bundles are not really single file and are heavily penalised by macOS's security scanning. Please use onedir mode instead." [source: https://pyinstaller.org/en/stable/CHANGES.html] Confidence: HIGH
- Found: Entitlements applied to onefile outer binary do NOT propagate to extracted components. [source: https://github.com/pyinstaller/pyinstaller/issues/4629] Confidence: HIGH
- Found: XProtect expanded from ~195 rules to ~328 rules in 2024. PyInstaller patterns (.pyz, _MEIXXXXXX) are now heuristic targets. First macOS infostealer via PyInstaller documented April 2025. [source: https://eclecticlight.co/2024/12/27/xprotect-ascendant-macos-security-in-2024/, https://www.jamf.com/blog/pyinstaller-malware-jamf-threat-labs/] Confidence: HIGH
- Found: Cold start on Apple Silicon for 28MB onefile: ~2.1s extraction alone. Total with uvicorn startup plausibly 5-15 seconds. [source: https://ahmedsyntax.com/pyinstaller-onefile/] Confidence: HIGH
- Found: macOS SIP strips DYLD_LIBRARY_PATH from subprocess environments. Libraries depending on it silently fail to load. [source: https://github.com/pyinstaller/pyinstaller/issues/7973] Confidence: HIGH
- Found: certifi hook removed from pyinstaller-hooks-contrib. Must manually set SSL_CERT_FILE = certifi.where() at startup. Finder-launched apps don't inherit shell env vars. [source: https://github.com/pyinstaller/pyinstaller/issues/7229] Confidence: HIGH

### Q2: Tauri v2 macOS-Specific Bugs

- Found: WebviewMessage::WithWebview leaks ObjC objects on every call — reference counts not decremented. Open issue. [source: https://github.com/tauri-apps/tauri/issues/15210] Confidence: HIGH
- Found: Continuous event emission causes unbounded memory growth — 2M events → 1.1GB frontend. Root cause in wry. [source: https://github.com/tauri-apps/tauri/issues/12724] Confidence: HIGH
- Found: Production .app blocks network calls that work in tauri dev — codesigning/entitlements difference. [source: https://github.com/tauri-apps/tauri/issues/13878] Confidence: HIGH
- Found: Window close ≠ app exit on macOS. Closing last window leaves sidecar + Rust process as zombies. Only Cmd+Q triggers cleanup. [source: https://github.com/tauri-apps/tauri/issues/5611] Confidence: HIGH
- Found: No built-in sidecar health check, auto-restart, or graceful shutdown API. Proposed but not shipped. [source: https://github.com/tauri-apps/plugins-workspace/issues/3062] Confidence: HIGH
- Found: Sidecar stdout is line-buffered to pipe. Crash before flush = lost output. Fix: print(flush=True) or python -u. [source: https://github.com/tauri-apps/tauri/issues/5022] Confidence: HIGH

### Q3: Unsigned macOS App Distribution Pitfalls

- Conflict: Wave 1 stated "Sequoia killed Finder right-click bypass." This is INCORRECT. Right-click → Open still works for unsigned non-malware apps. What changed: double-click dialog no longer has "Open Anyway" button — users must go to System Settings > Privacy & Security. [source: Apple Security documentation 2024, Homebrew/macOS discussions] Confidence: HIGH
- Found: xattr -d com.apple.quarantine still works on Sequoia. Removes quarantine flag, prevents Gatekeeper dialog. Does NOT bypass XProtect signatures. Requires Terminal + admin. [source: macOS security docs 2024-2025] Confidence: HIGH
- Found: First-launch UX for unsigned .app via double-click: blocked, "Cannot open" with only Cancel + Show in Finder. "Open Anyway" only in System Settings. Right-click → Open shows same dialog PLUS an "Open" button. [source: Apple Platform Security 2024] Confidence: HIGH

### Q4: macOS-Specific Python Issues in Frozen Apps

- Found: Frozen apps from Finder don't inherit LANG/LC_CTYPE. locale.getpreferredencoding() returns US-ASCII instead of UTF-8. File operations without explicit encoding='utf-8' corrupt non-ASCII data. [source: https://github.com/pyinstaller/pyinstaller/issues/3592] Confidence: HIGH
- Found: multiprocessing.freeze_support() required on macOS in frozen apps, not just Windows. Without it, Manager() enters infinite loops, Process() raises RuntimeError. Must be called before any framework init. [source: https://github.com/pyinstaller/pyinstaller/issues/8080] Confidence: HIGH
- Found: macOS 15.4 Sequoia strict validation of duplicate LC_RPATH entries in Mach-O binaries. Libraries with dupes (numpy, scipy) fail with dlopen errors. [source: https://fenicsproject.discourse.group/t/duplicate-lc-rpath-errors-on-macos-15-4-sequoia/17364] Confidence: HIGH
- Found: TCC does NOT restrict writes to /tmp or /var — only Desktop, Documents, Downloads, iCloud, camera, mic. PyInstaller extraction to /tmp is not blocked. [source: https://eclecticlight.co/2025/11/08/explainer-permissions-privacy-and-tcc/] Confidence: HIGH

### Q5: FastAPI/Uvicorn in Frozen Environments

- Found: PyInstaller misses uvicorn dynamic imports. Must specify: uvicorn.logging, uvicorn.loops.auto, uvicorn.protocols.http.auto, uvicorn.protocols.websockets.auto, uvicorn.lifespan.on. Without these, generic "Could not import module" with no underlying stacktrace. [source: https://github.com/Kludex/uvicorn/issues/2035] Confidence: HIGH
- Found: sys._MEIPASS in onefile mode points to temp dir that OS can clean mid-run. Onedir is mandatory for long-running servers. [source: PyInstaller operating mode docs] Confidence: HIGH
- Found: No Tauri built-in sidecar readiness mechanism. Community pattern: HTTP polling /health endpoint, 20-30s timeout for frozen envs (vs 5-10s normal). [source: https://github.com/tauri-apps/tauri/discussions/5391] Confidence: HIGH
- Found: Blocking uvicorn lifespan handler makes SIGTERM/SIGINT ineffective — server becomes unkillable zombie. Tauri cannot terminate gracefully. [source: https://github.com/Kludex/uvicorn/issues/2751] Confidence: HIGH
- Found: Dual instance → port conflict. Two Tauri app launches both try port 8765 — second sidecar silently fails. No retry/negotiation built in. [source: https://github.com/Kludex/uvicorn/discussions/1820] Confidence: HIGH

### Key Corrections to Wave 1

1. Sequoia right-click bypass NOT removed — wave 1 was wrong
2. PyInstaller onefile + .app officially deprecated, blocked in v7.0
3. Ad-hoc sig doesn't survive extraction — deeper than just "UPX incompatible"
4. SSL certs need manual setup — certifi hook was removed
5. Frozen Finder apps don't inherit locale — US-ASCII default breaks non-ASCII paths
