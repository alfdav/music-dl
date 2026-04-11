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
