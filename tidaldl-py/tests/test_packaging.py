from pathlib import Path

import toml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
TAURI_CONFIG_PATH = PROJECT_ROOT / "src-tauri" / "tauri.conf.json"


def test_pyproject_readme_points_to_existing_file():
    project = toml.load(PYPROJECT_PATH)["project"]
    readme_path = PROJECT_ROOT / project["readme"]

    assert readme_path.is_file(), f"Missing package README: {readme_path}"


def test_tauri_build_checks_qol_static_markers():
    config = TAURI_CONFIG_PATH.read_text()

    assert "Continue Listening" in config
    assert "Smart Shuffle" in config
    assert "_libraryAlbumCache" in config
