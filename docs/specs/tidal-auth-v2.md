# Tidal login v2 — audit and design

**Status:** design spec only. This pull request does not change auth code, bump a version, or ship a binary.

**Audience:** the first two sections are for anyone. The rest is for the person who implements this.

---

## Plain summary

Today, music-dl keeps your Tidal login in a plain text file called `token.json` on disk. Most of the time the app reuses that file when you update, restart, or get a 401. That is the right idea.

The danger is not "we log in too often on purpose." The danger is a handful of crash, refresh, and UI paths that can **destroy the saved login** or **start a brand-new Tidal device login without the user meaning to**. Tidal treats each new device-code login as another seat. Too many seats is what the owner is worried will get the account banned.

What a user sees today is also thin: a sidebar chip, a "Connect to Tidal" popup with a code, and a Reset button whose warning does not mention extra devices.

v2 keeps the standing law — **one Tidal login per machine** — and makes it harder to break:

1. Put the token in the OS keychain (with a safe encrypted-file fallback).
2. Write the file so a crash cannot truncate it.
3. On 401: refresh once, retry once, then show "session needs attention." Never auto-start login.
4. Give the user a real login screen and a real account panel, with Reset behind a two-step warning that this device will become a new Tidal seat on the next login.
5. Lock the local HTTP API so a website or another program cannot drive login or reset.

Nothing in this spec asks anyone to log in again just to migrate. The existing `token.json` is copied once, with a backup, and the session stays alive.

---

## Standing laws

These are not negotiable. Every v2 task must keep them.

1. **One Tidal login per machine**, unless the user explicitly taps Reset / Sign out, or Tidal itself revokes the refresh token.
2. **Updates, sidecar restarts, and 401s refresh the token.** They never start a new device-code / OAuth flow.
3. **Never wipe or overwrite `token.json`** (or its v2 keychain / encrypted-file equivalent) except on an explicit user Reset / Sign out.
4. **Do not create extra Tidal device sessions.** Extra seats are the ban risk.

---

## How login works today

This is the map the findings refer to. Paths are from the repo root. Line numbers are as of `master` at the time of this audit.

### Where the token lives

| OS | Default path |
| --- | --- |
| Linux | `~/.config/music-dl/token.json`, or `$XDG_CONFIG_HOME/music-dl/token.json` if that env var is set |
| macOS | `~/.config/music-dl/token.json` (XDG-style, **not** `~/Library/Application Support`) |
| Windows | `%HOMEDRIVE%%HOMEPATH%\.config\music-dl\token.json` (typically `C:\Users\<name>\.config\music-dl\token.json`, **not** `%APPDATA%`) |
| Override | `$MUSIC_DL_CONFIG_DIR/token.json` on every OS |

Source: `tidaldl-py/tidal_dl/helper/path.py:73-121`, locked by `tidaldl-py/tests/test_public_branding.py:12-76`.

If `~/.config/music-dl` does not exist and `~/.config/tidal-dl` does, the whole legacy folder is moved (`path.py:91-100`). That can move a token. If `music-dl` already exists, the legacy folder is left behind and its token is ignored.

The file is a JSON object with `token_type`, `access_token`, `refresh_token`, `expiry_time`, and `account_quality` (`tidaldl-py/tidal_dl/model/cfg.py:237-242`). Those fields are **plaintext**. There is no keychain, no encryption, and no Windows Credential Manager.

After a successful `token_persist()`, the process tries `chmod 0o600` (`tidaldl-py/tidal_dl/config.py:545-546`). Other writes go through `BaseConfig.save()` (`config.py:92-106`), which does **not** set permissions. A brand-new file created by `read()` → `save()` follows the process umask (often world-readable `0644` until the next persist).

### The happy path (one seat)

1. User taps **Log in to Tidal** / **Connect Tidal**. The UI `POST`s `/api/auth/login`.
2. The server tries to refresh any saved refresh token first (`tidaldl-py/tidal_dl/gui/api/settings.py:508-526`). If that works, it returns `already_logged_in` and no new Tidal device is created.
3. Only if there is **no** refresh token, or Tidal **rejects** the refresh, does the server call `session.login_oauth()` (`settings.py:528-560`). That is a new device-code seat.
4. The UI shows the code and opens the browser (`tidaldl-py/tidal_dl/gui/static/player.js:1927-1993`).
5. Tokens are written to `token.json` via `login_finalize()` → `token_persist()` (`config.py:519-543`).
6. Later, sidecar start, a 30-minute keepalive thread, `TokenRefreshMiddleware`, `GET /auth/status`, and `call_tidal` on 401 all try to **refresh**, not log in again. Sidecar start uses `allow_interactive_login=False` (`tidaldl-py/tidal_dl/gui/__init__.py:69-90`). A Tauri update is tested to leave `token.json` alone (`tidaldl-py/tests/test_gui_lifespan.py:182-247`).

