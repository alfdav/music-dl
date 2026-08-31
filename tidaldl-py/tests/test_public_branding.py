from pathlib import Path
import tomllib
from unittest.mock import patch

from tidal_dl import distribution_name
from tidal_dl.helper.path import path_config_base, path_file_token

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"


def test_public_branding_matches_music_dl(monkeypatch):
    monkeypatch.setenv("HOME", "/tmp/test-home")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("MUSIC_DL_CONFIG_DIR", raising=False)

    with PYPROJECT_PATH.open("rb") as f:
        project = tomllib.load(f)["project"]

    assert project["name"] == "music-dl"
    assert project["scripts"]["music-dl"] == "tidal_dl.cli:main"
    assert project["urls"]["repository"] == "https://github.com/alfdav/music-dl"
    assert path_config_base() == "/tmp/test-home/.config/music-dl"


def test_distribution_name_matches_public_package():
    assert distribution_name() == "music-dl"


def test_path_config_base_migrates_legacy_tidal_dl_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("MUSIC_DL_CONFIG_DIR", raising=False)

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
    monkeypatch.delenv("MUSIC_DL_CONFIG_DIR", raising=False)

    legacy_dir = tmp_path / ".config" / "tidal-dl"
    legacy_dir.mkdir(parents=True)
    current_dir = tmp_path / ".config" / "music-dl"

    with patch("tidal_dl.helper.path.shutil.move", side_effect=PermissionError("denied")):
        assert path_config_base() == str(current_dir)

    assert legacy_dir.exists()


def test_windows_token_path_is_stable_user_config_not_download_dir(monkeypatch):
    """Tokens live in the per-user config dir, never next to MusicDlQA downloads."""
    monkeypatch.delenv("MUSIC_DL_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setenv("HOMEDRIVE", "C:")
    monkeypatch.setenv("HOMEPATH", "Users/PLEX-MINI")

    base = path_config_base()
    token = path_file_token()

    assert base.endswith(str(Path(".config") / "music-dl"))
    assert token == str(Path(base) / "token.json")
    assert "MusicDlQA" not in token
    assert Path(token).parent == Path(base)
