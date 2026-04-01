#!/usr/bin/env bash
# Build the Python sidecar binary for Tauri bundling.
# Usage: bash scripts/build-sidecar.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BINARIES_DIR="$PROJECT_DIR/src-tauri/binaries"

# Detect target triple
TARGET_TRIPLE="$(rustc --print host-tuple)"
SIDECAR_NAME="music-dl-server-${TARGET_TRIPLE}"

SPEC_FILE="$PROJECT_DIR/build/pyinstaller/music-dl-server.spec"

echo "==> Building sidecar for ${TARGET_TRIPLE}"
echo "    spec: ${SPEC_FILE}"

cd "$PROJECT_DIR"

# Build with PyInstaller using the full-dependency spec file
.venv/bin/pyinstaller \
    --distpath "$BINARIES_DIR" \
    --workpath build/pyinstaller \
    --noconfirm \
    "$SPEC_FILE"

# Rename with target triple (Tauri requirement)
mv "$BINARIES_DIR/music-dl-server" "$BINARIES_DIR/${SIDECAR_NAME}"

echo "==> Sidecar built: ${BINARIES_DIR}/${SIDECAR_NAME}"
