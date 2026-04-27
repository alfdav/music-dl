#!/usr/bin/env bash
# One-line installer for music-dl on macOS and Linux.
# Usage: curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.sh | bash
#
# macOS: downloads the latest DMG, verifies its checksum, installs to /Applications.
# Linux: downloads the latest AppImage, verifies its checksum, installs to ~/.local/bin.
set -euo pipefail

REPO="alfdav/music-dl"
APP_NAME="music-dl"
MACOS_INSTALL_DIR="/Applications"
LINUX_INSTALL_DIR="${MUSIC_DL_INSTALL_DIR:-$HOME/.local/bin}"
INSTALLER_TMPDIR=""
INSTALLER_MOUNT_POINT=""

say()  { printf '\n\033[1;33m==> %s\033[0m\n' "$1" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }
ok()   { printf '\033[1;32m==> %s\033[0m\n' "$1" >&2; }

cleanup_installer() {
  if [ -n "${INSTALLER_MOUNT_POINT:-}" ]; then
    hdiutil detach "$INSTALLER_MOUNT_POINT" 2>/dev/null || true
    INSTALLER_MOUNT_POINT=""
  fi
  if [ -n "${INSTALLER_TMPDIR:-}" ]; then
    rm -rf "$INSTALLER_TMPDIR"
    INSTALLER_TMPDIR=""
  fi
}

current_os() {
  uname -s
}

current_arch() {
  uname -m
}

fetch_latest_release() {
  curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    || die "Could not reach GitHub. Check your connection."
}

asset_for_extension() {
  local release_json="$1" extension="$2"
  printf '%s\n' "$release_json" | awk -v extension="$extension" '
    /"assets": \[/ { in_assets=1; next }
    in_assets && /^    \{/ { block=$0 "\n"; in_asset=1; next }
    in_asset {
      block=block $0 "\n"
      if ($0 ~ /^    \}/) {
        pattern = "\"browser_download_url\": *\"[^\"]*\\." extension "\""
        if (block ~ pattern) {
          printf "%s", block
          exit
        }
        block=""
        in_asset=0
      }
    }
  '
}

asset_url() {
  local asset="$1" extension="$2"
  printf '%s' "$asset" \
    | grep -Eo "\"browser_download_url\":[[:space:]]*\"[^\"]*\\.${extension}\"" \
    | head -1 \
    | sed 's/.*"\(http[^"]*\)".*/\1/'
}

asset_sha256() {
  local asset="$1"
  printf '%s' "$asset" \
    | grep -Eo '"digest":[[:space:]]*"sha256:[0-9a-fA-F]{64}"' \
    | head -1 \
    | sed 's/.*sha256:\([0-9a-fA-F]\{64\}\).*/\1/'
}

release_version() {
  local release_json="$1"
  printf '%s' "$release_json" \
    | grep -Eo '"tag_name":[[:space:]]*"[^"]*"' \
    | head -1 \
    | sed 's/.*"\([^"]*\)".*/\1/'
}

file_sha256() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    die "No SHA-256 tool found. Install sha256sum or shasum, then rerun this installer."
  fi
}

download_verified_asset() {
  local url="$1" expected_sha="$2" tmpdir="$3" file actual_sha
  file="$(basename "$url")"

  say "Downloading ${file}"
  curl -fSL --progress-bar -o "${tmpdir}/${file}" "$url" \
    || die "Download failed."

  say "Verifying download checksum"
  actual_sha="$(file_sha256 "${tmpdir}/${file}")"
  [ "$actual_sha" = "$expected_sha" ] \
    || die "Refusing to install because the downloaded checksum does not match GitHub's release digest."
  ok "Checksum verified"

  printf '%s\n' "${tmpdir}/${file}"
}

