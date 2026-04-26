# Windows MSI Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repeatable GitHub Actions path that builds an unsigned native Windows 10/11 MSI for `music-dl`, with a Windows sidecar health smoke and updated release docs.

**Architecture:** Keep the existing Tauri + PyInstaller sidecar architecture. Extend the existing desktop release workflow with Windows-specific steps instead of creating a separate release system. Keep runtime code changes limited to Windows portability needed for the sidecar to start.

**Tech Stack:** Python 3.12, uv, PyInstaller, FastAPI/uvicorn sidecar, Tauri v2, Bun, GitHub Actions, Windows MSI/WiX.

---

## File Structure

- Modify `tidaldl-py/sidecar_entry.py`: make signal ignoring portable on Windows.
- Add `tidaldl-py/tests/test_sidecar_entry.py`: regression tests for signal setup.
- Modify `.github/workflows/build-desktop.yml`: add Windows MSI build path, Windows-safe sidecar build commands, sidecar health smoke, artifact upload, and release upload.
- Add `tidaldl-py/src-tauri/tauri.ci.conf.json`: disable the local Unix `beforeBuildCommand` for CI builds that already build the sidecar explicitly.
- Modify `README.md`: add Windows MSI install/build notes.
- Modify `docs/release/install-instructions.md`: add Windows release install instructions and expected asset.
- Modify `CONTRIBUTING.md`: add maintainer-facing Windows release smoke checklist.

No new app module, installer framework, or backend abstraction is needed.

## Task 1: Windows-Safe Sidecar Startup

**Files:**
- Modify: `tidaldl-py/sidecar_entry.py`
- Create: `tidaldl-py/tests/test_sidecar_entry.py`

- [x] **Step 1: Write failing tests for portable signal setup**

Create `tidaldl-py/tests/test_sidecar_entry.py`:

```python
import signal

import sidecar_entry


def test_ignore_shutdown_signals_skips_missing_signals(monkeypatch):
    calls = []

    monkeypatch.delattr(signal, "SIGHUP", raising=False)
    monkeypatch.setattr(signal, "SIGINT", 2, raising=False)
    monkeypatch.setattr(signal, "SIG_IGN", object(), raising=False)

    def fake_signal(sig, handler):
        calls.append((sig, handler))

    monkeypatch.setattr(sidecar_entry.signal, "signal", fake_signal)

    sidecar_entry._ignore_shutdown_signals()

    assert calls == [(signal.SIGINT, signal.SIG_IGN)]


def test_ignore_shutdown_signals_ignores_unsupported_signal(monkeypatch):
    calls = []

    monkeypatch.setattr(signal, "SIGINT", 2, raising=False)
    monkeypatch.setattr(signal, "SIGHUP", 1, raising=False)
    monkeypatch.setattr(signal, "SIG_IGN", object(), raising=False)

    def fake_signal(sig, handler):
        calls.append((sig, handler))
        if sig == signal.SIGHUP:
            raise ValueError("unsupported signal")

    monkeypatch.setattr(sidecar_entry.signal, "signal", fake_signal)

    sidecar_entry._ignore_shutdown_signals()

    assert calls == [(signal.SIGINT, signal.SIG_IGN), (signal.SIGHUP, signal.SIG_IGN)]
```

- [x] **Step 2: Run tests to verify failure**

Run:

```bash
cd tidaldl-py
uv run --extra test pytest tests/test_sidecar_entry.py -v
```

Expected: FAIL because `_ignore_shutdown_signals` does not exist.

- [x] **Step 3: Implement minimal portable signal helper**

In `tidaldl-py/sidecar_entry.py`, add:

```python
def _ignore_shutdown_signals() -> None:
    for name in ("SIGINT", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, signal.SIG_IGN)
        except (OSError, RuntimeError, ValueError):
            continue
```

Then replace the two direct `signal.signal(...)` calls in `main()` with:

```python
_ignore_shutdown_signals()
```

- [x] **Step 4: Run focused test**

Run:

```bash
cd tidaldl-py
uv run --extra test pytest tests/test_sidecar_entry.py -v
```

Expected: PASS.

- [x] **Step 5: Run sidecar-related Python checks**

Run:

```bash
cd tidaldl-py
uv run --extra test pytest tests/test_sidecar_entry.py tests/test_gui_daemon.py tests/test_packaging.py -v
```