### What the user sees

| Moment | What they see |
| --- | --- |
| Not logged in | Sidebar chip: gray dot + "log in". Settings: "Log in to Tidal". Search: "Connect Tidal to search, stream, and download". Setup wizard: secondary "Connect Tidal" button. |
| Logging in | Modal title "Connect to Tidal", the user code (click to copy), the verification URL, a spinner "Waiting for you to confirm in browser...". Sidebar becomes "tidal · waiting...". No countdown. No cancel that stops the server. Clicking the dimmed backdrop only hides the modal. Copy does **not** say this adds a device to the Tidal account. (`player.js:1927-1964`, `1971-2030`) |
| Signed in | Sidebar: green dot + username, or just "connected" if the name is empty. Settings: same, plus a quality badge (Hi-Res / Lossless) if `account_quality` is cached. No plan. No last-refresh time. No device / seat name. |
| Session expired | Banner: "Tidal session expired." + **Re-connect**. Chip: "connection expired". (`player.js:42-45`, `2551-2563`) |
| Transient refresh failure | Toast: "Tidal session could not be refreshed. Try again in a moment." if `/auth/login` returns `expired`. (`player.js:1979-1982`) |
| 401 on download/search | Toast: "Tidal login required — opening sign-in…" and the UI **starts login by itself**. (`tidaldl-py/tidal_dl/gui/static/api.js:489-496`) |
| Reset | Button "Reset Tidal connection" on connected / expired / unavailable. Confirm: "Reset the saved Tidal connection? You will need to log in again." One **Continue** click. No typed confirm. No mention of a new Tidal device / seat. (`tidaldl-py/tidal_dl/gui/static/views.js:5351-5407`) |

The user cannot tell **which Tidal device or seat** this machine is. The API never returns a device id.

---

## Findings

Each finding cites `file:line` on current `master` and a concrete scenario. Severity is the combination of "can we lose the only seat or mint a new one" and "can someone else touch the session."

### Critical

#### C1. A crash while writing `token.json` can destroy the only seat

`BaseConfig.save()` opens the real file with `"w"`, which truncates it immediately, then dumps JSON (`tidaldl-py/tidal_dl/config.py:92-106`). There is no temp file, no `fsync`, no `rename`. `token_persist()` and `refresh_account_quality()` both call that save (`config.py:533-543`, `548-564`). `Tidal.__init__` also `read()`s then `save()`s the same file on every process start (`config.py:124-151`, `247-259`).

The bot already knows the safe pattern — temp file, `fsync`, `os.replace` — and uses it for the Discord shared secret (`tidaldl-py/tidal_dl/gui/api/bot_control.py:576-586`). Tokens do not.

**Scenario:** Tidal rotates the refresh token. `token_persist()` truncates `token.json`. The sidecar is killed mid-write (update restart, crash, power loss). The file is empty or half-written. Next start, `read()` hits `JSONDecodeError` and `_recover_from_corrupt()` (`config.py:160-184`) **deletes any existing `token.json.bak`**, moves the truncated file onto `.bak`, fails to parse it, and writes a default empty `Token`. The refresh token that Tidal just issued exists only in the truncated backup. The UI shows `not_configured`. The next Connect Tidal creates a **new device session**. If Tidal invalidated the old refresh token on rotation, the old seat is also dead.

#### C2. A 401 can auto-start a new device-code login

Backend `call_tidal` refreshes once and does not call `login_oauth` (`settings.py:357-380`). That part is correct.

The UI does not stay in that contract. `apiTidal()` treats `401 Not logged in to Tidal` as "open sign-in" and calls `triggerLogin()` (`api.js:489-496`). `triggerLogin()` `POST`s `/auth/login`. If the refresh token is missing **or Tidal rejected it**, `auth_login` calls `session.login_oauth()` (`settings.py:522-540`). A current test **requires** that rejected-refresh path to start OAuth (`tidaldl-py/tests/test_gui_auth_login.py:93-128`, `401-441`).

**Scenario:** Overnight Tidal revokes the refresh token, or a 401 storm hits while refresh is already rejected. The user clicks Download on a search row. They never tapped Connect Tidal. A new device-code seat is created in the background, the modal pops, and Tidal now sees another device on the account.

### High

#### H1. Tokens sit on disk in plaintext

`token.json` is JSON text with live `access_token` and `refresh_token` (`model/cfg.py:237-242`, `config.py:536-538`). Permissions are `0600` only after `token_persist`. First create and corrupt-recovery writes use the umask.

**Scenario:** A sync tool, Time Machine / File History, a NAS backup of the home folder, or malware that can read the user profile copies `~/.config/music-dl/token.json`. That file is enough to use the Tidal account from another machine — another seat from Tidal's point of view.

#### H2. Two processes share the file with only an in-process lock

