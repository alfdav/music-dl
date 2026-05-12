import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.release_version import (
    bump_version,
    check_release_versions,
    current_version,
    parse_version,
    set_release_version,
)


def write_project(root: Path, *, version: str = "1.6.7", changelog: str | None = None) -> None:
    tauri_dir = root / "tidaldl-py" / "src-tauri"
    tauri_dir.mkdir(parents=True)
    (root / "tidaldl-py").mkdir(exist_ok=True)
    (root / "tidaldl-py" / "pyproject.toml").write_text(
        f'[project]\nname = "music-dl"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (tauri_dir / "Cargo.toml").write_text(
        f'[package]\nname = "music-dl"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (tauri_dir / "tauri.conf.json").write_text(
        json.dumps({"productName": "music-dl", "version": version}),
        encoding="utf-8",
    )
    (root / "tidaldl-py" / "updatelog.md").write_text(
        changelog
        or "# music-dl changelog\n\n## Unreleased\n\n- Fix startup.\n\n## v1.6.7 (2026-05-12)\n",
        encoding="utf-8",
    )


def test_parse_version_rejects_four_part_versions():
    with pytest.raises(ValueError, match="X.Y.Z"):
        parse_version("1.6.6.1")


def test_bump_version_updates_requested_part():
    assert bump_version("1.6.7", "patch") == "1.6.8"
    assert bump_version("1.6.7", "minor") == "1.7.0"
    assert bump_version("1.6.7", "major") == "2.0.0"


def test_check_release_versions_requires_all_files_to_agree(tmp_path):
    write_project(tmp_path)
    cargo = tmp_path / "tidaldl-py" / "src-tauri" / "Cargo.toml"
    cargo.write_text(
        '[package]\nname = "music-dl"\nversion = "1.6.8"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Version files disagree"):
        check_release_versions(tmp_path)


def test_set_release_version_updates_metadata_and_changelog_without_lock(tmp_path):
    write_project(tmp_path)

    set_release_version(
        tmp_path,
        "1.6.8",
        release_date=date(2026, 5, 13),
        lock=False,
    )

    assert current_version(tmp_path) == "1.6.8"
    assert 'version = "1.6.8"' in (tmp_path / "tidaldl-py" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert 'version = "1.6.8"' in (
        tmp_path / "tidaldl-py" / "src-tauri" / "Cargo.toml"
    ).read_text(encoding="utf-8")
    assert json.loads(
        (tmp_path / "tidaldl-py" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )["version"] == "1.6.8"
    assert "## v1.6.8 (2026-05-13)" in (
        tmp_path / "tidaldl-py" / "updatelog.md"
    ).read_text(encoding="utf-8")


def test_set_release_version_requires_unreleased_changelog(tmp_path):
    write_project(tmp_path, changelog="# music-dl changelog\n\n## v1.6.7 (2026-05-12)\n")

    with pytest.raises(ValueError, match="No '## Unreleased' section"):
        set_release_version(tmp_path, "1.6.8", lock=False)

    assert current_version(tmp_path) == "1.6.7"


def test_cli_check_reports_current_version(tmp_path):
    write_project(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "release_version.py"),
            "--root",
            str(tmp_path),
            "check",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.strip() == "Release version files agree: 1.6.7"


def test_cli_reports_missing_unreleased_without_traceback(tmp_path):
    write_project(tmp_path, changelog="# music-dl changelog\n\n## v1.6.7 (2026-05-12)\n")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "release_version.py"),
            "--root",
            str(tmp_path),
            "bump",
            "patch",
            "--no-lock",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr.strip() == "error: No '## Unreleased' section found in updatelog.md"
    assert "Traceback" not in result.stderr
    assert current_version(tmp_path) == "1.6.7"
