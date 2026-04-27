#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


EDGE_ENDPOINT = "https://github.com/alfdav/music-dl/releases/download/edge/latest.json"


def _version_parts(current_version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+._].*)?", current_version)
    if not match:
        raise ValueError(f"Unsupported version: {current_version}")
    return tuple(int(part) for part in match.groups())


def edge_version(current_version: str, run_number: str) -> str:
    major, minor, patch = _version_parts(current_version)
    return f"{major}.{minor}.{patch + 1}-edge.{run_number}"


def python_edge_version(current_version: str, run_number: str) -> str:
    major, minor, patch = _version_parts(current_version)
    return f"{major}.{minor}.{patch + 1}.dev{run_number}"


def replace_version_assignment(text: str, version: str) -> str:
    return re.sub(
        r'(?m)^(version\s*=\s*)"[^"]+"',
        rf'\g<1>"{version}"',
        text,
        count=1,
    )


def apply_edge_version(root: Path, run_number: str, endpoint: str = EDGE_ENDPOINT) -> str:
    pyproject = root / "tidaldl-py" / "pyproject.toml"
    cargo_toml = root / "tidaldl-py" / "src-tauri" / "Cargo.toml"
    tauri_conf = root / "tidaldl-py" / "src-tauri" / "tauri.conf.json"

    pyproject_text = pyproject.read_text(encoding="utf-8")
    current_match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject_text)
    if not current_match:
        raise ValueError(f"Could not find project version in {pyproject}")

    version = edge_version(current_match.group(1), run_number)
    python_version = python_edge_version(current_match.group(1), run_number)
    pyproject.write_text(replace_version_assignment(pyproject_text, python_version), encoding="utf-8")
    cargo_toml.write_text(
        replace_version_assignment(cargo_toml.read_text(encoding="utf-8"), version),
        encoding="utf-8",
    )

    config = json.loads(tauri_conf.read_text(encoding="utf-8"))
    config["version"] = version
    config.setdefault("plugins", {}).setdefault("updater", {})["endpoints"] = [endpoint]
    tauri_conf.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return version


def first_file(root: Path, pattern: str, *, exclude_suffix: str | None = None) -> Path:
    matches = sorted(root.rglob(pattern))
    if exclude_suffix:
        matches = [path for path in matches if not path.name.endswith(exclude_suffix)]
    if not matches:
        raise FileNotFoundError(f"No artifact matching {pattern} under {root}")
    return matches[0]


def signature_for(path: Path) -> str:
    sig_path = path.with_name(path.name + ".sig")
    if not sig_path.exists():
        raise FileNotFoundError(f"Missing signature for {path}")
    return sig_path.read_text(encoding="utf-8").strip()


def platform_entry(path: Path, base_url: str) -> dict[str, str]:
    return {
        "url": f"{base_url.rstrip('/')}/{path.name}",
        "signature": signature_for(path),
    }


def build_manifest(
    artifacts_dir: Path,
    version: str,
    base_url: str,
    notes: str,
    pub_date: str,
) -> dict[str, object]:
    linux_appimage = first_file(artifacts_dir, "*.AppImage", exclude_suffix=".sig")
    macos_archive = first_file(artifacts_dir, "*.app.tar.gz")
    windows_msi = first_file(artifacts_dir, "*.msi")

    return {
        "version": version,
        "notes": notes,
        "pub_date": pub_date,
        "platforms": {
            "linux-x86_64": platform_entry(linux_appimage, base_url),
            "darwin-aarch64": platform_entry(macos_archive, base_url),
            "windows-x86_64": platform_entry(windows_msi, base_url),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--root", type=Path, default=Path.cwd())
    prepare.add_argument("--run-number", required=True)
    prepare.add_argument("--endpoint", default=EDGE_ENDPOINT)
    prepare.add_argument("--output")

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--artifacts-dir", type=Path, required=True)
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--base-url", required=True)
    manifest.add_argument("--notes", default="Rolling edge build from master.")
    manifest.add_argument("--pub-date")
    manifest.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        version = apply_edge_version(args.root, args.run_number, args.endpoint)
        if args.output:
            Path(args.output).write_text(version + "\n", encoding="utf-8")
        else:
            print(version)
        return

    pub_date = args.pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_json = build_manifest(
        artifacts_dir=args.artifacts_dir,
        version=args.version,
        base_url=args.base_url,
        notes=args.notes,
        pub_date=pub_date,
    )
    args.output.write_text(json.dumps(manifest_json, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