`_token_fresh_lock` is a module `RLock` (`config.py:48`, `569-592`). It serializes refresh inside one Python process. The CLI (`music-dl dl`, `music-dl login`) and the GUI sidecar are different processes. They both read and write the same path (`path_file_token()`). There is no `fcntl` / Windows file lock.

**Scenario:** The desktop app is playing. The user also runs `music-dl dl <url>` in a terminal. Both refresh at once. One persist wins, the other overwrites with a stale refresh token. If Tidal rotated, the overwritten token is already invalid. Next restart looks expired and the user is pushed toward a new login.

#### H3. CLI download can start an interactive device-code flow

GUI startup passes `allow_interactive_login=False` (`gui/__init__.py:76-78`). CLI `_resolve_session()` does not (`tidaldl-py/tidal_dl/cli.py:458-476`). `resolve_source()` defaults `allow_interactive_login=True` and calls `login()` (`config.py:297-342`). `login()` starts `login_oauth()` when there is no refresh token (`config.py:675-684`). That path is used by download, favorites, playlist import, ISRC tagging, and sync (`cli.py:323`, `821`, `898`, `1139`; `tidaldl-py/tidal_dl/cli_sync.py:123`).

**Scenario:** `token.json` was emptied by C1. The user only wanted to download a URL they already had. The CLI opens a browser and adds a device.

#### H4. `login_token(..., delete_on_failure=True)` can still unlink the file

The last key-rotation attempt sets `delete_on_failure=not quiet` (`config.py:415-420`). Unlink runs only when restore failed **and** there is no `refresh_token` (`config.py:475-481`). Tests lock the "do not delete while a refresh token remains" case (`tidaldl-py/tests/test_token_refresh.py:302-316`).

**Scenario:** Corrupt recovery already blanked `refresh_token` (C1). CLI `music-dl login` then exhausts API keys and deletes the file. Harmless if empty; harmful if a human-readable leftover or a second writer had just put a token back.

#### H5. Any local program can reset or start login

CSRF is a random token embedded in `index.html` (`gui/__init__.py:168-219`). The frontend will `GET /` and scrape it (`api.js:11-18`). There is **no per-launch secret** from the Tauri shell. `GET` is CSRF-exempt (`security.py:109-117`). So any process on the machine can: read `/`, take the CSRF token, `POST /api/auth/reset` (deletes `token.json`, `settings.py:595-608`) or `POST /api/auth/login` (may start device-code).

**Scenario:** A browser page cannot easily *read* cross-origin responses (CORS is tight). A helper script, another local app, or an extension that can hit `http://127.0.0.1:8765/` can. One POST wipes the only seat. The next UI login is a new Tidal device.

#### H6. Reset does not explain the seat risk

`logout()` deletes `token.json` and replaces the session (`config.py:760-788`). The UI confirm is one sentence (`views.js:5402-5406`). CLI `music-dl logout` prints success with no warning (`cli.py:587-599`). `music-dl cfg --reset` only touches `settings.json` (`cli.py:410-425`) — good — but a user who hears "reset" may hit the Tidal Reset button instead.

**Scenario:** Playback looks broken (H8 / expired banner). The user taps Reset, Continue, then Log in. They thought they were "refreshing the connection." They created a second Tidal device. The old refresh token is gone locally; if Tidal still has the old device listed, they now have two.

#### H7. Host check is weaker than its comment, and Docker binds all interfaces

`HostValidationMiddleware` claims an exact match (`security.py:78-84`) but also allows any `Host` whose name is `localhost` or `127.0.0.1` **regardless of port** (`security.py:91-95`). The backend guide documents that (`tidaldl-py/docs/backend-guide.md:183-186`). Tests do not cover `Host: localhost:9`.

Default bind is `127.0.0.1` (`daemon.py:21`, `server.py:56-58`, sidecar `make_uvicorn_config` without `bind_all`). Docker sets `MUSIC_DL_BIND_ALL=1` and listens on `0.0.0.0` (`docker/Dockerfile` `ENV MUSIC_DL_BIND_ALL=1`, `server.py:56-70`, `daemon.py:195-198`).

**Scenario:** On a NAS/Docker install, anything on the LAN can open port 8765. A request with `Host: 127.0.0.1:8765` (easy with curl) passes the Host check. Combined with H5, a roommate or a compromised device on the same LAN can reset Tidal or start a device-code login. Desktop-without-Docker stays loopback-only; this is the bind-all case.

#### H8. 401 storm: toast spam and repeated `/auth/login` while a refresh token still exists

If `/auth/login` returns `expired` (refresh token present, not rejected), `triggerLogin()` toasts and returns **without** setting `_loginPoll` (`player.js:1979-1982`). `apiTidal` only suppresses auto-login while `_loginPoll` is set (`api.js:493`).

