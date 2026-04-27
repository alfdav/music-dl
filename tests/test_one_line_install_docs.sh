#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README_FILE="$ROOT/README.md"
INSTALL_DOC="$ROOT/docs/release/install-instructions.md"
GITIGNORE="$ROOT/.gitignore"
INSTALL_SH="$ROOT/scripts/install.sh"
INSTALL_PS1="$ROOT/scripts/install.ps1"
INSTALL_DOCKER="$ROOT/scripts/install-docker.sh"

pass() { printf 'ok - %s\n' "$1"; }
fail() { printf 'not ok - %s\n' "$1"; exit 1; }

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "$haystack" in
    *"$needle"*) pass "$label" ;;
    *) fail "$label (missing=$needle)" ;;
  esac
}

assert_file() {
  local path="$1" label="$2"
  [ -f "$path" ] || fail "$label (missing=$path)"
  pass "$label"
}

readme_contents="$(<"$README_FILE")"
install_doc_contents="$(<"$INSTALL_DOC")"
gitignore_contents="$(<"$GITIGNORE")"
install_sh_contents="$(<"$INSTALL_SH")"

mac_linux_command="curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.sh | bash"
windows_command="irm https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.ps1 | iex"
docker_command="curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-docker.sh | bash"

assert_contains "$readme_contents" "## Install" "README has a top-level install section"
assert_contains "$readme_contents" "$mac_linux_command" "README exposes macOS/Linux one-liner"
assert_contains "$readme_contents" "$windows_command" "README exposes Windows PowerShell one-liner"
assert_contains "$readme_contents" "$docker_command" "README exposes headless Docker one-liner"

assert_contains "$install_doc_contents" "$mac_linux_command" "release docs expose macOS/Linux one-liner"
assert_contains "$install_doc_contents" "$windows_command" "release docs expose Windows PowerShell one-liner"
assert_contains "$install_doc_contents" "$docker_command" "release docs expose headless Docker one-liner"
assert_contains "$install_doc_contents" "- Windows: \`.msi\`" "release docs keep Windows expected asset"

assert_contains "$install_sh_contents" "install_linux_appimage" "install.sh has Linux AppImage installer"
assert_contains "$install_sh_contents" "\$HOME/.local/bin" "install.sh installs Linux AppImage into user bin"

assert_file "$INSTALL_PS1" "Windows installer script exists"
assert_file "$INSTALL_DOCKER" "Docker installer script exists"
install_docker_contents="$(<"$INSTALL_DOCKER")"
assert_contains "$install_docker_contents" "Refusing unsafe install directory" "Docker installer refuses unsafe install dirs"
assert_contains "$gitignore_contents" "!/scripts/install.ps1" "gitignore allows Windows installer script"
assert_contains "$gitignore_contents" "!/scripts/install-docker.sh" "gitignore allows Docker installer script"
