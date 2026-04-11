# macOS Local Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guided macOS local-build installer that ends with `/Applications/music-dl.app` and document macOS as a manual/local Tauri install path.

**Architecture:** Implement a single checked-in shell installer at repo root under `scripts/` and a small shell-based test harness that sources its helper functions. The installer will fail fast on missing prerequisites, tell the user exactly what to fix, and require rerunning the same command after each prerequisite is installed. Linux public releases remain unchanged; the installer is only for local macOS usage.

**Tech Stack:** POSIX/Bash shell, git, macOS CLI tools, Rust, uv, npm, Tauri v2

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/install-macos-local.sh` | Create | Guided macOS installer: preflight checks, repo sync, local Tauri build, install to `/Applications/music-dl.app` |
| `tests/test_macos_local_installer.sh` | Create | Shell harness for installer helper functions and deterministic preflight logic |
| `README.md` | Modify | Public install docs: Linux release downloads, macOS local installer one-liner, manual update messaging |

**Implementation notes:**
- Use `Node.js + npm` only; do not branch on Bun.
- Target Apple Silicon only for v1 (`uname -m` must be `arm64`).
- Use a deterministic cache dir under `~/Library/Caches/music-dl-installer/`.
- Clone via HTTPS (`https://github.com/alfdav/music-dl.git`) so users do not need SSH keys.
- For reruns, hard-reset the cache repo to the remote default branch resolved from `origin/HEAD`.
- Never silently use `sudo`; if `/Applications` copy fails, print the exact manual fallback command.

---

### Task 1: Add installer scaffold + shell test harness

**Files:**
- Create: `scripts/install-macos-local.sh`
- Create: `tests/test_macos_local_installer.sh`

- [ ] **Step 1: Create the working branch and directories**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
git switch -c feat/macos-local-installer
mkdir -p scripts tests
```

Expected: branch created and `scripts/` + `tests/` exist.

- [ ] **Step 2: Write the failing shell harness**

Create `tests/test_macos_local_installer.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/install-macos-local.sh"

[ -f "$SCRIPT" ] || {
  echo "missing installer script: $SCRIPT"
  exit 1
}

export MUSIC_DL_INSTALLER_SOURCE_ONLY=1
# shellcheck disable=SC1090
source "$SCRIPT"
unset MUSIC_DL_INSTALLER_SOURCE_ONLY

pass() { printf 'ok - %s\n' "$1"; }
fail() { printf 'not ok - %s\n' "$1"; exit 1; }

assert_eq() {
  local got="$1" expected="$2" label="$3"
  [ "$got" = "$expected" ] || fail "$label (got=$got expected=$expected)"
  pass "$label"
}

assert_nonzero() {
  local status="$1" label="$2"
  [ "$status" -ne 0 ] || fail "$label"
  pass "$label"
}

export MUSIC_DL_TEST_OS="Linux"
if is_macos; then
  fail "is_macos rejects non-macOS"
else
  pass "is_macos rejects non-macOS"
fi
mac_output="$( (require_macos) 2>&1 || true )"
printf '%s' "$mac_output" | grep -q "Run it on a Mac, then rerun this installer."
pass "require_macos prints rerun guidance"
unset MUSIC_DL_TEST_OS

export MUSIC_DL_TEST_ARCH="x86_64"
if is_arm64; then
  fail "is_arm64 rejects Intel"
else
  pass "is_arm64 rejects Intel"
fi
arm_output="$( (require_arm64) 2>&1 || true )"
printf '%s' "$arm_output" | grep -q "Use an Apple Silicon Mac, then rerun this installer."
pass "require_arm64 prints rerun guidance"
unset MUSIC_DL_TEST_ARCH

expected_cache="$HOME/Library/Caches/music-dl-installer"
assert_eq "$(installer_cache_dir)" "$expected_cache" "default cache dir"

export MUSIC_DL_INSTALLER_CACHE_DIR="/tmp/music-dl-test-cache"
assert_eq "$(installer_cache_dir)" "/tmp/music-dl-test-cache" "cache dir override"
unset MUSIC_DL_INSTALLER_CACHE_DIR

```

- [ ] **Step 3: Run harness to verify it fails**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
bash tests/test_macos_local_installer.sh
```

Expected: FAIL because `scripts/install-macos-local.sh` does not exist yet.

- [ ] **Step 4: Write minimal installer scaffold**

Create `scripts/install-macos-local.sh` with source-safe helpers only:

