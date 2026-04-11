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

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "$haystack" in
    *"$needle"*) pass "$label" ;;
    *) fail "$label (missing=$needle output=$haystack)" ;;
  esac
}

run_and_capture() {
  local __output_var="$1" __status_var="$2"
  shift 2

  local output status
  set +e
  output="$("$@" 2>&1)"
  status=$?
  set -e

  printf -v "$__output_var" '%s' "$output"
  printf -v "$__status_var" '%s' "$status"
}

run_in_subshell() {
  local __output_var="$1" __status_var="$2" snippet="$3"

  local output status
  set +e
  output="$(bash -c "$snippet" 2>&1)"
  status=$?
  set -e

  printf -v "$__output_var" '%s' "$output"
  printf -v "$__status_var" '%s' "$status"
}

export MUSIC_DL_TEST_OS="Linux"
if is_macos; then
  fail "is_macos rejects non-macOS"
else
  pass "is_macos rejects non-macOS"
fi
run_and_capture mac_output mac_status require_macos
assert_nonzero "$mac_status" "require_macos exits non-zero"
assert_eq "$mac_output" "This installer only supports macOS. Run it on a Mac, then rerun this installer." "require_macos prints exact rerun guidance"
unset MUSIC_DL_TEST_OS

export MUSIC_DL_TEST_ARCH="x86_64"
if is_arm64; then
  fail "is_arm64 rejects Intel"
else
  pass "is_arm64 rejects Intel"
fi
run_and_capture arm_output arm_status require_arm64
assert_nonzero "$arm_status" "require_arm64 exits non-zero"
assert_eq "$arm_output" "This installer currently supports Apple Silicon (arm64) only. Use an Apple Silicon Mac, then rerun this installer." "require_arm64 prints exact rerun guidance"
unset MUSIC_DL_TEST_ARCH

expected_cache="$HOME/Library/Caches/music-dl-installer"
assert_eq "$(installer_cache_dir)" "$expected_cache" "default cache dir"

export MUSIC_DL_INSTALLER_CACHE_DIR="/tmp/music-dl-test-cache"
assert_eq "$(installer_cache_dir)" "/tmp/music-dl-test-cache" "cache dir override"
unset MUSIC_DL_INSTALLER_CACHE_DIR

export MUSIC_DL_TEST_XCODE_PATH=""
if has_xcode_clt >/dev/null 2>&1; then
  fail "has_xcode_clt detects missing CLT"
else
  pass "has_xcode_clt detects missing CLT"
fi
run_and_capture xcode_output xcode_status require_xcode_clt
assert_nonzero "$xcode_status" "require_xcode_clt exits non-zero"
assert_contains "$xcode_output" "Finish the Apple installer, then rerun the same command." "require_xcode_clt prints rerun guidance"
run_in_subshell xcode_composable_output xcode_composable_status "
  set -euo pipefail
  export MUSIC_DL_INSTALLER_SOURCE_ONLY=1
  source \"$SCRIPT\"
  unset MUSIC_DL_INSTALLER_SOURCE_ONLY
  export MUSIC_DL_TEST_XCODE_PATH=''
  set +e
  require_xcode_clt
  status=\$?
  set -e
  printf 'status=%s\\nafter-call\\n' \"\$status\"
"
assert_eq "$xcode_composable_status" "0" "require_xcode_clt stays composable when sourced"
assert_contains "$xcode_composable_output" "status=1" "require_xcode_clt returns status 1 when CLT missing"
assert_contains "$xcode_composable_output" "after-call" "require_xcode_clt returns control to caller"
unset MUSIC_DL_TEST_XCODE_PATH

export MUSIC_DL_TEST_PATH_BIN="/tmp"
if have_command rustc >/dev/null 2>&1; then
  fail "have_command fails when binary missing"
else
  pass "have_command fails when binary missing"
fi
run_and_capture rust_output rust_status require_rust
assert_nonzero "$rust_status" "require_rust exits non-zero"
assert_contains "$rust_output" "Install it from https://rustup.rs then rerun this installer." "require_rust prints rerun guidance"

