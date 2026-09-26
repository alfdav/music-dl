# Contributing to music-dl

## Getting Started

```shell
git clone git@github.com:alfdav/music-dl.git
cd music-dl/tidaldl-py
uv sync
uv run music-dl gui   # launches at http://localhost:8765
```

## Branch Conventions

- `master` — stable, release-ready
- `feat/*` — new features
- `fix/*` — bug fixes
- `docs/*` — documentation only

Create a branch, make your changes, open a PR against `master`.

## Repository Privacy Gate

Enable the tracked Git hooks once per clone:

```shell
git config core.hooksPath .githooks
```

The commit hook checks staged paths. The push hook checks each outgoing commit,
including commits created with `git commit --no-verify`. A required CI check
scans the complete tracked tree before changes can merge into `master`.

Local hooks can still be deliberately bypassed with `git push --no-verify`.
Do not use that option; protected-branch CI is the final merge gate.

## Pull Request Process

1. One logical change per PR. Split unrelated work into separate PRs.
2. Write a clear title: `fix: ...`, `feat: ...`, `docs: ...`, `security: ...`
3. The PR description should explain *what* and *why*. Code explains *how*.
4. Review the final `qa` summary:
   - 90–100: ready
   - 80–89: ready with visible debt
   - Below 80: blocked
   - Any hard blocker or missing required check: blocked
5. If you touch the GUI, test in a browser. If you touch Docker, build and run the image.

The `qa` workflow is enforcing. Check steps still use `continue-on-error` so
every result is gathered, but the final `qa` job fails on a hard blocker, a
missing required check, or a score under 80. Ruff stays a score deduction,
not a hard fail. The owner should make `qa / qa` a required status check on
`master` in branch protection.

## Code Conventions

### Python

- **Python 3.12 or 3.13** — use modern syntax (`match`, `type X = ...`, `|` unions)
- **uv** over pip — always
- **No frameworks for the frontend** — vanilla JS split across `api.js`, `views.js`, `player.js`, and `routes.js`
- **Shared configuration** — `Settings()` and `Tidal()` are singletons; each `LibraryDB()` instance owns its connection
- **Path validation** — any endpoint that touches the filesystem must use `validate_audio_path()` or equivalent

### Frontend

- **bun** over npm — always
- **No build step** — split JavaScript, `style.css`, and `index.html` are served directly
- **No Web Audio API** — the `<audio>` element plays files from source, untouched. Quality is non-negotiable.
- **CSS variables** for theming — keep the tracked [design system](tidaldl-py/docs/design-system.md) and `style.css` aligned

### Packaging

- Stable release metadata must be changed through `scripts/release_version.py`
- Static assets must be listed in `[tool.setuptools.package-data]` or Docker breaks
- Test with `docker build -f docker/Dockerfile -t music-dl .` before merging packaging changes

## Running Tests

```shell
# Quick smoke
cd tidaldl-py
uv run --extra test pytest tests/test_gui_api.py tests/test_gui_security.py -q

# Full suite
uv run --extra test pytest

# Release smoke (from repo root)
uv run --project tidaldl-py --extra test pytest \
  tidaldl-py/tests/test_gui_command.py \
  tidaldl-py/tests/test_gui_api.py \
  tidaldl-py/tests/test_setup.py \
  tidaldl-py/tests/test_token_refresh.py \
  tidaldl-py/tests/test_public_branding.py \
  tidaldl-py/tests/test_packaging.py
```

Discord bot checks:

```shell
cd apps/discord-bot
bun test
bun run typecheck
```

## Releasing Desktop Binaries

1. Land the release changes through a PR against `master`.
2. Write a real PR title/body — the tag workflow turns merged PRs into GitHub release notes and updater notes.
3. Before tagging, confirm updater signing secrets exist:
   - `TAURI_SIGNING_PRIVATE_KEY`
   - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
4. After the PR merges, push an annotated tag like `v1.6.0`.
5. GitHub Actions runs `.github/workflows/build-desktop.yml`, uploads Linux, macOS, and Windows binaries, updates `latest.json`, and writes release notes onto the GitHub release.
6. Confirm the Windows MSI assets are present when the release should support Windows 10/11:
   - Windows assets are uploaded: `.msi`, `.msi.sig`
   - The MSI is unsigned, so SmartScreen warnings are expected.
   - WSL is not required to install or run the desktop app.
7. Sanity-check the release before announcing it:
   - release notes are present
   - Linux assets are uploaded: `.AppImage`, `.AppImage.sig`, `.deb`
   - macOS assets are uploaded: `.dmg`, `.app.tar.gz`, `.app.tar.gz.sig`
   - the macOS CI bundle-integrity check passed (ad-hoc signature, not Apple notarization)
   - Windows assets are uploaded: `.msi`, `.msi.sig`
   - `latest.json` points at the new tag
   - `latest.json` contains `linux-x86_64`, `darwin-aarch64`, and `windows-x86_64`
8. Smoke-test Windows before announcing Windows support:
   - Install the MSI.
   - Launch `music-dl`.
   - Complete or recover Tidal authentication.
   - Choose a local library/download path.
   - Search for one track.
   - Download one track.
   - Play that track.
   - Quit and reopen the app.
   - Confirm settings, auth, and library state persist.

Blank release notes are a release bug.

macOS DMGs and updater archives are built and attached by GitHub Actions. CI applies and verifies an ad-hoc macOS bundle signature with hardened runtime disabled so the bundled PyInstaller runtime remains loadable; the app is not Apple Developer ID signed or notarized. Windows MSIs are unsigned, so SmartScreen warnings are expected.

Prepare stable release metadata from the repository root:

```shell
uv run --project tidaldl-py python scripts/release_version.py bump patch
```

Use `bump minor`, `bump major`, or `set X.Y.Z` when needed. The helper updates Python, Tauri, Rust, changelog, and lockfile version state together, rejects non-SemVer stable versions, and requires an `## Unreleased` changelog section before writing files.

## Security

- Server binds `127.0.0.1` by default. `0.0.0.0` only via `MUSIC_DL_BIND_ALL=1`.
- CSRF token required for POST/PATCH/PUT/DELETE.
- Path traversal is blocked: `resolve(strict=True)` + `is_relative_to()` + extension whitelist.
- Never hardcode secrets. Never log tokens.
- Docker runs as non-root (UID 1000).

## Architecture

See [backend-guide.md](tidaldl-py/docs/backend-guide.md) for the full architecture, API routes, DB schema, and download pipeline.

## Questions?

Open an [issue](https://github.com/alfdav/music-dl/issues). Use the templates. For bugs, follow the [bug reporting guide](docs/bug-reporting.md) so reports include version, platform, install path, local state, logs, and reproduction steps.