**Scenario:** Tidal is briefly down. Ten download 401s fire. Each one toasts "Tidal login required — opening sign-in…" and POSTs `/auth/login`. The backend mostly returns `expired` (good — no OAuth). The user sees a flood of "please log in" and may hit Reset (H6).

### Medium

#### M1. Device-code modal is incomplete

No countdown despite `expires_in` (`settings.py:551-552`, `player.js:1927-1964`). No Cancel that stops `_wait_for_login` (5 minute `future.result`, `settings.py:477-498`). Dismissing the overlay leaves the server still waiting. No sentence that this **adds this device** to the Tidal account.

**Scenario:** User closes the modal, thinks they cancelled, then later completes an old Tidal page. A seat is added they did not mean to finish. Or the code expires and they only see a later timeout toast.

#### M2. Account panel cannot tell you who or what is signed in

`GET /auth/status` returns `logged_in`, `username`, `auth_state`, `account_quality` (`settings.py:414-425`, `436-464`). Username is `session.user.name` and is often `""` after a silent restore (the update-revive test expects an empty username: `test_gui_lifespan.py:233-238`). There is no plan name, no last-refresh timestamp, no device label.

**Scenario:** Two family members share a Mac. The chip says "connected." Nobody can see which Tidal account or which seat it is before they download.

#### M3. `GET /auth/status` has a side effect, and `GET /auth/login/status` exposes the device code

Status revive calls Tidal when the access token is missing or expired (`settings.py:447-450`). Login status is a CSRF-exempt GET that returns `user_code` and `verification_uri` while pending (`settings.py:576-580`, `547-553`). CORS blocks a foreign website from *reading* the response if the browser enforces it (`gui/__init__.py:174-178`). The request still runs. A local caller can read the code.

**Scenario:** During login, another local process polls `/auth/login/status` and races the user to submit the code. Unlikely on a single-user desktop; relevant on a shared NAS GUI.

#### M4. Swagger and a null Tauri CSP widen the local attack surface

FastAPI serves `/api/docs` (`gui/__init__.py:161`). Tauri `csp` is `null` (`tidaldl-py/src-tauri/tauri.conf.json:25-27`). The loopback capability grants updater and sidecar commands to `http://127.0.0.1:*` (`tidaldl-py/src-tauri/capabilities/loopback.json:6-19`).

**Scenario:** An XSS in the GUI (user-controlled metadata is generally `textContent`, `api.js:1-4`, but CSP-null means one slip is enough) can call Tauri `install_update` / `stop-sidecar` and the auth API. Not a token leak by itself; it is how H5 gets into the desktop webview.

#### M5. Tokens and login URLs are not systematically redacted

No auth log redactor exists. `auth_login` can raise `Login failed: {exc}` (`settings.py:554-556`). `login_token` prints a credentials-or-server message on exception (`config.py:465-469`) without dumping the token — good. Bug-report docs tell humans not to paste tokens (`docs/bug-reporting.md:9`) and to list config **file names**, not contents (`docs/bug-reporting.md:37-53`). There is no crash-bundle builder, so there is also no automated strip of `token.json`. The frontend never puts tokens in the DOM (no `access_token` / `refresh_token` in `gui/static`).

**Scenario:** A user attaches a full `~/.config/music-dl` zip to a GitHub issue, or a debug log includes an exception string with a verification URL. The refresh token or a live login code is now public.

#### M6. Legacy folder move can hide the real token

If `shutil.move` of `tidal-dl` → `music-dl` fails, the app creates an empty `music-dl` dir and continues (`path.py:93-100`). The token stays in `tidal-dl`. New logins write a second `token.json` under `music-dl`.

**Scenario:** Permissions on the old folder block the move. User is asked to log in again. Two files, two possible seats if they complete login.

#### M7. `TokenRefreshMiddleware` runs on almost every `/api/` call and swallows errors

It calls `_ensure_token_fresh()` on a worker thread, except playback / settings / setup / scan / queue (`gui/__init__.py:183-204`). Failures are `pass`. `/api/auth` is **not** skipped, so status and login also refresh first.

**Scenario:** A slow refresh holds `_token_fresh_lock` while downloads also refresh. Playback was correctly excluded so the player does not freeze; search/download still serialize on that lock. A swallowed error then becomes a route 401, which is how C2 starts.

### Low

#### L1. Empty username and "connected" vs "credentials_ready"

A saved unexpired token is shown as connected (`player.js:49-50`). That is intentional (`MISTAKES.md` 2026-08-15 credentials_ready). The missing name still makes the chip feel anonymous (M2).

#### L2. IPv6 loopback is not in the Host allow-list

`[::1]:8765` is rejected. Unlikely on this app because the daemon advertises `127.0.0.1` (`daemon.py:21-56`).

#### L3. Overlay click looks like cancel

Clicking the backdrop calls `_dismissDeviceCodeModal()` only (`player.js:1929-1930`, `1966-1968`). The OAuth wait keeps running (M1).

