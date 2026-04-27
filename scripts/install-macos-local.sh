#!/usr/bin/env bash
set -euo pipefail

say() { printf '\n==> %s\n' "$1"; }
die() { printf '%b\n' "$1" >&2; exit 1; }

current_os() {
  if [ -n "${MUSIC_DL_TEST_OS:-}" ]; then
    printf '%s\n' "$MUSIC_DL_TEST_OS"
  else
    uname -s
  fi
}

current_arch() {
  if [ -n "${MUSIC_DL_TEST_ARCH:-}" ]; then
    printf '%s\n' "$MUSIC_DL_TEST_ARCH"
  else
    uname -m
  fi
}

installer_cache_dir() {
  printf '%s\n' "${MUSIC_DL_INSTALLER_CACHE_DIR:-$HOME/Library/Caches/music-dl-installer}"
}

repo_dir() {
  printf '%s/repo\n' "$(installer_cache_dir)"
}

repo_url() {
  printf '%s\n' "${MUSIC_DL_INSTALLER_REPO_URL:-git@github.com:alfdav/music-dl.git}"
}

install_target() {
  printf '%s\n' "${MUSIC_DL_TEST_INSTALL_TARGET:-/Applications/music-dl.app}"
}

is_macos() {
  [ "$(current_os)" = "Darwin" ]
}

is_arm64() {
  [ "$(current_arch)" = "arm64" ]
}

have_command() {
  local name="$1"
  if [ -n "${MUSIC_DL_TEST_PATH_BIN:-}" ]; then
    PATH="$MUSIC_DL_TEST_PATH_BIN" command -v "$name" >/dev/null 2>&1
  else
    command -v "$name" >/dev/null 2>&1
  fi
}

has_xcode_clt() {
  if [ "${MUSIC_DL_TEST_XCODE_PATH+set}" = "set" ]; then
    [ -n "${MUSIC_DL_TEST_XCODE_PATH:-}" ]
  else
    xcode-select -p >/dev/null 2>&1
  fi
}

require_macos() {
  is_macos || die "This installer only supports macOS. Run it on a Mac, then rerun this installer."
}

require_arm64() {
  is_arm64 || die "This installer currently supports Apple Silicon (arm64) only. Use an Apple Silicon Mac, then rerun this installer."
}

require_xcode_clt() {
  say "Checking Xcode Command Line Tools"
  if ! has_xcode_clt; then
    printf 'Xcode Command Line Tools are required.\n'
    xcode-select --install >/dev/null 2>&1 || true
    printf 'Finish the Apple installer, then rerun the same command.\n'
    return 1
  fi
}

require_rust() {
  say "Checking Rust"
  have_command rustc || die "Rust is required. Install it from https://rustup.rs then rerun this installer."
}

require_uv() {
  say "Checking uv"
  have_command uv || die "uv is required. Install it from https://docs.astral.sh/uv/ then rerun this installer."
}

require_bun() {
  say "Checking Bun"
  have_command bun || die "Bun is required. Install it from https://bun.sh/docs/installation then rerun this installer."
}

sync_repo() {
  local cache repo default_ref
  say "Syncing music-dl source"
  cache="$(installer_cache_dir)"
  repo="$(repo_dir)"
  mkdir -p "$cache"

  if [ -d "$repo" ] && [ ! -d "$repo/.git" ]; then
    rm -rf "$repo" || die "Cached repo directory is corrupted. Delete $(installer_cache_dir) and rerun this installer."
  fi

  if [ ! -d "$repo/.git" ]; then
    git clone "$(repo_url)" "$repo" || die "Could not clone music-dl. Check your network connection, then rerun this installer."
  fi

  git -C "$repo" remote set-url origin "$(repo_url)" || die "Could not update cached repo origin. Delete $(installer_cache_dir) and rerun this installer."
  git -C "$repo" fetch origin --prune || die "Could not update the cached music-dl repo. Check your network connection, then rerun this installer."
  git -C "$repo" remote set-head origin -a >/dev/null 2>&1 || die "Could not refresh origin/HEAD. Delete $(installer_cache_dir) and rerun this installer."
  default_ref="$(git -C "$repo" symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')" || die "Could not resolve the remote default branch. Delete $(installer_cache_dir) and rerun this installer."
  git -C "$repo" checkout -B "$default_ref" "origin/$default_ref" || die "Could not normalize the cached repo to origin/$default_ref. Delete $(installer_cache_dir) and rerun this installer."
  git -C "$repo" reset --hard "origin/$default_ref" || die "Could not reset the cached repo to origin/$default_ref. Delete $(installer_cache_dir) and rerun this installer."
  git -C "$repo" clean -fdx || die "Could not clean the cached repo. Delete $(installer_cache_dir) and rerun this installer."
}

build_app() {
  local app_dir tauri_local_config
  say "Building music-dl.app"
  app_dir="$(repo_dir)/tidaldl-py"
  tauri_local_config='{"bundle":{"createUpdaterArtifacts":false}}'
  [ -d "$app_dir" ] || die "Could not enter $app_dir. Delete $(installer_cache_dir) and rerun this installer."

  (
    cd "$app_dir" || die "Could not enter $app_dir. Delete $(installer_cache_dir) and rerun this installer."
    uv sync --extra build || die "Python dependency sync failed. Fix the reported problem, then rerun this installer."
    bun install || die "Bun dependency install failed. Fix the reported problem, then rerun this installer."
    bunx tauri build --config "$tauri_local_config" || die "Local Tauri build failed. Fix the reported problem, then rerun this installer."
  )
}

built_app_path() {
  local bundle_dir
  if [ "${MUSIC_DL_TEST_BUILT_APP_PATH+set}" = "set" ]; then
    printf '%s\n' "$MUSIC_DL_TEST_BUILT_APP_PATH"
  else
    bundle_dir="$(repo_dir)/tidaldl-py/src-tauri/target/release/bundle/macos"
    find "$bundle_dir" -maxdepth 1 -name 'music-dl.app' 2>/dev/null | head -1 || true
  fi
}

manual_install_command() {
  local built_app="$1" target="$2"
  printf 'sudo rm -rf "%s" && sudo cp -R "%s" "%s"' "$target" "$built_app" "$target"
}

install_app() {
  local built_app target target_parent manual_command
  say "Installing music-dl.app"
  built_app="$(built_app_path)"
  target="$(install_target)"
  target_parent="$(dirname "$target")"
  manual_command="$(manual_install_command "$built_app" "$target")"

  [ -d "$built_app" ] || die "Built app not found at $built_app. Fix the reported problem, then rerun this installer."

  mkdir -p "$target_parent" || die "Could not write to $target.\nTry this manually:\n  $manual_command\nThen rerun or launch the app from /Applications."
  rm -rf "$target" || die "Could not write to $target.\nTry this manually:\n  $manual_command\nThen rerun or launch the app from /Applications."

  if [ -n "${MUSIC_DL_TEST_FAIL_COPY:-}" ]; then
    false
  else
    cp -R "$built_app" "$target"
  fi || die "Could not write to $target.\nTry this manually:\n  $manual_command\nThen rerun or launch the app from /Applications."
}

main() {
  require_macos
  require_arm64
  require_xcode_clt
  require_rust
  require_uv
  require_bun
  sync_repo
  build_app
  install_app
  say "Done. Open /Applications/music-dl.app"
}

if [ -z "${MUSIC_DL_INSTALLER_SOURCE_ONLY:-}" ]; then
  main "$@"
fi
