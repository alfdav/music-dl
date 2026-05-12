#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
VERSION_ASSIGNMENT_RE = re.compile(r'(?m)^(version\s*=\s*)"([^"]+)"')
UNRELEASED_RE = re.compile(r"(?m)^## Unreleased\s*$")


@dataclass(frozen=True)
class ReleaseFiles:
    pyproject: Path
    cargo_toml: Path
    tauri_conf: Path
    changelog: Path


def release_files(root: Path) -> ReleaseFiles:
    return ReleaseFiles(
        pyproject=root / "tidaldl-py" / "pyproject.toml",
        cargo_toml=root / "tidaldl-py" / "src-tauri" / "Cargo.toml",
        tauri_conf=root / "tidaldl-py" / "src-tauri" / "tauri.conf.json",
        changelog=root / "tidaldl-py" / "updatelog.md",
    )


def parse_version(version: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(version)
    if not match:
        raise ValueError(f"Stable releases must use X.Y.Z SemVer, got: {version}")
    return tuple(int(part) for part in match.groups())


def bump_version(current: str, part: str) -> str:
    major, minor, patch = parse_version(current)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unsupported bump part: {part}")


def read_toml_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = VERSION_ASSIGNMENT_RE.search(text)
    if not match:
        raise ValueError(f"Could not find version assignment in {path}")
    return match.group(2)


def read_versions(root: Path) -> dict[str, str]:
    files = release_files(root)
    config = json.loads(files.tauri_conf.read_text(encoding="utf-8"))
    return {
        str(files.pyproject): read_toml_version(files.pyproject),
        str(files.cargo_toml): read_toml_version(files.cargo_toml),
        str(files.tauri_conf): str(config.get("version", "")),
    }


def current_version(root: Path) -> str:
    versions = read_versions(root)
    unique = set(versions.values())
    if len(unique) != 1:
        details = "\n".join(f"- {path}: {version}" for path, version in versions.items())
        raise ValueError(f"Version files disagree:\n{details}")
    version = unique.pop()
    parse_version(version)
    return version


def replace_toml_version(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = VERSION_ASSIGNMENT_RE.subn(rf'\g<1>"{version}"', text, count=1)
    if count != 1:
        raise ValueError(f"Could not replace version assignment in {path}")
    path.write_text(updated, encoding="utf-8")


def replace_tauri_version(path: Path, version: str) -> None:
    config = json.loads(path.read_text(encoding="utf-8"))
    config["version"] = version
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def update_changelog(path: Path, version: str, release_date: date) -> None:
    text = path.read_text(encoding="utf-8")
    if not UNRELEASED_RE.search(text):
        raise ValueError("No '## Unreleased' section found in updatelog.md")
    updated, count = UNRELEASED_RE.subn(
        f"## v{version} ({release_date.isoformat()})",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("Could not update updatelog.md")
    path.write_text(updated, encoding="utf-8")


def ensure_changelog_has_unreleased(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if not UNRELEASED_RE.search(text):
        raise ValueError("No '## Unreleased' section found in updatelog.md")


def local_tag_exists(root: Path, version: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/tags/v{version}"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def run_uv_lock(root: Path) -> None:
    subprocess.run(["uv", "lock", "--project", "tidaldl-py"], cwd=root, check=True)


def set_release_version(
    root: Path,
    version: str,
    *,
    release_date: date | None = None,
    lock: bool = True,
) -> None:
    parse_version(version)
    current_version(root)
    if local_tag_exists(root, version):
        raise ValueError(f"Local tag already exists: v{version}")

    files = release_files(root)
    release_date = release_date or date.today()
    ensure_changelog_has_unreleased(files.changelog)
    replace_toml_version(files.pyproject, version)
    replace_toml_version(files.cargo_toml, version)
    replace_tauri_version(files.tauri_conf, version)
    update_changelog(files.changelog, version, release_date)
    if lock:
        run_uv_lock(root)


def check_release_versions(root: Path) -> str:
    return current_version(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare stable music-dl release versions.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    bump = subparsers.add_parser("bump", help="Bump the current stable version.")
    bump.add_argument("part", choices=("major", "minor", "patch"))
    bump.add_argument("--date", default=None, help="Release date, YYYY-MM-DD. Defaults to today.")
    bump.add_argument("--no-lock", action="store_true", help="Skip uv lock update.")

    set_cmd = subparsers.add_parser("set", help="Set an explicit stable version.")
    set_cmd.add_argument("version")
    set_cmd.add_argument("--date", default=None, help="Release date, YYYY-MM-DD. Defaults to today.")
    set_cmd.add_argument("--no-lock", action="store_true", help="Skip uv lock update.")

    subparsers.add_parser("check", help="Verify stable version files agree.")
    return parser


def parse_release_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        if args.command == "check":
            version = check_release_versions(root)
            print(f"Release version files agree: {version}")
            return

        if args.command == "bump":
            version = bump_version(current_version(root), args.part)
        else:
            version = args.version

        set_release_version(
            root,
            version,
            release_date=parse_release_date(args.date),
            lock=not args.no_lock,
        )
    except ValueError as exc:
        parser.exit(1, f"error: {exc}\n")

    print(f"Prepared v{version}")


if __name__ == "__main__":
    main()
