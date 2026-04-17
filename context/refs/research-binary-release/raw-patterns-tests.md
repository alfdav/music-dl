## Agent: codebase-patterns-tests

### 1. Coding Conventions

- Finding: Singleton pattern via `SingletonMeta` on `Settings`, `Tidal`, `HandlingApp`. `StrEnum` for constants. Protocol-based duck typing for loggers.
- Evidence: `tidal_dl/helper/decorator.py`, `tidal_dl/constants.py`, `tidal_dl/download.py:180`
- Implication: Singleton clearing required in test fixtures. `conftest.py` provides `clear_singletons` but autouse=False — tests must opt in.
- Confidence: HIGH

- Finding: snake_case functions, PascalCase classes, `_` prefix for private/module-level state. Type annotations pervasive. Python 3.12+ required.
- Evidence: `pyproject.toml:7` — `requires-python = ">=3.12,<3.14"`
- Implication: Binary must target Python 3.12+. `StrEnum`, `match`, `type X | Y` syntax used freely.
- Confidence: HIGH

- Finding: `dataclasses_json` for config serialization, `pydantic BaseModel` for FastAPI request/response. Two coexisting serialization layers.
- Evidence: `tidal_dl/model/cfg.py` uses `@dataclass_json @dataclass`. FastAPI routes use `BaseModel`.
- Confidence: HIGH

### 2. Known Issues/Bugs

- Finding: Two TODOs in `download.py` — video client string (line 152), pathlib consistency (line 189).
- Evidence: `tidal_dl/download.py:152,189`
- Implication: Not crash-level for macOS but incomplete work.
- Confidence: HIGH

- Finding: `tidalapi` has no `Quality.hi_res` member — `HI_RES` silently maps to `hi_res_lossless`.
- Evidence: `tidal_dl/constants.py:69`
- Implication: If tidalapi adds distinct `hi_res`, quality selection breaks silently.
- Confidence: HIGH

- Finding: `assert db._conn` used as runtime guard in production code — 10+ occurrences across API handlers.
- Evidence: `downloads.py:368`, `library.py:234,737`, `duplicates.py:144,167`, `upgrade.py:404`, `library_db.py:277+`
- Implication: Safe with PyInstaller default optimize=0, but fragile. Python `-O` would strip asserts → NPE.
- Confidence: HIGH

- Finding: `_login_state` dict in `settings.py` mutated from request handlers AND background thread without lock.
- Evidence: `tidal_dl/gui/api/settings.py:156-200`
- Implication: Race condition. GIL mitigates catastrophic failure but `_login_state.update(...)` with multiple keys not atomic. Visible as stale status reads.
- Confidence: MEDIUM

- Finding: CSP is null in `tauri.conf.json`.
- Evidence: `src-tauri/tauri.conf.json:26`
- Implication: No Content Security Policy in Tauri webview — security gap for release binary.
- Confidence: MEDIUM

### 3. Test Infrastructure

- Finding: pytest with httpx-backed FastAPI `TestClient`. No coverage tool configured. No CI config found.
- Evidence: `pyproject.toml:63-75`, no `.github/workflows/` directory.
- Implication: No coverage measurement. CI status unknown.
- Confidence: HIGH

- Finding: Shared `client` fixture with CSRF token extraction and host header injection.
- Evidence: `tests/conftest.py:19-29`
- Implication: Robust end-to-end API test fixture.
- Confidence: HIGH

- Finding: 30 test files, 403 test functions total.
- Confidence: HIGH

### 4. Test Coverage Map

**Well-tested:**
- GUI API surface (downloads, library, home, settings, setup, search, duplicates, upgrade, playlists)
- Security layer (path validation, stream URL validation, host validation, CSRF)
- Config loading with 3-tier recovery
- Static asset resolution (normal + frozen modes)

**UNTESTED (zero coverage):**
- `tidal_dl/helper/waveform.py` — ffmpeg subprocess, PCM decoding
- `tidal_dl/helper/library_scanner.py` — background library scan
- `tidal_dl/helper/wrapper.py` — LoggerWrapped
- `tidal_dl/metadata.py` — mutagen tag writing (MP3, FLAC, M4A)
- `tidal_dl/dash.py` — DASH manifest parsing
- `tidal_dl/gui/api/playback.py` — Python endpoint untested
- `tidal_dl/model/downloader.py`, `tidal_dl/model/meta.py` — data containers

Implication: Critical paths with NO tests: waveform, metadata tagging, library scanning, DASH parsing. Regressions would be silent.
Confidence: HIGH

### 5. Error Handling Patterns

- Finding: Pervasive `except Exception: pass` — 40+ occurrences. Intentional "never crash GUI" design.
- Evidence: `downloads.py:48`, `home.py:121,134,264,282,289`, `gui/__init__.py:37-38`, `library.py:65-66,469-470,663-664`, `search.py:42-43,124-125,135-136`
- Implication: Makes debugging hard. Silent failures appear as blank/hanging UI. No logged errors to trace.
- Confidence: HIGH

- Finding: Download pipeline uses structured retry — 3 retries, exponential backoff (2/4/8s), distinguishes retryable vs permanent errors.
- Evidence: `downloads.py:168-216`
- Implication: Well-structured. SSE broadcasts retry state.
- Confidence: HIGH

- Finding: Config loading has 3-tier recovery: exact → tolerant merge → backup restore.
- Evidence: `tidal_dl/config.py:135-234`
- Implication: Robust for real-world config drift across versions.
- Confidence: HIGH

### 6. GUI State Management

- Finding: Vanilla JS SPA, single global `state` object, 6952 lines, no framework/reactivity.
- Evidence: `app.js:148-162`
- Implication: All mutations synchronous imperative. State drift possible with async callbacks.
- Confidence: HIGH

- Finding: CSRF token embedded in meta tag, auto-refreshed on 403 with dedup promise.
- Evidence: `app.js:8,11-31`
- Implication: Correct implementation, tested.
- Confidence: HIGH

- Finding: `innerHTML` used ONLY for static SVG icons, never user data. `textContent`/`textEl()` for user data.
- Implication: No XSS surface. Release-safe.
- Confidence: HIGH

### 7. Dead Code / Stale State

- Finding: `_db` and `_db_opened_at` module-level vars in `library.py` and `home.py` labelled "Compatibility alias for tests/debugging" — not used by production path (which uses `threading.local()` via `_db_local`).
- Evidence: `library.py:49-50`, `home.py:18`
- Implication: Potentially misleading but not dead code.
- Confidence: HIGH

- Finding: `_playlist_tracks_cache` in `playlists.py` grows unboundedly — old playlist IDs never evicted, only TTL-replaced.
- Evidence: `playlists.py:19-21`
- Implication: Memory leak for long-running sessions with many playlists.
- Confidence: MEDIUM

### Release Readiness Risks

1. No test coverage for waveform, metadata, library scanner, DASH
2. Two TODOs in download.py (video client, pathlib)
3. _login_state race condition in settings.py
4. assert db._conn in production handlers — fragile
5. CSP null in tauri.conf.json
6. Unbounded playlist cache
7. Build infra solid: PyInstaller spec, sidecar entry, Tauri readiness check, build-time JS verification all exist
