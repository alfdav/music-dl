#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_SH="$ROOT/scripts/install.sh"
INSTALL_PS1="$ROOT/scripts/install.ps1"
README_FILE="$ROOT/README.md"
INSTALL_DOC="$ROOT/docs/release/install-instructions.md"

pass() { printf 'ok - %s\n' "$1"; }
fail() { printf 'not ok - %s\n' "$1"; exit 1; }

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "$haystack" in
    *"$needle"*) pass "$label" ;;
    *) fail "$label (missing=$needle)" ;;
  esac
}

install_sh_contents="$(<"$INSTALL_SH")"
install_ps1_contents="$(<"$INSTALL_PS1")"
readme_contents="$(<"$README_FILE")"
install_doc_contents="$(<"$INSTALL_DOC")"

assert_contains "$install_sh_contents" "MUSIC_DL_RELEASE_TAG" "macOS/Linux installer accepts release tag override"
assert_contains "$install_sh_contents" "releases/tags" "macOS/Linux installer can fetch a named release"
assert_contains "$install_ps1_contents" "MUSIC_DL_RELEASE_TAG" "Windows installer accepts release tag override"
assert_contains "$install_ps1_contents" "releases/tags" "Windows installer can fetch a named release"
assert_contains "$readme_contents" "MUSIC_DL_RELEASE_TAG=edge" "README documents edge installer command"
assert_contains "$install_doc_contents" "MUSIC_DL_RELEASE_TAG=edge" "release install docs document edge installer command"
