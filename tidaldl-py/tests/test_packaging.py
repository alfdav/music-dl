import json
import re
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
PACKAGE_JSON_PATH = PROJECT_ROOT / "package.json"
PACKAGE_LOCK_PATH = PROJECT_ROOT / "package-lock.json"
CARGO_LOCK_PATH = PROJECT_ROOT / "src-tauri" / "Cargo.lock"
TAURI_CONFIG_PATH = PROJECT_ROOT / "src-tauri" / "tauri.conf.json"
LOOPBACK_CAPABILITY_PATH = PROJECT_ROOT / "src-tauri" / "capabilities" / "loopback.json"
TAURI_BUILD_PATH = PROJECT_ROOT / "src-tauri" / "build.rs"

_CARGO_PACKAGE_RE = re.compile(
    r'(?ms)^name = "([^"]+)"\nversion = "([^"]+)"',
)

DESKTOP_COMMANDS = {
    "get-updater-state",
    "check-for-updates",
    "install-update",
    "sidecar-status",
    "stop-sidecar",
    "start-sidecar",
    "restart-sidecar",
}


def test_pyproject_readme_points_to_existing_file():
    with PYPROJECT_PATH.open("rb") as f:
        project = tomllib.load(f)["project"]
    readme_path = PROJECT_ROOT / project["readme"]

    assert readme_path.is_file(), f"Missing package README: {readme_path}"


def test_tauri_build_checks_qol_static_markers():
    config = TAURI_CONFIG_PATH.read_text()
    build_command = json.loads(config)["build"]["beforeBuildCommand"]

    assert '"withGlobalTauri": true' in config
    assert "tidal_dl/gui/static/app.js" not in build_command
    assert "from tests.gui_js_source import read_gui_js" in build_command
    assert "js=read_gui_js()" in build_command
    assert "Continue Listening" in build_command
    assert "Smart Shuffle" in build_command
    assert "_libraryAlbumCache" in build_command


def test_loopback_ui_has_only_required_desktop_permissions():
    capability = json.loads(LOOPBACK_CAPABILITY_PATH.read_text(encoding="utf-8"))
    permissions = set(capability["permissions"])

    assert capability["local"] is False
    assert capability["windows"] == ["main"]
    assert capability["remote"] == {"urls": ["http://127.0.0.1:*"]}
    assert permissions == {
        "core:event:default",
        "shell:allow-open",
        *(f"allow-{command}" for command in DESKTOP_COMMANDS),
    }
    assert "process:allow-restart" not in permissions
    assert "shell:allow-spawn" not in permissions


def test_tauri_build_registers_all_desktop_commands_for_acl():
    build_source = TAURI_BUILD_PATH.read_text(encoding="utf-8")

    assert "AppManifest::new().commands" in build_source
    for command in DESKTOP_COMMANDS:
        assert f'"{command.replace("-", "_")}"' in build_source


def _major_minor(version: str) -> tuple[int, int]:
    parts = version.lstrip("v^~>=< ").split(".")
    return int(parts[0]), int(parts[1])


def _cargo_lock_versions(names: set[str]) -> dict[str, str]:
    text = CARGO_LOCK_PATH.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for name, version in _CARGO_PACKAGE_RE.findall(text):
        if name in names:
            found[name] = version
    return found


def _npm_lock_versions() -> dict[str, str]:
    lock = json.loads(PACKAGE_LOCK_PATH.read_text(encoding="utf-8"))
    packages = lock.get("packages", {})
    found: dict[str, str] = {}
    for key, meta in packages.items():
        if not key.startswith("node_modules/@tauri-apps/"):
            continue
        name = key.removeprefix("node_modules/")
        if name.count("/") > 1:
            continue
        version = meta.get("version")
        if version:
            found[name] = version
    return found


def test_tauri_npm_plugins_match_rust_crate_major_minor():
    """edge-desktop `bunx tauri build` aborts before compile when these drift."""
    package = json.loads(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
    npm_direct = {
        **package.get("dependencies", {}),
        **package.get("devDependencies", {}),
    }
    npm_lock = _npm_lock_versions()
    rust_names = {"tauri"}
    pairs: set[tuple[str, str]] = set()
    if "@tauri-apps/api" in npm_lock:
        pairs.add(("tauri", "@tauri-apps/api"))
    for npm_name in (*npm_direct, *npm_lock):
        if not npm_name.startswith("@tauri-apps/plugin-"):
            continue
        rust_name = "tauri-plugin-" + npm_name.removeprefix("@tauri-apps/plugin-")
        rust_names.add(rust_name)
        pairs.add((rust_name, npm_name))

    rust_versions = _cargo_lock_versions(rust_names)
    mismatches = []
    for rust_name, npm_name in pairs:
        rust_version = rust_versions.get(rust_name)
        npm_version = npm_lock.get(npm_name)
        assert rust_version, f"missing Cargo.lock package {rust_name}"
        assert npm_version, f"missing package-lock.json package {npm_name}"
        if _major_minor(rust_version) != _major_minor(npm_version):
            mismatches.append(
                f"{rust_name} (v{rust_version}) : {npm_name} (v{npm_version})"
            )

    assert not mismatches, (
        "Found version mismatched Tauri packages. Make sure the NPM package "
        "and Rust crate versions are on the same major/minor releases:\n"
        + "\n".join(mismatches)
    )
