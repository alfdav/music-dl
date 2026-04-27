#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/scripts/install-windows-local.ps1"
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

assert_contains "$script_contents" "git@github.com:alfdav/music-dl.git" "Windows source installer defaults to SSH Git"
assert_contains "$script_contents" "remote set-url origin" "Windows source installer normalizes cached repo origin"
assert_contains "$script_contents" "uv sync --extra build" "Windows source installer syncs build dependencies with uv"
assert_contains "$script_contents" "bun install" "Windows source installer uses Bun"
assert_contains "$script_contents" "uv run pyinstaller --clean" "Windows source installer builds the Python sidecar"
assert_contains "$script_contents" 'music-dl-server-$TargetTriple.exe' "Windows source installer renames sidecar for Tauri"
assert_contains "$script_contents" "bunx tauri build --target" "Windows source installer builds Tauri MSI"
assert_contains "$script_contents" "src-tauri/tauri.ci.conf.json" "Windows source installer uses CI config override"
assert_contains "$script_contents" "msiexec.exe" "Windows source installer starts the MSI installer"
assert_contains "$readme_contents" "scripts/install-windows-local.ps1" "README documents Windows source installer"
assert_contains "$install_doc_contents" "scripts/install-windows-local.ps1" "release install docs document Windows source installer"
