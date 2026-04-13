#!/usr/bin/env bash
# One-line installer for music-dl on macOS.
# Usage: curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.sh | bash
#
# Downloads the latest DMG from GitHub Releases, mounts it, copies to
# /Applications, and cleans up.  curl does NOT set the quarantine xattr,
# so Gatekeeper never fires.
set -euo pipefail

REPO="alfdav/music-dl"
APP_NAME="music-dl"
INSTALL_DIR="/Applications"

say()  { printf '\n\033[1;33m==> %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }
done() { printf '\033[1;32m==> %s\033[0m\n' "$1"; }

# ── Preflight ─────────────────────────────────────────────────────────
[ "$(uname -s)" = "Darwin" ] || die "This installer only supports macOS."

say "Fetching latest release info"
RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest") \
  || die "Could not reach GitHub. Check your connection."

DMG_URL=$(printf '%s' "$RELEASE_JSON" | grep -o '"browser_download_url":\s*"[^"]*\.dmg"' | head -1 | sed 's/.*"\(http[^"]*\)".*/\1/')
[ -n "$DMG_URL" ] || die "No DMG found in the latest release. Use the build-from-source installer instead:\n  curl -fsSL https://raw.githubusercontent.com/${REPO}/master/scripts/install-macos-local.sh | bash"

VERSION=$(printf '%s' "$RELEASE_JSON" | grep -o '"tag_name":\s*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)".*/\1/')
DMG_FILE=$(basename "$DMG_URL")

say "Downloading ${APP_NAME} ${VERSION}"
TMPDIR_DL=$(mktemp -d)
trap 'rm -rf "$TMPDIR_DL"; hdiutil detach "$MOUNT_POINT" 2>/dev/null || true' EXIT
curl -fSL --progress-bar -o "${TMPDIR_DL}/${DMG_FILE}" "$DMG_URL" \
  || die "Download failed."

say "Installing to ${INSTALL_DIR}"
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

done "${APP_NAME} ${VERSION} installed to ${INSTALL_DIR}/${APP_NAME}.app"
printf '  Open it from your Applications folder or run:\n'
printf '    open -a %s\n\n' "$APP_NAME"