#### L4. "Re-connect" sounds like the same device

The expired banner button is labeled **Re-connect** (`player.js:2560-2562`). If the refresh token is dead, that label starts a **new** seat (C2 / H6).

---

## What already matches the standing laws

Do not rip these out in v2. They are the reason one-machine login works at all.

- Sidecar restore is silent: `allow_interactive_login=False` (`gui/__init__.py:76-78`).
- `GET /auth/status` revives from `refresh_token` instead of immediately saying "log in" (`settings.py:436-464`).
- `call_tidal` is refresh + one retry, never OAuth, never wipe (`settings.py:357-380`).
- CLI `Tidal.login()` refuses to start OAuth while a refresh token exists (`config.py:675-677`). The GUI `POST /auth/login` path is stricter on a *usable* refresh and **does** start OAuth after a rejected refresh (C2). v2 must make the GUI match the CLI rule: rejected refresh → `needs_attention`, not device-code.
- `login_token(delete_on_failure=True)` will not unlink while a refresh token remains (`config.py:475-481`).
- Keepalive on a 30-minute server thread so a closed UI still persists (`settings.py:175-181`, `gui/__init__.py:103-120`).
- Tauri `install_update` does not mention `token.json` (`tests/test_gui_lifespan.py:241-247`).
- GUI Reset is the only GUI wipe; it does not start OAuth (`settings.py:595-608`).
- Auth JSON responses do not include access or refresh tokens (`settings.py:414-425`).
- Default bind is `127.0.0.1` (`daemon.py:21`). CORS origins are only `http://localhost:{port}` and `http://127.0.0.1:{port}` (`gui/__init__.py:174-178`). Foreign `Host: evil.com` is 403 (`security.py:94-95`).
- Tokens are not stored in the download / music folder (`tests/test_public_branding.py:62-76`).

---

## v2 design

### Goal

Same user, same machine, same Tidal seat across updates, sidecar restarts, and 401s. A new Tidal device-code flow happens only when the user confirms they want this machine added (first run, or after an explicit Sign out / after Tidal revoked the token).

### Auth states the UI may show

| State | Meaning | User action |
| --- | --- | --- |
| `not_configured` | No access token and no refresh token (and nothing in the keychain) | **Connect this device** — the only path that starts device-code |
| `credentials_ready` | Tokens present and usable | Use the app. Account panel shows who. |
| `refreshing` | A single-flight refresh is in progress | Wait. Do not show login. |
| `needs_attention` | Refresh was tried and failed (rejected or still failing after backoff) | Explain. Offer **Try refresh again** and **Sign out of this device**. Never auto-start device-code. |
| `signing_in` | User started device-code and we are waiting | Login screen with code, link, countdown, Cancel |

`expired` as a user-facing word goes away. An expired *access* token with a live refresh token is `refreshing` then `credentials_ready`. Only a dead refresh token becomes `needs_attention`.

### Token storage

**Primary:** OS secret store.

| OS | Store | Item |
| --- | --- | --- |
| macOS | Keychain | service `music-dl`, account `tidal-oauth` |
| Windows | Credential Manager | target `music-dl/tidal-oauth` |
| Linux (desktop) | Secret Service / libsecret | same service/account |

**Fallback:** an encrypted file at the same config dir, e.g. `~/.config/music-dl/token.enc`, when the OS store is missing (headless Linux, Docker, NAS, CI). Encrypt with a key derived from a machine-scoped secret plus a file `token.key` at mode `0600`, or a user keyring password if Secret Service is present but the item APIs fail. The fallback exists so Docker/NAS does not force a re-login.

**Never** store a raw refresh token in settings.json, library.db, daemon.json, logs, or the frontend.

Suggested payload (same fields we have today, plus bookkeeping):

- `token_type`, `access_token`, `refresh_token`, `expiry_time`
- `account_quality`, `username`, `user_id` (for the account panel)
- `last_refresh_at`, `auth_client` (which bundled client id succeeded)
- `storage`: `keychain` | `encrypted_file`

### One-time migration (no re-login)

Run on sidecar/CLI start, before any OAuth:

1. If the keychain / encrypted store already has a refresh token, use it. Do not read `token.json` again except as a last-ditch fallback.
2. If `token.json` has a refresh or access token:
   1. Copy the file to `token.json.bak-migrate-<utc>` (copy, not move).
   2. Write the payload into the OS store (or encrypted file).
   3. Read it back and compare refresh token hashes (SHA-256), not the raw token in logs.
   4. Only then replace `token.json` with a stub `{ "migrated": true, "storage": "keychain" }` using the atomic write below. The stub has **no secrets**.
   5. Leave the `bak-migrate` file until the next successful refresh, then delete it. If anything fails, keep `token.json` as-is and stay on the file backend. **Do not start login.**
3. If both stores are empty → `not_configured`.

This is exactly-once. A second start sees the stub or the keychain item and skips.