run_and_capture uv_output uv_status require_uv
assert_nonzero "$uv_status" "require_uv exits non-zero"
assert_contains "$uv_output" "Install it from https://docs.astral.sh/uv/ then rerun this installer." "require_uv prints rerun guidance"

TMP_BIN="$(mktemp -d)"
printf '#!/usr/bin/env bash\nexit 0\n' > "$TMP_BIN/node"
chmod +x "$TMP_BIN/node"
export MUSIC_DL_TEST_PATH_BIN="$TMP_BIN"
run_and_capture node_output node_status require_node_npm
assert_nonzero "$node_status" "require_node_npm exits non-zero when npm missing"
assert_contains "$node_output" "Install Node.js + npm from https://nodejs.org/en/download, then rerun this installer." "require_node_npm prints rerun guidance"
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
git -C "$(repo_dir)" config user.name test
git -C "$(repo_dir)" config user.email test@example.com
git -C "$(repo_dir)" checkout --detach >/dev/null 2>&1
printf 'junk\n' > "$(repo_dir)/UNTRACKED.tmp"
printf 'local edit\n' > "$(repo_dir)/README.md"
git -C "$(repo_dir)" add README.md >/dev/null 2>&1
git -C "$(repo_dir)" commit -m local-change >/dev/null 2>&1 || fail "cached repo local commit succeeds"
pass "cached repo local commit succeeds"
sync_repo >/dev/null 2>&1 || fail "sync_repo refreshes cached repo"
expected_branch="$(git -C "$(repo_dir)" symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"
assert_eq "$(git -C "$(repo_dir)" rev-parse --abbrev-ref HEAD)" "$expected_branch" "sync_repo resets to origin HEAD branch"
assert_eq "$(cat "$(repo_dir)/README.md")" "hello" "sync_repo discards tracked local edits"
[ ! -e "$(repo_dir)/UNTRACKED.tmp" ] || fail "sync_repo cleans untracked files"
pass "sync_repo cleans untracked files"
rm -rf "$TMP_REMOTE" "$TMP_WORK"
unset MUSIC_DL_INSTALLER_CACHE_DIR
unset MUSIC_DL_INSTALLER_REPO_URL

export MUSIC_DL_TEST_BUILT_APP_PATH="/tmp/music-dl-custom.app"
assert_eq "$(built_app_path)" "/tmp/music-dl-custom.app" "built_app_path uses test override"
unset MUSIC_DL_TEST_BUILT_APP_PATH

export MUSIC_DL_TEST_BUILT_APP_PATH=""
assert_eq "$(built_app_path)" "" "built_app_path honors empty override when explicitly set"
unset MUSIC_DL_TEST_BUILT_APP_PATH

TMP_BUILD_ROOT="$(mktemp -d)"
export MUSIC_DL_INSTALLER_CACHE_DIR="$TMP_BUILD_ROOT/cache"
mkdir -p "$TMP_BUILD_ROOT/cache/repo/TIDALDL-PY/src-tauri/target/release/bundle/macos/music-dl.app"
assert_eq "$(built_app_path)" "$TMP_BUILD_ROOT/cache/repo/TIDALDL-PY/src-tauri/target/release/bundle/macos/music-dl.app" "built_app_path locates bundled app under bundle/macos"
unset MUSIC_DL_INSTALLER_CACHE_DIR
rm -rf "$TMP_BUILD_ROOT"

