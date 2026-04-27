<!--
  Canonical install block.

  Injected into every GitHub release body by .github/workflows/build-desktop.yml
  (publish-manifest job). Also surfaced from README.md.

  Edit this file only — both release notes and README reference it.
-->

---

## Install

### Desktop: macOS / Linux

Copy this into Terminal:

```shell
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.sh | bash
```

What it does:

- **macOS Apple Silicon**: downloads the latest `.dmg`, verifies the GitHub release checksum, installs to `/Applications`, strips quarantine, then opens `music-dl.app`.
- **Linux x86_64**: downloads the latest `.AppImage`, verifies the GitHub release checksum, installs it as `~/.local/bin/music-dl`.

If macOS reports a DMG mount failure, rerun the current command from this document before trying manual install steps. The installer keeps progress output separate from returned file paths so `hdiutil` receives the verified DMG path, not status text.

### Desktop: Windows 10/11

Copy this into PowerShell:

```powershell
irm https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.ps1 | iex
```

Downloads the latest unsigned `.msi`, verifies the GitHub release checksum, then starts the Windows installer. SmartScreen warnings are expected for early unsigned builds. WSL is not required.

### Headless / NAS / Docker

Copy this into Terminal:

```shell
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-docker.sh | bash
```

Builds and starts the Docker Compose GUI at `http://localhost:8765`. Use this for Linux servers, NAS boxes, or machines where you do not want desktop packaging.

### macOS: build from source

If you prefer to build locally, copy this into Terminal:

```shell
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-macos-local.sh | bash
```

On success, it installs `music-dl.app` to `/Applications/music-dl.app`. Requires Xcode Command Line Tools, Rust, `uv`, and Bun.

### Internal latest from `master`

Use these on our own machines when `master` has newer commits than the latest GitHub release and we do not want to cut new binaries yet.

No local build tools, rolling edge channel:

```shell
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.sh | MUSIC_DL_RELEASE_TAG=edge bash
```

```powershell
$env:MUSIC_DL_RELEASE_TAG = "edge"
irm https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.ps1 | iex
Remove-Item Env:MUSIC_DL_RELEASE_TAG
```

These install the latest rolling edge artifact. Edge builds are produced automatically from `master` and point the app updater at the same edge manifest.

Build locally from source:

```shell
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-macos-local.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-windows-local.ps1 | iex
```

These build from source and install locally. They require normal build tools. Source installers use SSH Git by default (`git@github.com:alfdav/music-dl.git`), so the machine needs GitHub SSH access.

### Manual assets

Manual release assets are still available below:

- **Linux**: `.AppImage` or `.deb`
- **Windows 10/11**: unsigned `.msi`
- **macOS Apple Silicon**: `.dmg`

### Updating

- macOS/Linux desktop users: rerun the same `install.sh` command.
- Windows users: rerun the same PowerShell command and follow the MSI installer.
- Headless/Docker users: rerun the same `install-docker.sh` command.
- macOS source-build users: rerun the same `install-macos-local.sh` command.

### Expected release assets

Each release should include:

- Linux: `.AppImage`, `.AppImage.sig`, `.deb`, and `latest.json`
- macOS: `.dmg`
- Windows: `.msi`

### Windows release smoke

Before marking Windows support ready:

1. Install the MSI.
2. Launch `music-dl`.
3. Complete or recover Tidal authentication.
4. Choose a local library/download path.
5. Search for one track.
6. Download one track.
7. Play that track.
8. Quit and reopen the app.
9. Confirm settings, auth, and library state persist.

### Full docs

See the project [README](https://github.com/alfdav/music-dl/blob/master/README.md) for dev setup, Docker Compose, Discord bot onboarding, and the `uv tool install` path.