### Atomic writes and single-flight refresh

Reuse the bot helper shape (`bot_control.py:576-586`):

1. Write `token.json.tmp-<random>` (or the encrypted file tmp) with `O_EXCL`, mode `0600`.
2. `flush` + `fsync`.
3. `os.replace` onto the real name (atomic on the same volume).
4. `chmod 0o600` again.
5. Best-effort `fsync` of the directory.

Do the same for the migrate backup **before** changing the original.

**Single-flight refresh:**

- Keep the in-process `RLock`.
- Add a file lock beside the token (`token.lock`) so CLI and sidecar cannot refresh at once. Wait up to a few seconds, then treat as "another process is refreshing" and re-read storage instead of starting a second Tidal refresh.
- One Tidal `token_refresh` at a time per machine. On success, persist atomically, then reload the session (`_reload_oauth_session` already exists and must stay OAuth-free: `config.py:485-517`).
- If persist fails after Tidal accepted a rotated refresh token, keep the new token in memory and retry persist. Do not call `login_oauth`. Do not unlink.

`_recover_from_corrupt` must **not** delete a good `.bak` before it has a new one. Copy the current file aside with a timestamp. Never write an empty `Token` over a file that still had a refresh token we failed to parse — leave the broken file and surface `needs_attention`.

`login_token(..., delete_on_failure=True)` in v2 is a no-op for storage. The only wipe is Sign out.

### 401 handling

One shared function, used by search, download, playback, playlists, CLI, and middleware:

1. If access token looks valid, make the call.
2. On 401 or failed `check_login`: single-flight refresh, persist, reload session, **retry the call once**.
3. If refresh is rejected by Tidal → `needs_attention` and HTTP **409** with `auth_state: needs_attention`. Do **not** return `401 Not logged in to Tidal` (that string is what `apiTidal` keys on today).
4. If refresh fails transiently → HTTP **503** + existing 30s backoff (`settings.py:194-208`). After the backoff still failing, keep 503 and `needs_attention`. Still no OAuth.
5. The UI shows the account-panel banner. **Try refresh again** is allowed. **Connect this device** is shown only in `not_configured`, or in `needs_attention` after the user confirms they understand this creates a new Tidal device.

`apiTidal()` must stop calling `triggerLogin()`. `TokenRefreshMiddleware` may stay as a hint, but it must use the same single-flight helper and must not start OAuth. CLI `resolve_source` used by `dl` / sync must pass `allow_interactive_login=False`. Only `music-dl login` and the GUI Connect button start device-code, and only after the rules above.

### Login screen

Replace the current modal with a dedicated screen (Settings and first-run wizard can embed the same component).

Must have:

- Title: **Connect this device to Tidal**
- Plain sentence: **This adds this computer to your Tidal account as a signed-in device. Use one login per machine. Do not repeat this unless you signed out or Tidal ended the session.**
- The device code in a large copyable field, with a Copy button (not click-only).
- A button **Open Tidal in your browser** that uses the Tauri shell / default browser, plus the raw URL for copy.
- A countdown from `expires_in`.
- **Cancel** — increments `_login_generation` (already used, `settings.py:467-498`), drops the waiter, does **not** write tokens, does **not** call logout if a previous session existed.
- After success: account panel, toast "This device is connected to Tidal."

Do not auto-start this screen from a 401, from sidecar start, from an update, or from `GET /auth/status`.

### Account panel

Settings → Tidal account, always visible.

| Field | Source |
| --- | --- |
| Signed-in user | `username` / `user_id` cached at login and after refresh |
| Plan / quality | existing `account_quality` (Hi-Res, Lossless, …) |
| Last refresh | `last_refresh_at`, local time, "a minute ago" + exact timestamp in the tooltip |
| Storage | "Saved in macOS Keychain" / "Saved in an encrypted file on this machine" — never show token material |
| Device | "music-dl on this computer" — we do not get Tidal's device list; say so |

Actions:

- **Sign out of this device** — not "Reset". Two steps: (1) checkbox or typed `sign out`, (2) confirm. Copy: **This removes the saved Tidal login from this computer. The next time you connect, Tidal will treat it as a new device. That can count as another seat. Do this only if you mean to disconnect this machine.**
- Sign out deletes keychain item + encrypted file + leftover `token.json` / backups of tokens. It does not start OAuth.
- Optional later: call Tidal's revoke endpoint if we can do it with the existing token and without opening a new device-code flow. Default for v2: local delete only, unless the owner answers yes (see Open questions).

### Local API hardening

The sidecar stays a local app, not a LAN service.