```bash
#!/usr/bin/env bash
set -euo pipefail

say() { printf '\n==> %s\n' "$1"; }
die() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

current_os() {
  if [ -n "${MUSIC_DL_TEST_OS:-}" ]; then
    printf '%s\n' "$MUSIC_DL_TEST_OS"
  else
    uname -s
  fi
}

current_arch() {
  if [ -n "${MUSIC_DL_TEST_ARCH:-}" ]; then
    printf '%s\n' "$MUSIC_DL_TEST_ARCH"
  else
    uname -m
  fi
}

installer_cache_dir() {
  printf '%s\n' "${MUSIC_DL_INSTALLER_CACHE_DIR:-$HOME/Library/Caches/music-dl-installer}"
}

is_macos() {
  [ "$(current_os)" = "Darwin" ]
}

is_arm64() {
  [ "$(current_arch)" = "arm64" ]
}

require_macos() {
  is_macos || die "This installer only supports macOS. Run it on a Mac, then rerun this installer."
}

require_arm64() {
  is_arm64 || die "This installer currently supports Apple Silicon (arm64) only. Use an Apple Silicon Mac, then rerun this installer."
}

main() {
  require_macos
  require_arm64
  say "scaffold only"
}

if [ -z "${MUSIC_DL_INSTALLER_SOURCE_ONLY:-}" ]; then
  main "$@"
fi
```

- [ ] **Step 5: Run harness to verify it passes**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
bash tests/test_macos_local_installer.sh
```

Expected: PASS.

- [ ] **Step 6: Commit scaffold**

```bash
cd "$(git rev-parse --show-toplevel)"
git add scripts/install-macos-local.sh tests/test_macos_local_installer.sh
git commit -m "feat(installer): scaffold local macos installer"
```

---

### Task 2: Implement prerequisite checks + deterministic repo sync

**Files:**
- Modify: `scripts/install-macos-local.sh`
- Modify: `tests/test_macos_local_installer.sh`

- [ ] **Step 1: Expand failing harness for preflight behavior**

Append these cases to `tests/test_macos_local_installer.sh`:

```bash
export MUSIC_DL_TEST_XCODE_PATH=""
if has_xcode_clt >/dev/null 2>&1; then
  fail "has_xcode_clt detects missing CLT"
else
  pass "has_xcode_clt detects missing CLT"
fi
xcode_output="$( (require_xcode_clt) 2>&1 || true )"
printf '%s' "$xcode_output" | grep -q "Finish the Apple installer, then rerun the same command\."
pass "require_xcode_clt prints rerun guidance"
unset MUSIC_DL_TEST_XCODE_PATH

export MUSIC_DL_TEST_PATH_BIN="/tmp"
if have_command rustc >/dev/null 2>&1; then
  fail "have_command fails when binary missing"
else
  pass "have_command fails when binary missing"
fi
rust_output="$( (require_rust) 2>&1 || true )"
printf '%s' "$rust_output" | grep -q "Install it from https://rustup.rs then rerun this installer."
pass "require_rust prints rerun guidance"

uv_output="$( (require_uv) 2>&1 || true )"
printf '%s' "$uv_output" | grep -q "Install it from https://docs.astral.sh/uv/ then rerun this installer."
pass "require_uv prints rerun guidance"

TMP_BIN="$(mktemp -d)"
printf '#!/usr/bin/env bash\nexit 0\n' > "$TMP_BIN/node"
chmod +x "$TMP_BIN/node"
export MUSIC_DL_TEST_PATH_BIN="$TMP_BIN"
node_output="$( (require_node_npm) 2>&1 || true )"
printf '%s' "$node_output" | grep -q "Install Node.js + npm from https://nodejs.org/en/download, then rerun this installer."
pass "require_node_npm prints rerun guidance"
rm -rf "$TMP_BIN"
unset MUSIC_DL_TEST_PATH_BIN

TMP_REMOTE="$(mktemp -d)"
TMP_WORK="$(mktemp -d)"
git init --bare "$TMP_REMOTE/origin.git" >/dev/null 2>&1

git clone "$TMP_REMOTE/origin.git" "$TMP_WORK/repo" >/dev/null 2>&1
(
  cd "$TMP_WORK/repo"
  git config user.name test
  git config user.email test@example.com
  printf 'hello\n' > README.md
  git add README.md
  git commit -m init >/dev/null 2>&1
  git branch -M master
  git push origin master >/dev/null 2>&1
)
git -C "$TMP_REMOTE/origin.git" symbolic-ref HEAD refs/heads/master >/dev/null 2>&1

