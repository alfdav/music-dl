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
assert_contains "$readme_contents" "verifies the GitHub release checksum" "README documents macOS checksum verification"
assert_contains "$install_doc_contents" "verifies the GitHub release checksum" "release install docs document macOS checksum verification"