Expected: PASS.

## Task 2: Windows MSI GitHub Actions Build

**Files:**
- Modify: `.github/workflows/build-desktop.yml`
- Create: `tidaldl-py/src-tauri/tauri.ci.conf.json`

- [x] **Step 1: Add Windows matrix entry**

Extend the build matrix with:

```yaml
          - os: windows-latest
            target: x86_64-pc-windows-msvc
            label: windows-x86_64
```

- [x] **Step 2: Use Bun for Tauri package commands**

Replace the Node/npm-only install/build shape with Bun setup:

```yaml
      - name: Set up Bun
        uses: oven-sh/setup-bun@v2
        with:
          bun-version: latest

      - name: Install Tauri dependencies
        run: bun install
```

Use `bunx tauri ...` for Tauri builds.

- [x] **Step 3: Split sidecar build by OS**

Keep the current Linux sidecar build shape for Linux.

Add a Windows PowerShell sidecar build step:

```yaml
      - name: Build PyInstaller sidecar (Windows)
        if: runner.os == 'Windows'
        shell: pwsh
        run: |
          $TargetTriple = rustc --print host-tuple
          uv run pyinstaller --clean `
            --distpath src-tauri/binaries `
            --workpath build/pyinstaller `
            --noconfirm `
            build/pyinstaller/music-dl-server.spec
          Move-Item `
            -Path "src-tauri/binaries/music-dl-server.exe" `
            -Destination "src-tauri/binaries/music-dl-server-$TargetTriple.exe" `
            -Force
```

For Linux, prefer `uv run pyinstaller` if dependencies are installed into the project environment; otherwise keep `.venv/bin/pyinstaller` to avoid changing a known-good path.

- [x] **Step 4: Split asset verification by OS**

Add a Windows-safe static asset verification step using PowerShell or `uv run python -c`.

- [x] **Step 5: Add Windows sidecar health smoke**

After the Windows sidecar build and rename, run the built sidecar and wait for `/api/server/health`:

```yaml
      - name: Smoke test Windows sidecar
        if: runner.os == 'Windows'
        shell: pwsh
        run: |
          $env:MUSIC_DL_CONFIG_DIR = Join-Path $env:RUNNER_TEMP "music-dl-config"
          New-Item -ItemType Directory -Force -Path $env:MUSIC_DL_CONFIG_DIR | Out-Null
          $MetadataPath = Join-Path $env:MUSIC_DL_CONFIG_DIR "daemon.json"
          $Sidecar = Get-ChildItem "src-tauri/binaries/music-dl-server-*.exe" | Select-Object -First 1
          $Process = Start-Process -FilePath $Sidecar.FullName -ArgumentList "8765" -PassThru
          try {
            $Ready = $false
            for ($i = 0; $i -lt 60; $i++) {
              try {
                if (-not (Test-Path $MetadataPath)) {
                  Start-Sleep -Seconds 1
                  continue
                }
                $Metadata = Get-Content $MetadataPath -Raw | ConvertFrom-Json
                $Health = Invoke-RestMethod -Uri $Metadata.health_url -TimeoutSec 2
                if ($Health.app -eq "music-dl" -and $Health.status -eq "ready") {
                  $Ready = $true
                  break
                }
              } catch {
                Start-Sleep -Seconds 1
              }
            }
            if (-not $Ready) {
              throw "Windows sidecar did not become ready"
            }
          } finally {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
          }
```

- [x] **Step 6: Build Windows MSI only on Windows**

Change the Tauri build step to use OS-specific commands:

```yaml
      - name: Build Tauri app (Linux)
        if: runner.os == 'Linux'
        run: bunx tauri build --target ${{ matrix.target }}

      - name: Build Tauri app (Windows MSI)
        if: runner.os == 'Windows'
        shell: pwsh
        run: bunx tauri build --target ${{ matrix.target }} --bundles msi
