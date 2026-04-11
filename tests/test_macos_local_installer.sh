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
