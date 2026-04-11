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

main >/dev/null 2>&1 || fail "main runs dependency checks"
assert_eq "$call_order" "require_macos -> require_xcode_clt -> require_rust -> require_uv -> require_node_npm -> require_arm64 -> sync_repo" "main runs Task 2 checks in spec order"
