#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/edge-desktop.yml"

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

assert_contains "$workflow_contents" "branches: [master]" "edge workflow runs on master pushes"
assert_contains "$workflow_contents" "macos-14" "edge workflow builds macOS on arm64 runner"
assert_contains "$workflow_contents" "ubuntu-22.04" "edge workflow builds Linux"
assert_contains "$workflow_contents" "windows-latest" "edge workflow builds Windows"
assert_contains "$workflow_contents" "scripts/edge_channel.py prepare" "edge workflow stamps edge app version"
assert_contains "$workflow_contents" "scripts/edge_channel.py manifest" "edge workflow generates updater manifest"
assert_contains "$workflow_contents" "gh release upload edge" "edge workflow uploads to the rolling edge channel"
assert_contains "$workflow_contents" "releases/assets" "edge workflow deletes stale rolling assets before upload"
assert_contains "$workflow_contents" "*.AppImage.sig" "edge workflow preserves Linux updater signature"
assert_contains "$workflow_contents" "*.app.tar.gz.sig" "edge workflow preserves macOS updater signature"
assert_contains "$workflow_contents" "*.msi.sig" "edge workflow preserves Windows updater signature"
