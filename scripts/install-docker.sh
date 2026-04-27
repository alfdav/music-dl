#!/usr/bin/env bash
# One-line Docker installer for music-dl headless/NAS use.
# Usage: curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-docker.sh | bash
set -euo pipefail

REPO_TARBALL_URL="${MUSIC_DL_SOURCE_TARBALL_URL:-https://github.com/alfdav/music-dl/archive/refs/heads/master.tar.gz}"
INSTALL_DIR="${MUSIC_DL_DOCKER_DIR:-$HOME/.local/share/music-dl/source}"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$1"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; exit 1; }
ok()  { printf '\033[1;32m==> %s\033[0m\n' "$1"; }

have_command() {
  command -v "$1" >/dev/null 2>&1
}

require_tools() {
  have_command curl || die "curl is required. Install curl, then rerun this installer."
  have_command tar || die "tar is required. Install tar, then rerun this installer."
  have_command docker || die "Docker is required. Install Docker, start it, then rerun this installer."
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required. Install Docker Compose, then rerun this installer."
}

require_safe_install_dir() {
  case "$INSTALL_DIR" in
    ""|"/"|"$HOME"|"$HOME/")
      die "Refusing unsafe install directory: ${INSTALL_DIR:-<empty>}"
      ;;
  esac
}

sync_source() {
  local tmpdir archive extracted parent
  tmpdir="$(mktemp -d)"
  archive="$tmpdir/music-dl.tar.gz"
  parent="$(dirname "$INSTALL_DIR")"
  trap 'rm -rf "$tmpdir"' RETURN

  say "Downloading music-dl source"
  curl -fSL --progress-bar -o "$archive" "$REPO_TARBALL_URL" \
    || die "Could not download music-dl source."

  tar -xzf "$archive" -C "$tmpdir" || die "Could not extract music-dl source."
  extracted="$(find "$tmpdir" -maxdepth 1 -type d -name 'music-dl-*' -print -quit)"
  [ -n "$extracted" ] || die "Could not find extracted music-dl source."

  mkdir -p "$parent" || die "Could not create $parent."
  rm -rf "$INSTALL_DIR" || die "Could not replace $INSTALL_DIR."
  mv "$extracted" "$INSTALL_DIR" || die "Could not install source into $INSTALL_DIR."
}

start_compose() {
  say "Building and starting music-dl"
  docker compose -f "$INSTALL_DIR/docker/docker-compose.yml" up gui -d --build \
    || die "Docker Compose failed. Check Docker, then rerun this installer."
}

main() {
  require_tools
  require_safe_install_dir
  sync_source
  start_compose
  ok "music-dl is running at http://localhost:8765"
  printf 'Source installed at %s\n' "$INSTALL_DIR"
}

main "$@"
