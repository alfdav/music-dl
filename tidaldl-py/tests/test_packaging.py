from pathlib import Path

import toml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"


def test_pyproject_readme_points_to_existing_file():
    project = toml.load(PYPROJECT_PATH)["project"]
    readme_path = PROJECT_ROOT / project["readme"]

    assert readme_path.is_file(), f"Missing package README: {readme_path}"
