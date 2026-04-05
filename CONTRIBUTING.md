# Contributing to music-dl

## Getting Started

```shell
git clone git@github.com:alfdav/music-dl.git
cd music-dl/TIDALDL-PY
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
- **CSS variables** for theming — see [design-system.md](TIDALDL-PY/docs/design-system.md)

### Packaging

- `pyproject.toml` is the single source of truth
- Static assets must be listed in `[tool.setuptools.package-data]` or Docker breaks
- Test with `docker build -f docker/Dockerfile -t music-dl .` before merging packaging changes

## Running Tests

```shell
# Quick smoke
cd TIDALDL-PY
uv run pytest tests/test_gui_api.py tests/test_gui_security.py -q

# Full suite
uv run pytest

# Release smoke (from repo root)
uv run --project TIDALDL-PY pytest \
  TIDALDL-PY/tests/test_gui_command.py \
  TIDALDL-PY/tests/test_gui_api.py \
  TIDALDL-PY/tests/test_setup.py \
  TIDALDL-PY/tests/test_token_refresh.py \
  TIDALDL-PY/tests/test_public_branding.py \
  TIDALDL-PY/tests/test_packaging.py
```

## Security

- Server binds `127.0.0.1` by default. `0.0.0.0` only via `MUSIC_DL_BIND_ALL=1`.
- CSRF token required for POST/PUT/DELETE.
- Path traversal is blocked: `resolve(strict=True)` + `is_relative_to()` + extension whitelist.
- Never hardcode secrets. Never log tokens.
- Docker runs as non-root (UID 1000).

## Architecture

See [backend-guide.md](TIDALDL-PY/docs/backend-guide.md) for the full architecture, API routes, DB schema, and download pipeline.

## Questions?

Open an [issue](https://github.com/alfdav/music-dl/issues). Use the templates.
