#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/install.sh"
README_FILE="$ROOT/README.md"
INSTALL_DOC="$ROOT/docs/release/install-instructions.md"

[ -f "$SCRIPT" ] || {
  echo "missing installer script: $SCRIPT"
  exit 1
}

pass() { printf 'ok - %s\n' "$1"; }
fail() { printf 'not ok - %s\n' "$1"; exit 1; }

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "$haystack" in
    *"$needle"*) pass "$label" ;;
    *) fail "$label (missing=$needle)" ;;
  esac
}

script_contents="$(<"$SCRIPT")"
readme_contents="$(<"$README_FILE")"
install_doc_contents="$(<"$INSTALL_DOC")"

assert_contains "$script_contents" "dmg_sha" "release installer extracts the DMG digest"
assert_contains "$script_contents" "file_sha256" "release installer computes downloaded asset sha256"
assert_contains "$script_contents" "Refusing to install because the downloaded checksum does not match GitHub's release digest." "release installer refuses checksum mismatches"
assert_contains "$script_contents" "[[:space:]]*" "release installer uses macOS-compatible grep whitespace"
assert_contains "$script_contents" 'MUSIC_DL_INSTALLER_SOURCE_ONLY' "release installer can be sourced for regression tests"
assert_contains "$readme_contents" "verifies the GitHub release checksum" "README documents macOS checksum verification"
assert_contains "$install_doc_contents" "verifies the GitHub release checksum" "release install docs document macOS checksum verification"

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

fixture="$TMP_ROOT/music-dl-test.dmg"
printf 'fixture\n' >"$fixture"
expected_sha="$(shasum -a 256 "$fixture" | awk '{print $1}')"
url="file://$fixture"
mkdir -p "$TMP_ROOT/download"

source_output="$TMP_ROOT/stdout.txt"
source_error="$TMP_ROOT/stderr.txt"
MUSIC_DL_INSTALLER_SOURCE_ONLY=1 bash -c '
  set -euo pipefail
  source "$1"
  curl() {
    local output=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -o)
          output="$2"
          shift 2
          ;;
        file://*)
          cp "${1#file://}" "$output"
          shift
          ;;
        *)
          shift
          ;;
      esac
    done
  }
  download_verified_asset "$2" "$3" "$4"
' bash "$SCRIPT" "$url" "$expected_sha" "$TMP_ROOT/download" >"$source_output" 2>"$source_error"

expected_path="$TMP_ROOT/download/music-dl-test.dmg"
actual_output="$(cat "$source_output")"
assert_contains "$(cat "$source_error")" "Checksum verified" "release installer logs checksum status to stderr"
[ "$actual_output" = "$expected_path" ] \
  || fail "download_verified_asset prints only the downloaded path to stdout (actual=$actual_output)"
pass "download_verified_asset prints only the downloaded path to stdout"