TMP_BUILD_ROOT="$(mktemp -d)"
TMP_BUILD_BIN="$(mktemp -d)"
mkdir -p "$TMP_BUILD_ROOT/TIDALDL-PY"
BUILD_LOG="$TMP_BUILD_ROOT/build.log"
cat > "$TMP_BUILD_BIN/uv" <<EOF
#!/usr/bin/env bash
printf 'uv %s\n' "\$*" >> "$BUILD_LOG"
exit 0
EOF
cat > "$TMP_BUILD_BIN/npm" <<EOF
#!/usr/bin/env bash
printf 'npm %s\n' "\$*" >> "$BUILD_LOG"
exit 0
EOF
cat > "$TMP_BUILD_BIN/npx" <<EOF
#!/usr/bin/env bash
printf 'npx %s\n' "\$*" >> "$BUILD_LOG"
exit 0
EOF
chmod +x "$TMP_BUILD_BIN/uv" "$TMP_BUILD_BIN/npm" "$TMP_BUILD_BIN/npx"
ORIGINAL_PATH="$PATH"
PATH="$TMP_BUILD_BIN:$PATH"
repo_dir() { printf '%s\n' "$TMP_BUILD_ROOT"; }
build_app >/dev/null 2>&1 || fail "build_app succeeds with available toolchain"
assert_eq "$(cat "$BUILD_LOG")" $'uv sync\nuv pip install pyinstaller\nnpm install\nnpx tauri build --config {"bundle":{"createUpdaterArtifacts":false}}' "build_app runs Task 3 build commands in order"
assert_contains "$(cat "$BUILD_LOG")" 'createUpdaterArtifacts":false' "build_app disables updater artifacts for local installer builds"
PATH="$ORIGINAL_PATH"
rm -rf "$TMP_BUILD_ROOT" "$TMP_BUILD_BIN"

TMP_BUILD_ROOT="$(mktemp -d)"
TMP_BUILD_BIN="$(mktemp -d)"
mkdir -p "$TMP_BUILD_ROOT/TIDALDL-PY"
cat > "$TMP_BUILD_BIN/uv" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$TMP_BUILD_BIN/npm" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$TMP_BUILD_BIN/npx" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
chmod +x "$TMP_BUILD_BIN/uv" "$TMP_BUILD_BIN/npm" "$TMP_BUILD_BIN/npx"
ORIGINAL_PATH="$PATH"
PATH="$TMP_BUILD_BIN:$PATH"
repo_dir() { printf '%s\n' "$TMP_BUILD_ROOT"; }
run_and_capture build_output build_status build_app
assert_nonzero "$build_status" "build_app exits non-zero when tauri build fails"
assert_contains "$build_output" "Local Tauri build failed. Fix the reported problem, then rerun this installer." "build_app prints exact tauri failure guidance"
PATH="$ORIGINAL_PATH"
rm -rf "$TMP_BUILD_ROOT" "$TMP_BUILD_BIN"

TMP_BUILD_ROOT="$(mktemp -d)"
repo_dir() { printf '%s\n' "$TMP_BUILD_ROOT"; }
run_and_capture build_cd_output build_cd_status build_app
assert_nonzero "$build_cd_status" "build_app exits non-zero when app source dir missing"
assert_contains "$build_cd_output" "Could not enter $TMP_BUILD_ROOT/TIDALDL-PY" "build_app prints cache reset guidance when app dir missing"
rm -rf "$TMP_BUILD_ROOT"

TMP_INSTALL_ROOT="$(mktemp -d)"
export MUSIC_DL_TEST_INSTALL_TARGET="$TMP_INSTALL_ROOT/Applications/music-dl.app"
export MUSIC_DL_TEST_BUILT_APP_PATH="$TMP_INSTALL_ROOT/missing/music-dl.app"
run_and_capture install_missing_output install_missing_status install_app
assert_nonzero "$install_missing_status" "install_app exits non-zero when built app missing"
assert_contains "$install_missing_output" "Built app not found at $TMP_INSTALL_ROOT/missing/music-dl.app" "install_app reports missing built app path"
unset MUSIC_DL_TEST_INSTALL_TARGET
unset MUSIC_DL_TEST_BUILT_APP_PATH
rm -rf "$TMP_INSTALL_ROOT"

TMP_INSTALL_ROOT="$(mktemp -d)"
export MUSIC_DL_TEST_INSTALL_TARGET="$TMP_INSTALL_ROOT/Applications/music-dl.app"
export MUSIC_DL_TEST_BUILT_APP_PATH=""
run_and_capture install_empty_output install_empty_status install_app
assert_nonzero "$install_empty_status" "install_app exits non-zero when built app override is explicitly empty"
assert_contains "$install_empty_output" "Built app not found at " "install_app keeps empty built app override on failure"
unset MUSIC_DL_TEST_INSTALL_TARGET
unset MUSIC_DL_TEST_BUILT_APP_PATH
rm -rf "$TMP_INSTALL_ROOT"

