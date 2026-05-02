#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/build-desktop.yml"
CONTRIBUTING="$ROOT/CONTRIBUTING.md"
README="$ROOT/README.md"
INSTALL_DOC="$ROOT/docs/release/install-instructions.md"

[ -f "$WORKFLOW" ] || {
  echo "missing workflow: $WORKFLOW"
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

workflow_contents="$(<"$WORKFLOW")"
contributing_contents="$(<"$CONTRIBUTING")"
readme_contents="$(<"$README")"
install_doc_contents="$(<"$INSTALL_DOC")"

assert_contains "$workflow_contents" "macos-14" "stable workflow builds macOS on arm64 runner"
assert_contains "$workflow_contents" "--bundles app,dmg" "stable workflow creates macOS updater archive and DMG"
assert_contains "$workflow_contents" "*.app.tar.gz" "stable workflow uploads macOS updater archive"
assert_contains "$workflow_contents" "*.app.tar.gz.sig" "stable workflow uploads macOS updater signature"
assert_contains "$workflow_contents" "*.dmg" "stable workflow uploads macOS DMG"
assert_contains "$workflow_contents" "*.msi.sig" "stable workflow preserves Windows updater signature"
assert_contains "$workflow_contents" "scripts/edge_channel.py manifest" "stable workflow generates multi-platform latest.json"
assert_contains "$workflow_contents" "read_text(encoding='utf-8')" "stable workflow reads static assets as UTF-8"

assert_contains "$contributing_contents" "Linux, macOS, and Windows binaries" "release docs describe cross-platform CI"
assert_contains "$contributing_contents" "darwin-aarch64" "release docs require macOS updater manifest platform"
assert_contains "$readme_contents" "Linux, macOS, and Windows releases are published via GitHub Actions" "README describes CI-published macOS releases"
assert_contains "$install_doc_contents" ".app.tar.gz" "release install docs list macOS updater archive"