```

Pass the existing `TAURI_SIGNING_PRIVATE_KEY` env to both steps.

- [x] **Step 7: Upload Windows artifact and release asset**

Add upload paths:

```yaml
      - name: Upload Windows desktop artifacts
        if: runner.os == 'Windows'
        uses: actions/upload-artifact@v4
        with:
          name: music-dl-${{ matrix.label }}
          path: tidaldl-py/src-tauri/target/${{ matrix.target }}/release/bundle/msi/*.msi
          if-no-files-found: error
```

Add the same MSI path to tagged release upload with an OS guard or separate Windows release upload step.

- [x] **Step 8: Keep `publish-manifest` Linux-only for updater**

Do not require Windows MSI for `latest.json`. The existing manifest should keep using the Linux AppImage signature only.

- [x] **Step 9: Validate workflow syntax locally as far as possible**

Run:

```bash
git diff --check .github/workflows/build-desktop.yml
```

Expected: no whitespace errors.

## Task 3: Windows Release Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/release/install-instructions.md`
- Modify: `CONTRIBUTING.md`

- [x] **Step 1: Update release install instructions**

In `docs/release/install-instructions.md`, add a Windows section:

```markdown
### Windows 10/11

Download the unsigned `.msi` from the release assets below and run it.

Windows SmartScreen may warn because early Windows builds are unsigned. Choose **More info** → **Run anyway** only if you downloaded the installer from the official `alfdav/music-dl` GitHub release.

WSL is not required.
```

Update expected release assets:

```markdown
- Windows: `.msi`
```

- [x] **Step 2: Update README Get Started section**

Add Windows beside Linux/macOS desktop app instructions:

```markdown
- **Windows 10/11**: download the unsigned `.msi` from GitHub Releases. SmartScreen warnings are expected for early unsigned builds.
```

- [x] **Step 3: Update build docs**

In `README.md` desktop build section, add Windows prerequisites and command:

```markdown
**Windows 10/11:**
- WebView2 Runtime (normally already installed on Windows 10/11)
- Microsoft C++ Build Tools / Visual Studio Build Tools
- WiX requirements used by Tauri MSI builds

```shell
bunx tauri build --bundles msi
```
```

Also update the output sentence to include `.msi` for Windows.

- [x] **Step 4: Add manual Windows smoke checklist**

Add a short checklist to README or release instructions, and include the maintainer-facing version in `CONTRIBUTING.md`:

```markdown
Windows smoke test before marking a release supported:

1. Install the MSI.
2. Launch `music-dl`.
3. Complete or recover Tidal authentication.
4. Choose a local library/download path.
5. Search for one track.
6. Download one track.
7. Play that track.
8. Quit and reopen the app.
9. Confirm settings, auth, and library state persist.
```

- [x] **Step 5: Validate docs**

Run:

```bash
git diff --check README.md docs/release/install-instructions.md CONTRIBUTING.md
```

Expected: no whitespace errors.

## Task 4: Integration Verification

**Files:**
- All files touched by Tasks 1-3.

- [x] **Step 1: Review combined diff**

Run:

```bash
git diff --stat
git diff -- .github/workflows/build-desktop.yml tidaldl-py/sidecar_entry.py tidaldl-py/tests/test_sidecar_entry.py README.md docs/release/install-instructions.md
```

Expected: changes are limited to Windows MSI release support.

- [x] **Step 2: Run focused Python tests**

Run:

```bash
cd tidaldl-py
uv run --extra test pytest tests/test_sidecar_entry.py tests/test_gui_daemon.py tests/test_packaging.py -v
```

Expected: PASS.

- [x] **Step 3: Run release smoke subset**

Run:

```bash
uv run --project tidaldl-py --extra test pytest \
  tidaldl-py/tests/test_gui_command.py \
  tidaldl-py/tests/test_gui_api.py \
  tidaldl-py/tests/test_setup.py \
  tidaldl-py/tests/test_token_refresh.py \
  tidaldl-py/tests/test_public_branding.py \
  tidaldl-py/tests/test_packaging.py \
  tidaldl-py/tests/test_sidecar_entry.py
```

Expected: PASS.

- [x] **Step 4: Check formatting-sensitive diffs**

Run:

```bash
git diff --check
```

Expected: PASS.

- [x] **Step 5: Commit**

Run:

```bash
git add .github/workflows/build-desktop.yml README.md CONTRIBUTING.md docs/release/install-instructions.md tidaldl-py/sidecar_entry.py tidaldl-py/tests/test_sidecar_entry.py docs/superpowers/plans/2026-04-24-windows-msi-release.md
git commit -m "Add Windows MSI release path"
```
