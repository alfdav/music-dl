# Contributing to music-dl

## Getting Started

```shell
git clone git@github.com:alfdav/music-dl.git
cd music-dl/tidaldl-py
uv sync
music-dl gui          # launches at http://localhost:8765
```

## Branch Conventions

- `master` — stable, release-ready
- `feat/*` — new features
- `fix/*` — bug fixes
- `docs/*` — documentation only

Create a branch, make your changes, open a PR against `master`.

## Pull Request Process

1. One logical change per PR. Split unrelated work into separate PRs.
2. Write a clear title: `fix: ...`, `feat: ...`, `docs: ...`, `security: ...`
3. The PR description should explain *what* and *why*. Code explains *how*.
4. CI must pass (gui-smoke tests run automatically on PRs).
5. If you touch the GUI, test in a browser. If you touch Docker, build and run the image.

## Code Conventions

### Python

- **Python 3.12+** — use modern syntax (`match`, `type X = ...`, `|` unions)
- **uv** over pip — always
- **No frameworks for the frontend** — vanilla JS, single `app.js` file
- **Singletons** — `Settings()`, `Tidal()`, `LibraryDB()` are shared across CLI and GUI
- **Path validation** — any endpoint that touches the filesystem must use `validate_audio_path()` or equivalent

### Frontend

- **bun** over npm — always
- **No build step** — `app.js`, `style.css`, and `index.html` are served directly
- **No Web Audio API** — the `<audio>` element plays files from source, untouched. Quality is non-negotiable.
- **CSS variables** for theming — see [design-system.md](tidaldl-py/docs/design-system.md)

### Packaging

- `pyproject.toml` is the single source of truth
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
4. After the PR merges, push an annotated tag like `v1.4.2`.
5. GitHub Actions runs `.github/workflows/build-desktop.yml`, uploads Linux binaries, updates `latest.json`, and writes release notes onto the GitHub release.
6. Sanity-check the release before announcing it:
   - release notes are present
   - expected Linux assets are uploaded
   - `latest.json` points at the new tag
   - `latest.json` only contains `linux-x86_64`

Blank release notes are a release bug.

macOS desktop usage is manual/local-build only. Build with Tauri locally and replace the app bundle yourself when you want to update.

## Security

- Server binds `127.0.0.1` by default. `0.0.0.0` only via `MUSIC_DL_BIND_ALL=1`.
- CSRF token required for POST/PUT/DELETE.
- Path traversal is blocked: `resolve(strict=True)` + `is_relative_to()` + extension whitelist.
- Never hardcode secrets. Never log tokens.
- Docker runs as non-root (UID 1000).

## Architecture

See [backend-guide.md](tidaldl-py/docs/backend-guide.md) for the full architecture, API routes, DB schema, and download pipeline.

## Questions?

Open an [issue](https://github.com/alfdav/music-dl/issues). Use the templates.
