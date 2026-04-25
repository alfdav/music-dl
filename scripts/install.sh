#!/usr/bin/env bash
# One-line installer for music-dl on macOS.
# Usage: curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.sh | bash
#
# Downloads the latest DMG from GitHub Releases, verifies its checksum,
# mounts it, copies to /Applications, and cleans up. curl does NOT set the
# quarantine xattr, so Gatekeeper never fires.
set -euo pipefail

REPO="alfdav/music-dl"
APP_NAME="music-dl"
INSTALL_DIR="/Applications"

say()  { printf '\n\033[1;33m==> %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }
ok()   { printf '\033[1;32m==> %s\033[0m\n' "$1"; }

# ── Preflight ─────────────────────────────────────────────────────────
[ "$(uname -s)" = "Darwin" ] || die "This installer only supports macOS."

say "Fetching latest release info"
RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest") \
  || die "Could not reach GitHub. Check your connection."

DMG_ASSET=$(printf '%s\n' "$RELEASE_JSON" | awk '
  /"assets": \[/ { in_assets=1; next }
  in_assets && /^    \{/ { block=$0 "\n"; in_asset=1; next }
  in_asset {
    block=block $0 "\n"
    if ($0 ~ /^    \}/) {
      if (block ~ /"browser_download_url": *"[^"]*\.dmg"/) {
        printf "%s", block
        exit
      }
      block=""
      in_asset=0
    }
  }
')

DMG_URL=$(printf '%s' "$DMG_ASSET" | grep -Eo '"browser_download_url":[[:space:]]*"[^"]*\.dmg"' | head -1 | sed 's/.*"\(http[^"]*\)".*/\1/')
[ -n "$DMG_URL" ] || die "No DMG found in the latest release. Use the build-from-source installer instead:\n  curl -fsSL https://raw.githubusercontent.com/${REPO}/master/scripts/install-macos-local.sh | bash"

VERSION=$(printf '%s' "$RELEASE_JSON" | grep -Eo '"tag_name":[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)".*/\1/')
DMG_SHA256=$(printf '%s' "$DMG_ASSET" | grep -Eo '"digest":[[:space:]]*"sha256:[0-9a-fA-F]{64}"' | head -1 | sed 's/.*sha256:\([0-9a-fA-F]\{64\}\).*/\1/')
[ -n "$DMG_SHA256" ] || die "No SHA-256 digest found for the macOS DMG in the latest GitHub release."
DMG_FILE=$(basename "$DMG_URL")

say "Downloading ${APP_NAME} ${VERSION}"
TMPDIR_DL=$(mktemp -d)
trap 'rm -rf "$TMPDIR_DL"; hdiutil detach "$MOUNT_POINT" 2>/dev/null || true' EXIT
curl -fSL --progress-bar -o "${TMPDIR_DL}/${DMG_FILE}" "$DMG_URL" \
  || die "Download failed."

say "Verifying download checksum"
ACTUAL_SHA256=$(shasum -a 256 "${TMPDIR_DL}/${DMG_FILE}" | awk '{print $1}')
[ "$ACTUAL_SHA256" = "$DMG_SHA256" ] || die "Refusing to install because the downloaded DMG checksum does not match GitHub's release digest."
ok "Checksum verified"

say "Installing to ${INSTALL_DIR}"

# Stop the running app and sidecar so we don't replace a live binary
if pgrep -f "${APP_NAME}.app" >/dev/null 2>&1; then
  say "Stopping running ${APP_NAME}"
  pkill -f "${APP_NAME}.app/Contents/MacOS/music-dl-server" 2>/dev/null || true
  pkill -f "${APP_NAME}.app/Contents/MacOS/music-dl" 2>/dev/null || true
  sleep 1
fi

MOUNT_POINT=$(hdiutil attach -nobrowse -readonly "${TMPDIR_DL}/${DMG_FILE}" 2>/dev/null \
  | grep '/Volumes/' | sed 's/.*\(\/Volumes\/.*\)/\1/') \
  || die "Could not mount DMG."

APP_SRC=$(find "$MOUNT_POINT" -maxdepth 1 -name "*.app" -print -quit)
[ -n "$APP_SRC" ] || die "No .app found in the DMG."

# Remove old version if present
if [ -d "${INSTALL_DIR}/${APP_NAME}.app" ]; then
  say "Replacing existing ${APP_NAME}.app"
  rm -rf "${INSTALL_DIR}/${APP_NAME}.app"
fi

cp -R "$APP_SRC" "${INSTALL_DIR}/" \
  || die "Copy failed. You may need to run: sudo bash -c 'curl ... | bash'"

# Belt-and-suspenders: strip quarantine in case macOS adds it anyway
xattr -cr "${INSTALL_DIR}/${APP_NAME}.app" 2>/dev/null || true

hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true

ok "${APP_NAME} ${VERSION} installed to ${INSTALL_DIR}/${APP_NAME}.app"
open -a "$APP_NAME"
