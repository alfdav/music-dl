import os
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "restart-gui.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_restart_gui_script_resolves_python_before_chdir(tmp_path):
    repo = tmp_path / "repo"
    scripts_dir = repo / "scripts"
    app_dir = repo / "TIDALDL-PY"
    venv_bin = app_dir / ".venv" / "bin"
    fake_bin = tmp_path / "fake-bin"
    log_file = tmp_path / "python.log"

    scripts_dir.mkdir(parents=True)
    venv_bin.mkdir(parents=True)
    fake_bin.mkdir(parents=True)

    shutil.copy2(SCRIPT, scripts_dir / "restart-gui.sh")

    _write_executable(
        venv_bin / "python",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$0 $*\" > {log_file!s}\nexit 0\n",
    )
    _write_executable(fake_bin / "lsof", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", "./scripts/restart-gui.sh"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    logged = log_file.read_text(encoding="utf-8")
    invoked_path = Path(logged.split(" ", 1)[0]).resolve()
    assert invoked_path == (venv_bin / "python").resolve()
    assert "from tidal_dl.gui.server import run; run(open_browser=False)" in logged
