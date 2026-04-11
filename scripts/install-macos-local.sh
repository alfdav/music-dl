#!/usr/bin/env bash
set -euo pipefail

say() { printf '\n==> %s\n' "$1"; }
die() { printf '%s\n' "$1" >&2; exit 1; }

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

is_macos() {
  [ "$(current_os)" = "Darwin" ]
}

is_arm64() {
  [ "$(current_arch)" = "arm64" ]
}

require_macos() {
  is_macos || die "This installer only supports macOS. Run it on a Mac, then rerun this installer."
}

require_arm64() {
  is_arm64 || die "This installer currently supports Apple Silicon (arm64) only. Use an Apple Silicon Mac, then rerun this installer."
}

main() {
  require_macos
  require_arm64
  say "scaffold only"
}

if [ -z "${MUSIC_DL_INSTALLER_SOURCE_ONLY:-}" ]; then
  main "$@"
fi