1. **Bind `127.0.0.1` only** in desktop/Tauri/browser-on-the-same-machine. `MUSIC_DL_BIND_ALL` remains for Docker, but Docker then **requires** the per-launch (or compose) secret; refuse to boot bind-all without it.
2. **Per-launch secret.** Tauri generates a random value, passes it to the sidecar as env (e.g. `MUSIC_DL_UI_SECRET`), and the shell sends header `X-Music-DL-UI: <secret>` on every API call. Sidecar rejects `/api/*` (except `/api/server/health` and static `/`) without it. Rotate every process start. Browser-only `music-dl gui` can print the secret once to the terminal or write it into the served HTML the way CSRF is done today — plus the header, so a foreign site cannot guess it.
3. **Keep CSRF** for cookie-less extra defense. Keep **strict CORS** (current origins only; no `*`, no `allow_credentials` unless we have a reason).
4. **Host check is an exact match** of `localhost:{port}` and `127.0.0.1:{port}` only. Drop the `host_no_port in {localhost, 127.0.0.1}` bypass (`security.py:94`).
5. **Never return tokens, refresh tokens, or raw `token.json` contents.** Status, account, login, login/status stay metadata-only. `user_code` is OK on the login screen response to the UI that started login; do not serve it on a CSRF-exempt GET without the UI secret.
6. Disable `/api/docs` in packaged desktop builds (keep it for dev).
7. Bot routes stay on their own bearer token; they do not receive Tidal tokens.

### Logs and bug reports

- Redact anything that looks like `access_token`, `refresh_token`, `Bearer …`, `user_code`, `verification_uri_complete`, and the contents of `token.json` / `token.enc`.
- Exception handlers must not interpolate raw Tidal responses into HTTP `detail` or `_console.print`.
- Bug-report guide already says not to paste tokens (`docs/bug-reporting.md:9`). Add: do not zip `token.json`, `token.enc`, `token.json.bak*`, or keychain exports. A future "copy debug info" button must run the redactor and omit those files.

---

## Phased rollout

Each phase can ship on its own. **None of phases 0–2 require a new Tidal login** if `token.json` is healthy.

### Phase 0 — no session risk (ship first)

Docs and tests that lock the standing laws. Change **UI copy and 401 behavior only**:

- Stop `apiTidal` from calling `triggerLogin`.
- Rename Reset → Sign out copy (even before two-step).
- Add `needs_attention` as a displayed state mapped from today's `expired` / 503.
- Redact tokens in new log lines.

Old `token.json` is unread except as today. No storage migration.

### Phase 1 — safer file, same file

- Atomic write for `token.json` (the bot helper).
- Timestamped backups before overwrite; stop deleting `.bak` first.
- File lock + single-flight refresh.
- `delete_on_failure` no longer unlinks.
- CLI `dl` / sync use `allow_interactive_login=False`.
- Host exact-match + UI secret header (desktop). Bind stays `127.0.0.1`.

Still one plaintext file. A healthy session is only copied, never replaced with empty defaults.

### Phase 2 — keychain migrate

- OS store + encrypted-file fallback.
- One-time migrate with `bak-migrate` and hash verify.
- Stub `token.json` after success.

If migrate fails, keep using `token.json`. No login prompt.

### Phase 3 — login screen and account panel

- Full device-code screen (countdown, cancel, seat copy).
- Account panel fields and two-step Sign out.
- Disable `/api/docs` in packaged builds.
- Docker bind-all requires the secret.

Phase 3 is UX. It must not change storage rules already shipped in phase 2.

---

## Test plan

Automated tests should fail if a path starts `login_oauth` or unlinks token storage outside Sign out. Extend `tidaldl-py/tests/test_gui_auth_login.py`, `test_token_refresh.py`, and `test_gui_lifespan.py` rather than inventing a second auth stack.

### Simulated access-token expiry

1. Write a token file (or keychain fixture) with `expiry_time` in the past and a live `refresh_token`.
2. Hit `GET /auth/status`, `POST /auth/keepalive`, sidecar lifespan, and a Tidal search.
3. Expect: one `token_refresh`, atomic persist, `credentials_ready`. **Zero** `login_oauth`. **File / keychain still present.**

### 401 storm

1. Mock Tidal to 401 three times, then succeed after one refresh.
2. Fire ten parallel `call_tidal` / `apiTidal` downloads.
3. Expect: one in-flight refresh (lock), each caller retries once, no UI login, no second device-code.
4. Mock refresh **rejected**: HTTP is not `401 Not logged in to Tidal`; UI shows `needs_attention`; `login_oauth` is not called.
5. The current test `test_gui_auth_login_uses_oauth_when_refresh_cannot_repair` must be **rewritten** to assert no OAuth. That is an intentional contract change.

### Crash mid-write

1. Monkeypatch save to truncate the dest file and raise.
2. Expect: original `token.json` (or keychain) still valid; tmp leftover cleaned; state `needs_attention` or retry persist — not `not_configured`.
3. Monkeypatch kill between truncate-and-rename on the **old** saver (until phase 1 lands) to prove today's C1, then prove the atomic saver cannot empty the live file.
4. Corrupt-recovery must not delete a good timestamped backup.

