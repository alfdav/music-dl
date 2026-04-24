<!--
  Canonical install block.

  Injected into every GitHub release body by .github/workflows/build-desktop.yml
  (publish-manifest job). Also surfaced from README.md Option 1b.

  Edit this file only — both release notes and README reference it.
-->

---

## Install

### macOS (Apple Silicon) — quick install

Downloads the `.dmg` attached to the latest GitHub release, verifies the GitHub release checksum, installs to `/Applications`, handles Gatekeeper automatically. No dev tools needed.

```shell
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.sh | bash
```

### macOS — build from source

If you prefer to build locally (or want the latest code), the installer handles Xcode tools, `uv`, Node, Rust, and Tauri. On success it installs `music-dl.app` to `/Applications/music-dl.app` with no Gatekeeper prompts since the app is built on your machine.

```shell
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-macos-local.sh | bash
```

### Linux (x86_64)

Download the `.AppImage` from the release assets below, then:

```shell
chmod +x music-dl_*.AppImage
./music-dl_*.AppImage
```

For Debian/Ubuntu, the `.deb` is also available in the assets:

```shell
sudo dpkg -i music-dl_*.deb
```

### Windows 10/11

Download the unsigned `.msi` from the release assets below and run it.

Windows SmartScreen may warn because early Windows builds are unsigned. Choose **More info**, then **Run anyway** only if you downloaded the installer from the official `alfdav/music-dl` GitHub release.

WSL is not required.

### Updating

- macOS quick install users: rerun the same `curl` command — it replaces the old version in place.
- Linux users: download the latest `.AppImage` or `.deb` from GitHub Releases. The app also self-updates on launch when a signed Linux update manifest is published.
- Windows users: download and run the newest `.msi` from GitHub Releases. Windows updater support is not published yet.

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