TMP_INSTALL_ROOT="$(mktemp -d)"
TMP_SOURCE_APP="$TMP_INSTALL_ROOT/build/music-dl.app"
TMP_TARGET_APP="$TMP_INSTALL_ROOT/Applications/music-dl.app"
mkdir -p "$TMP_SOURCE_APP/Contents/MacOS" "$TMP_TARGET_APP"
printf 'new-build\n' > "$TMP_SOURCE_APP/Contents/MacOS/music-dl"
printf 'old-build\n' > "$TMP_TARGET_APP/old.txt"
export MUSIC_DL_TEST_BUILT_APP_PATH="$TMP_SOURCE_APP"
export MUSIC_DL_TEST_INSTALL_TARGET="$TMP_TARGET_APP"
install_app >/dev/null 2>&1 || fail "install_app copies built app into install target"
assert_eq "$(cat "$TMP_TARGET_APP/Contents/MacOS/music-dl")" "new-build" "install_app copies the built app contents"
[ ! -e "$TMP_TARGET_APP/old.txt" ] || fail "install_app removes existing target before copy"
pass "install_app removes existing target before copy"
unset MUSIC_DL_TEST_BUILT_APP_PATH
unset MUSIC_DL_TEST_INSTALL_TARGET
rm -rf "$TMP_INSTALL_ROOT"

TMP_INSTALL_ROOT="$(mktemp -d)"
TMP_SOURCE_APP="$TMP_INSTALL_ROOT/build/music-dl.app"
TMP_TARGET_APP="$TMP_INSTALL_ROOT/Applications/music-dl.app"
mkdir -p "$TMP_SOURCE_APP/Contents/MacOS"
printf 'new-build\n' > "$TMP_SOURCE_APP/Contents/MacOS/music-dl"
export MUSIC_DL_TEST_BUILT_APP_PATH="$TMP_SOURCE_APP"
export MUSIC_DL_TEST_INSTALL_TARGET="$TMP_TARGET_APP"
export MUSIC_DL_TEST_FAIL_COPY="1"
run_and_capture install_copy_output install_copy_status install_app
assert_nonzero "$install_copy_status" "install_app exits non-zero when app copy fails"
assert_contains "$install_copy_output" "Could not write to $TMP_TARGET_APP" "install_app prints writable target guidance"
expected_manual_fallback="$(printf 'Try this manually:\n  sudo rm -rf "%s" && sudo cp -R "%s" "%s"\nThen rerun or launch the app from /Applications.' "$TMP_TARGET_APP" "$TMP_SOURCE_APP" "$TMP_TARGET_APP")"
assert_contains "$install_copy_output" "$expected_manual_fallback" "install_app prints exact manual copy fallback"
unset MUSIC_DL_TEST_FAIL_COPY
unset MUSIC_DL_TEST_BUILT_APP_PATH
unset MUSIC_DL_TEST_INSTALL_TARGET
rm -rf "$TMP_INSTALL_ROOT"

call_order=""
record_call() {
  if [ -n "$call_order" ]; then
    call_order="$call_order -> $1"
  else
    call_order="$1"
  fi
}

say() { :; }
require_macos() { record_call require_macos; }
require_xcode_clt() { record_call require_xcode_clt; }
require_rust() { record_call require_rust; }
require_uv() { record_call require_uv; }
require_node_npm() { record_call require_node_npm; }
require_arm64() { record_call require_arm64; }
sync_repo() { record_call sync_repo; }
build_app() { record_call build_app; }
install_app() { record_call install_app; }
say() { record_call "say:$1"; }

main >/dev/null 2>&1 || fail "main runs dependency checks"
assert_eq "$call_order" "require_macos -> require_xcode_clt -> require_rust -> require_uv -> require_node_npm -> require_arm64 -> sync_repo -> build_app -> install_app -> say:Done. Open /Applications/music-dl.app" "main runs Task 3 flow in spec order"
