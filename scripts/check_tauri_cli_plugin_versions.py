#!/usr/bin/env python3
"""Fail if `bunx tauri info` reports NPM/Rust Tauri plugin major/minor drift.

This is the same `check_mismatched_packages` path `bunx tauri build` uses
on edge-desktop. `tauri info` prints the error but still exits 0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MISMATCH = "Found version mismatched Tauri packages"


def frontend_dir() -> Path:
    here = Path(__file__).resolve()
    repo = here.parents[1]
    candidate = repo / "tidaldl-py"
    if (candidate / "package.json").is_file():
        return candidate
    cwd = Path.cwd()
    if (cwd / "package.json").is_file() and (cwd / "src-tauri").is_dir():
        return cwd
    raise SystemExit("could not find tidaldl-py frontend directory")


def main() -> int:
    proc = subprocess.run(
        ["bunx", "tauri", "info"],
        cwd=frontend_dir(),
        text=True,
        capture_output=True,
        check=False,
    )
    output = f"{proc.stdout}{proc.stderr}"
    sys.stdout.write(output)
    if MISMATCH in output:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