export MUSIC_DL_INSTALLER_CACHE_DIR="$TMP_WORK/cache"
export MUSIC_DL_INSTALLER_REPO_URL="$TMP_REMOTE/origin.git"
mkdir -p "$MUSIC_DL_INSTALLER_CACHE_DIR"
git clone "$TMP_REMOTE/origin.git" "$(repo_dir)" >/dev/null 2>&1
git -C "$(repo_dir)" checkout --detach >/dev/null 2>&1
printf 'junk\n' > "$(repo_dir)/UNTRACKED.tmp"
printf 'local edit\n' > "$(repo_dir)/README.md"
git -C "$(repo_dir)" add README.md >/dev/null 2>&1
git -C "$(repo_dir)" commit -m local-change >/dev/null 2>&1 || true
sync_repo >/dev/null 2>&1 || fail "sync_repo refreshes cached repo"
expected_branch="$(git -C "$(repo_dir)" symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"
assert_eq "$(git -C "$(repo_dir)" rev-parse --abbrev-ref HEAD)" "$expected_branch" "sync_repo resets to origin HEAD branch"
assert_eq "$(cat "$(repo_dir)/README.md")" "hello" "sync_repo discards tracked local edits"
[ ! -e "$(repo_dir)/UNTRACKED.tmp" ] || fail "sync_repo cleans untracked files"
pass "sync_repo cleans untracked files"
rm -rf "$TMP_REMOTE" "$TMP_WORK"
unset MUSIC_DL_INSTALLER_CACHE_DIR
unset MUSIC_DL_INSTALLER_REPO_URL
```

- [ ] **Step 2: Run harness to verify it fails**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
bash tests/test_macos_local_installer.sh
```

Expected: FAIL because `has_xcode_clt` / `have_command` do not exist yet.

- [ ] **Step 3: Implement preflight helpers and repo sync**

Extend `scripts/install-macos-local.sh` with:

```bash
repo_dir() {
  printf '%s/repo\n' "$(installer_cache_dir)"
}

repo_url() {
  printf '%s\n' "${MUSIC_DL_INSTALLER_REPO_URL:-https://github.com/alfdav/music-dl.git}"
}

install_target() {
  printf '%s\n' "${MUSIC_DL_TEST_INSTALL_TARGET:-/Applications/music-dl.app}"
}

have_command() {
  local name="$1"
  if [ -n "${MUSIC_DL_TEST_PATH_BIN:-}" ]; then
    PATH="$MUSIC_DL_TEST_PATH_BIN" command -v "$name" >/dev/null 2>&1
  else
    command -v "$name" >/dev/null 2>&1
  fi
}

has_xcode_clt() {
  if [ "${MUSIC_DL_TEST_XCODE_PATH+set}" = "set" ]; then
    [ -n "${MUSIC_DL_TEST_XCODE_PATH:-}" ]
  else
    xcode-select -p >/dev/null 2>&1
  fi
}

require_xcode_clt() {
  say "Checking Xcode Command Line Tools"
  if ! has_xcode_clt; then
    printf 'Xcode Command Line Tools are required.\n'
    xcode-select --install >/dev/null 2>&1 || true
    printf 'Finish the Apple installer, then rerun the same command.\n'
    exit 1
  fi
}

require_rust() {
  say "Checking Rust"
  have_command rustc || die "Rust is required. Install it from https://rustup.rs then rerun this installer."
}

require_uv() {
  say "Checking uv"
  have_command uv || die "uv is required. Install it from https://docs.astral.sh/uv/ then rerun this installer."
}

require_node_npm() {
  say "Checking Node.js + npm"
  have_command node || die "Node.js is required. Install it from https://nodejs.org/en/download, make sure npm is available, then rerun this installer."
  have_command npm || die "npm is required. Install Node.js + npm from https://nodejs.org/en/download, then rerun this installer."
}

sync_repo() {
  local cache repo default_ref
  say "Syncing music-dl source"
  cache="$(installer_cache_dir)"
  repo="$(repo_dir)"
  mkdir -p "$cache"

  if [ -d "$repo" ] && [ ! -d "$repo/.git" ]; then
    rm -rf "$repo" || die "Cached repo directory is corrupted. Delete $(installer_cache_dir) and rerun this installer."
  fi

  if [ ! -d "$repo/.git" ]; then
    git clone "$(repo_url)" "$repo" || die "Could not clone music-dl. Check your network connection, then rerun this installer."
  fi

  git -C "$repo" fetch origin --prune || die "Could not update the cached music-dl repo. Check your network connection, then rerun this installer."
  git -C "$repo" remote set-head origin -a >/dev/null 2>&1 || die "Could not refresh origin/HEAD. Delete $(installer_cache_dir) and rerun this installer."
  default_ref="$(git -C "$repo" symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')" || die "Could not resolve the remote default branch. Delete $(installer_cache_dir) and rerun this installer."
  git -C "$repo" checkout -B "$default_ref" "origin/$default_ref" || die "Could not normalize the cached repo to origin/$default_ref. Delete $(installer_cache_dir) and rerun this installer."
  git -C "$repo" reset --hard "origin/$default_ref" || die "Could not reset the cached repo to origin/$default_ref. Delete $(installer_cache_dir) and rerun this installer."
  git -C "$repo" clean -fdx || die "Could not clean the cached repo. Delete $(installer_cache_dir) and rerun this installer."
}
```