install_macos_dmg() {
  local release_json dmg_asset dmg_url version dmg_sha tmpdir dmg_file mount_point app_src

  say "Fetching latest release info"
  release_json="$(fetch_latest_release)"
  dmg_asset="$(asset_for_extension "$release_json" "dmg")"
  dmg_url="$(asset_url "$dmg_asset" "dmg")"
  [ -n "$dmg_url" ] || die "No DMG found in the latest release. Use the build-from-source installer instead:\n  curl -fsSL https://raw.githubusercontent.com/${REPO}/master/scripts/install-macos-local.sh | bash"

  version="$(release_version "$release_json")"
  dmg_sha="$(asset_sha256 "$dmg_asset")"
  [ -n "$dmg_sha" ] || die "No SHA-256 digest found for the macOS DMG in the latest GitHub release."

  tmpdir="$(mktemp -d)"
  INSTALLER_TMPDIR="$tmpdir"
  mount_point=""
  INSTALLER_MOUNT_POINT=""
  trap cleanup_installer EXIT
  dmg_file="$(download_verified_asset "$dmg_url" "$dmg_sha" "$tmpdir")"

  say "Installing to ${MACOS_INSTALL_DIR}"

  if pgrep -f "${APP_NAME}.app" >/dev/null 2>&1; then
    say "Stopping running ${APP_NAME}"
    pkill -f "${APP_NAME}.app/Contents/MacOS/music-dl-server" 2>/dev/null || true
    pkill -f "${APP_NAME}.app/Contents/MacOS/music-dl" 2>/dev/null || true
    sleep 1
  fi

  mount_point="$(hdiutil attach -nobrowse -readonly "$dmg_file" 2>/dev/null \
    | grep '/Volumes/' | sed 's/.*\(\/Volumes\/.*\)/\1/')" \
    || die "Could not mount DMG."
  INSTALLER_MOUNT_POINT="$mount_point"

  app_src="$(find "$mount_point" -maxdepth 1 -name "*.app" -print -quit)"
  [ -n "$app_src" ] || die "No .app found in the DMG."

  if [ -d "${MACOS_INSTALL_DIR}/${APP_NAME}.app" ]; then
    say "Replacing existing ${APP_NAME}.app"
    rm -rf "${MACOS_INSTALL_DIR}/${APP_NAME}.app"
  fi

  cp -R "$app_src" "${MACOS_INSTALL_DIR}/" \
    || die "Copy failed. You may need to run: sudo bash -c 'curl ... | bash'"

  xattr -cr "${MACOS_INSTALL_DIR}/${APP_NAME}.app" 2>/dev/null || true
  hdiutil detach "$mount_point" -quiet 2>/dev/null || true
  INSTALLER_MOUNT_POINT=""
  mount_point=""
  cleanup_installer
  trap - EXIT

  ok "${APP_NAME} ${version} installed to ${MACOS_INSTALL_DIR}/${APP_NAME}.app"
  open -a "$APP_NAME"
}

install_linux_appimage() {
  local release_json appimage_asset appimage_url version appimage_sha tmpdir appimage_file target

  [ "$(current_arch)" = "x86_64" ] \
    || die "Linux quick install currently supports x86_64 only. Use the Docker installer on this machine:\n  curl -fsSL https://raw.githubusercontent.com/${REPO}/master/scripts/install-docker.sh | bash"

  say "Fetching latest release info"
  release_json="$(fetch_latest_release)"
  appimage_asset="$(asset_for_extension "$release_json" "AppImage")"
  appimage_url="$(asset_url "$appimage_asset" "AppImage")"
  [ -n "$appimage_url" ] || die "No AppImage found in the latest release."

  version="$(release_version "$release_json")"
  appimage_sha="$(asset_sha256 "$appimage_asset")"
  [ -n "$appimage_sha" ] || die "No SHA-256 digest found for the Linux AppImage in the latest GitHub release."

  tmpdir="$(mktemp -d)"
  INSTALLER_TMPDIR="$tmpdir"
  INSTALLER_MOUNT_POINT=""
  trap cleanup_installer EXIT
  appimage_file="$(download_verified_asset "$appimage_url" "$appimage_sha" "$tmpdir")"

  say "Installing to ${LINUX_INSTALL_DIR}"
  mkdir -p "$LINUX_INSTALL_DIR" || die "Could not create ${LINUX_INSTALL_DIR}."
  target="${LINUX_INSTALL_DIR}/${APP_NAME}"
  cp "$appimage_file" "$target" || die "Could not write ${target}."
  chmod +x "$target" || die "Could not make ${target} executable."
  cleanup_installer
  trap - EXIT

  ok "${APP_NAME} ${version} installed to ${target}"
  case ":$PATH:" in
    *":${LINUX_INSTALL_DIR}:"*) ;;
    *) printf 'Add %s to PATH, or run %s directly.\n' "$LINUX_INSTALL_DIR" "$target" ;;
  esac
}

main() {
  case "$(current_os)" in
    Darwin)
      install_macos_dmg
      ;;
    Linux)
      install_linux_appimage
      ;;
    *)
      die "Unsupported OS: $(current_os). Use Windows PowerShell instead:\n  irm https://raw.githubusercontent.com/${REPO}/master/scripts/install.ps1 | iex"
      ;;
  esac
}

if [ "${MUSIC_DL_INSTALLER_SOURCE_ONLY:-0}" != "1" ]; then
  main "$@"
fi
