#!/usr/bin/env bash
# Full reset / uninstall for music-dl on macOS and Linux.
# Usage: curl -fsSL https://raw.githubusercontent.com/STEPPING3DCAD/music-dl/master/scripts/reset.sh | bash
#
# Removes: app bundle, config dir, caches, logs, pip and uv package.
# Does NOT touch your downloaded music library.
set -euo pipefail

APP_NAME="music-dl"
BUNDLE_ID="com.alfdav.music-dl"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$1" >&2; }
ok()  { printf '\033[1;32m    %s\033[0m\n' "$1" >&2; }
skip(){ printf '    (not found, skipping)\n' >&2; }

remove() {
  local target
  target="$1"
  if [ -e "$target" ] || [ -L "$target" ]; then
    rm -rf "$target"
    ok "Removed: $target"
  else
    skip
  fi
}

say "Stopping any running ${APP_NAME} processes"
pkill -f "${APP_NAME}.app/Contents/MacOS" 2>/dev/null || true
pkill -f "${APP_NAME}-server"             2>/dev/null || true
pkill -f "${APP_NAME}"                    2>/dev/null || true
sleep 1

say "Removing app bundle"
remove "/Applications/${APP_NAME}.app"
remove "${HOME}/Applications/${APP_NAME}.app"

say "Removing config and credentials"
remove "${HOME}/.config/${APP_NAME}"

say "Removing caches"
remove "${HOME}/Library/Caches/${BUNDLE_ID}"
remove "${HOME}/Library/Caches/${APP_NAME}-installer"
remove "${HOME}/Library/WebKit/${BUNDLE_ID}"

say "Removing logs"
remove "${HOME}/Library/Logs/${APP_NAME}dl"
remove "${HOME}/Library/Logs/${APP_NAME}"

say "Removing Application Support"
remove "${HOME}/Library/Application Support/${BUNDLE_ID}"
remove "${HOME}/Library/Application Support/${APP_NAME}"

say "Removing Saved Application State"
remove "${HOME}/Library/Saved Application State/${BUNDLE_ID}.savedState"

say "Uninstalling pip package (musicdl)"
if python3 -m pip show musicdl >/dev/null 2>&1; then
  python3 -m pip uninstall -y musicdl 2>/dev/null && ok "pip package removed" || true
else
  skip
fi

say "Removing uv-managed tool install"
if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q music-dl; then
  uv tool uninstall music-dl 2>/dev/null && ok "uv tool removed" || true
else
  skip
fi

say "Removing standalone binary"
remove "${HOME}/.local/bin/${APP_NAME}"

printf '\n\033[1;32mDone.\033[0m music-dl has been fully removed.\n' >&2
printf 'Your music library files were not touched.\n' >&2
printf 'To reinstall:\n  curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.sh | bash\n' >&2