Also wire these into `main()` before any build work.

- [ ] **Step 4: Run harness to verify it passes**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
bash tests/test_macos_local_installer.sh
bash -n scripts/install-macos-local.sh
```

Expected: both PASS.

- [ ] **Step 5: Verify guidance strings exist for implemented failure branches**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
grep -q "Finish the Apple installer, then rerun the same command" scripts/install-macos-local.sh
grep -q "Check your network connection, then rerun this installer" scripts/install-macos-local.sh
```

Expected: implemented preflight + repo-sync guidance strings are present in the installer.

- [ ] **Step 6: Commit preflight + repo sync**

```bash
cd "$(git rev-parse --show-toplevel)"
git add scripts/install-macos-local.sh tests/test_macos_local_installer.sh
git commit -m "feat(installer): add macos preflight and repo sync"
```

---

### Task 3: Implement build/install flow + manual fallback messaging

**Files:**
- Modify: `scripts/install-macos-local.sh`

- [ ] **Step 1: Implement local build + install functions**

Add these functions to `scripts/install-macos-local.sh`:

```bash
build_app() {
  local repo app_root
  repo="$(repo_dir)"
  app_root="$repo/TIDALDL-PY"

  say "Building music-dl locally"
  cd "$app_root" || die "Could not enter $app_root. Delete $(installer_cache_dir) and rerun this installer."
  uv sync || die "uv sync failed. Fix the reported problem, then rerun this installer."
  uv pip install pyinstaller || die "Installing PyInstaller failed. Fix the reported problem, then rerun this installer."
  npm install || die "npm install failed. Fix the reported problem, then rerun this installer."
  npx tauri build || die "Local Tauri build failed. Fix the reported problem, then rerun this installer."
}

built_app_path() {
  if [ "${MUSIC_DL_TEST_BUILT_APP_PATH+set}" = "set" ]; then
    printf '%s\n' "${MUSIC_DL_TEST_BUILT_APP_PATH:-}"
  else
    find "$(repo_dir)/TIDALDL-PY/src-tauri/target/release/bundle/macos" -maxdepth 1 -name 'music-dl.app' 2>/dev/null | head -1 || true
  fi
}

install_app() {
  local built_app target copy_failed
  built_app="$(built_app_path)"
  target="$(install_target)"
  copy_failed=0

  [ -d "$built_app" ] || die "Built app not found at $built_app. Check the build output, then rerun this installer."

  rm -rf "$target" 2>/dev/null || true
  if [ "${MUSIC_DL_TEST_FAIL_COPY:-0}" = "1" ]; then
    copy_failed=1
  elif cp -R "$built_app" "$target"; then
    say "Installed to $target"
    return 0
  else
    copy_failed=1
  fi

  if [ "$copy_failed" -ne 0 ]; then
    printf 'Could not write to %s\n' "$target" >&2
    printf 'Try this manually:\n' >&2
    printf '  sudo rm -rf %q && sudo cp -R %q %q\n' "$target" "$built_app" "$target" >&2
    printf 'Then rerun or launch the app from /Applications.\n' >&2
    exit 1
  fi
}
```

Update `main()` to run:

```bash
main() {
  require_macos
  require_xcode_clt
  require_rust
  require_uv
  require_node_npm
  require_arm64
  sync_repo
  build_app
  install_app
  say "Done. Open /Applications/music-dl.app"
}
```

- [ ] **Step 2: Expand the harness for install failure branches**

Append these cases to `tests/test_macos_local_installer.sh`:

