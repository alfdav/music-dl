---

## Install

### macOS (Apple Silicon) — quick install

Downloads the latest DMG, installs to `/Applications`, handles Gatekeeper automatically. No dev tools needed.

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

### Updating

Rerun the same `curl` command — the installers replace the old version in place. The app also self-updates on launch when a signed update manifest is published.

### Full docs

See the project [README](https://github.com/alfdav/music-dl/blob/master/README.md) for dev setup, Docker Compose, Discord bot onboarding, and the `uv tool install` path.