### Update install keeps the session

Already sketched in `test_sidecar_start_after_binary_update_revives_refresh_token_without_oauth` and `test_install_update_does_not_touch_token_json`. Keep both. Add: after phase 2, an update restart migrates or reads the keychain and still does not call `login_oauth`.

### More cases

| Case | Expect |
| --- | --- |
| First run, empty store | Login screen only after the user taps Connect. |
| Cancel during device-code | No persist, no leftover pending generation, store unchanged. |
| Sign out two-step abandoned | Store unchanged. |
| Sign out confirmed | Store empty; next Connect is a new seat; copy warned. |
| CLI `dl` with empty store | Error "Connect Tidal in the app or run music-dl login" — no browser. |
| CLI `dl` with good store while GUI runs | File lock; one refresh; both see the new token. |
| `MUSIC_DL_BIND_ALL` without UI secret | Process refuses to listen on `0.0.0.0`. |
| Request without UI secret | 403, no refresh, no OAuth. |
| `Host: evil.com` or `Host: localhost:9` | 403. |
| `GET /auth/status` from a foreign origin | CORS hides body; no `login_oauth`. |
| Auth response JSON | No `access_token` / `refresh_token` keys. |
| Logs during failed refresh | Redacted; no raw token. |
| Migrate with healthy `token.json` | Keychain filled, stub written, backup exists, no login. |
| Migrate crash after backup, before stub | Next start retries migrate or uses `token.json`; no login. |
| Linux without Secret Service | Encrypted-file fallback; same tests. |

Manual (desktop, once per OS) before calling phase 2 done:

1. Real account, one login.
2. Quit, update or replace the binary, reopen — still signed in.
3. Turn off wifi, play local, turn wifi on — no login modal.
4. Sign out with the two-step, confirm Tidal will need a new device, log in once.

---

## Open questions for the owner

1. **When Tidal has truly revoked the refresh token**, is one user-confirmed "Connect this device" enough, or do you want a support step first (so a flaky Tidal 400 cannot mint a seat)?
2. **Should Sign out also revoke the token at Tidal**, or only delete it here? Revoke is cleaner for theft; it is also another Tidal API call from this client.
3. **Docker / NAS:** keep `0.0.0.0` behind the UI secret, or require a reverse proxy and loopback-only inside the container?
4. **Headless Linux** without Secret Service: is an encrypted file in `~/.config/music-dl` acceptable, or do you want to refuse Tidal login until a keyring exists?
5. **CLI `music-dl login`:** keep it as an explicit seat-creating command (recommended), or retire it in favor of the GUI screen only?
6. **Tidal device nickname.** We cannot list Tidal's device manager from here. Is "music-dl on this computer" enough, or do you want a user-typed device name stored only locally?
7. **How many seats has Tidal actually flagged as risky?** That number decides how loud the Sign out / Connect copy should be.
8. **After a successful keychain migrate, how long do we keep `token.json.bak-migrate-*`?** Recommendation: delete after the next successful refresh, or after 7 days, whichever comes first.
9. **Atmos / API-key rotation** (`config.py:381-420`, `601-622`) uses other client ids with the same refresh token. Has Tidal ever counted those as extra devices? If yes, v2 should freeze on the client id that first succeeded and never rotate while a refresh token lives.

---

## What this PR is not

- No Python, JS, or Rust auth changes.
- No version bump and no installer.
- No change to bundled Tidal `clientId`s (rotating those would force every install to log in again — already forbidden in `MISTAKES.md` 2026-08-31).
- No implementation plan execution. When this spec is approved, implement in the phases above, smallest phase 0 first.

---

## Implementation notes (for the next PR, not this one)

Touch these areas when building v2. Do not treat this as a license to change them in the docs PR.

| Area | Files |
| --- | --- |
| Store / persist / logout / login | `tidaldl-py/tidal_dl/config.py`, `tidaldl-py/tidal_dl/model/cfg.py`, `tidaldl-py/tidal_dl/helper/path.py` |
| HTTP auth and 401 | `tidaldl-py/tidal_dl/gui/api/settings.py`, `tidaldl-py/tidal_dl/gui/__init__.py`, `tidaldl-py/tidal_dl/gui/security.py` |
| CLI | `tidaldl-py/tidal_dl/cli.py`, `tidaldl-py/tidal_dl/cli_sync.py` |
| UI | `tidaldl-py/tidal_dl/gui/static/player.js`, `views.js`, `api.js` |
| Tests that encode today's OAuth-on-reject contract | `tidaldl-py/tests/test_gui_auth_login.py` |
| Atomic write reference | `tidaldl-py/tidal_dl/gui/api/bot_control.py` |
| Update must keep the session | `tidaldl-py/tests/test_gui_lifespan.py`, `tidaldl-py/src-tauri/src/updater.rs` |