```bash
TMP_APP="$(mktemp -d)"
mkdir -p "$TMP_APP/music-dl.app"
export MUSIC_DL_TEST_BUILT_APP_PATH="$TMP_APP/music-dl.app"
export MUSIC_DL_TEST_INSTALL_TARGET="$TMP_APP/Applications/music-dl.app"
export MUSIC_DL_TEST_FAIL_COPY=1
copy_output="$( (install_app) 2>&1 || true )"
printf '%s' "$copy_output" | grep -q "Try this manually:"
pass "install_app prints manual fallback guidance"
unset MUSIC_DL_TEST_FAIL_COPY
unset MUSIC_DL_TEST_INSTALL_TARGET
unset MUSIC_DL_TEST_BUILT_APP_PATH
rm -rf "$TMP_APP"

export MUSIC_DL_TEST_BUILT_APP_PATH=""
missing_app_output="$( (install_app) 2>&1 || true )"
printf '%s' "$missing_app_output" | grep -q "Built app not found at"
pass "install_app prints built-app-missing guidance"
unset MUSIC_DL_TEST_BUILT_APP_PATH
```

- [ ] **Step 3: Run syntax + helper tests**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
bash -n scripts/install-macos-local.sh
bash tests/test_macos_local_installer.sh
```

Expected: PASS.

- [ ] **Step 4: Verify build/install failure guidance strings exist**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
grep -q "Local Tauri build failed. Fix the reported problem, then rerun this installer." scripts/install-macos-local.sh
grep -q "Could not write to" scripts/install-macos-local.sh
grep -q "Try this manually:" scripts/install-macos-local.sh
```

Expected: the installer includes explicit build failure and `/Applications` fallback guidance.

- [ ] **Step 5: Run local installer end-to-end on this machine**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
bash scripts/install-macos-local.sh
```

Expected: after fixing any reported prerequisites and rerunning as instructed, the installer completes a successful local build and installs `/Applications/music-dl.app`.

Verify:
```bash
test -d /Applications/music-dl.app && echo installed
```

Expected: `installed`

- [ ] **Step 6: Commit build/install flow**

```bash
cd "$(git rev-parse --show-toplevel)"
git add scripts/install-macos-local.sh
git commit -m "feat(installer): build and install macos app locally"
```

---

### Task 4: Update README install story

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write the doc change**

Update the macOS install sections in `README.md` so they say:
- Linux public releases are downloadable
- macOS uses the local installer one-liner
- macOS updates are manual: rerun the installer or rebuild locally

Use concrete text like:

```markdown
### Option 1b: Desktop App on macOS (manual/local build)

Run:

```bash
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-macos-local.sh | bash
```

If the installer reports a missing dependency, fix it and rerun the same command. On success it installs the app to `/Applications/music-dl.app`.
```

- [ ] **Step 2: Verify README references**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
grep -q "install-macos-local" README.md
grep -q "/Applications/music-dl.app" README.md
grep -q "manual/local build" README.md
grep -q "GitHub Releases" README.md
grep -q "rerun the installer" README.md
grep -q "rebuild locally" README.md
```

Expected: the new macOS installer language appears.

- [ ] **Step 3: Commit docs**

```bash
cd "$(git rev-parse --show-toplevel)"
git add README.md
git commit -m "docs: add macos local installer guide"
```

---

### Task 5: Final verification + branch prep

**Files:**
- Verify only: `scripts/install-macos-local.sh`, `tests/test_macos_local_installer.sh`, `README.md`

- [ ] **Step 1: Run full planned verification**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
bash -n scripts/install-macos-local.sh
bash tests/test_macos_local_installer.sh
grep -q "install-macos-local" README.md
grep -q "/Applications/music-dl.app" README.md
grep -q "manual/local build" README.md
grep -q "GitHub Releases" README.md
grep -q "rerun the installer" README.md
grep -q "rebuild locally" README.md
```

Expected: all commands PASS and README references are present.

- [ ] **Step 2: Verify installed app path after successful installer run**

Run:
```bash
test -d /Applications/music-dl.app && echo installed
```

Expected: `installed`

- [ ] **Step 3: Inspect diff before PR**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
git status --short
git diff -- scripts/install-macos-local.sh tests/test_macos_local_installer.sh README.md
```

Expected: only installer/test/README changes for this feature.

- [ ] **Step 4: Final commit if needed**

```bash
cd "$(git rev-parse --show-toplevel)"
git add scripts/install-macos-local.sh tests/test_macos_local_installer.sh README.md
git commit -m "chore: finalize macos local installer"
```

- [ ] **Step 5: Push branch**

```bash
cd "$(git rev-parse --show-toplevel)"
git push -u origin feat/macos-local-installer
```

Expected: branch pushed and ready for PR.
