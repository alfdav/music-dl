from pathlib import Path
from unittest.mock import patch

import toml

from tidal_dl import distribution_name
from tidal_dl.helper.path import path_config_base

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"


def test_public_branding_matches_music_dl(monkeypatch):
    monkeypatch.setenv("HOME", "/tmp/test-home")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    project = toml.load(PYPROJECT_PATH)["project"]

    assert project["name"] == "music-dl"
    assert project["scripts"]["music-dl"] == "tidal_dl.cli:main"
    assert project["urls"]["repository"] == "https://github.com/alfdav/music-dl"
    assert path_config_base() == "/tmp/test-home/.config/music-dl"


def test_distribution_name_matches_public_package():
    assert distribution_name() == "music-dl"


def test_path_config_base_migrates_legacy_tidal_dl_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    legacy_dir = tmp_path / ".config" / "tidal-dl"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "settings.json"
    legacy_file.write_text("{}", encoding="utf-8")

    current_dir = tmp_path / ".config" / "music-dl"

    assert path_config_base() == str(current_dir)
    assert current_dir.joinpath("settings.json").read_text(encoding="utf-8") == "{}"
    assert not legacy_dir.exists()


def test_path_config_base_ignores_legacy_migration_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    legacy_dir = tmp_path / ".config" / "tidal-dl"
    legacy_dir.mkdir(parents=True)
    current_dir = tmp_path / ".config" / "music-dl"

    with patch("tidal_dl.helper.path.shutil.move", side_effect=PermissionError("denied")):
        assert path_config_base() == str(current_dir)

    assert legacy_dir.exists()
