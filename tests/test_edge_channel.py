import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.edge_channel import (
    apply_edge_version,
    build_manifest,
    edge_version,
)


def write_project(root: Path) -> None:
    tauri_dir = root / "tidaldl-py" / "src-tauri"
    tauri_dir.mkdir(parents=True)
    (root / "tidaldl-py" / "pyproject.toml").write_text(
        '[project]\nname = "music-dl"\nversion = "1.6.1"\n',
        encoding="utf-8",
    )
    (tauri_dir / "Cargo.toml").write_text(
        '[package]\nname = "music-dl"\nversion = "1.6.1"\n',
        encoding="utf-8",
    )
    (tauri_dir / "tauri.conf.json").write_text(
        json.dumps(
            {
                "productName": "music-dl",
                "version": "1.6.1",
                "plugins": {
                    "updater": {
                        "endpoints": [
                            "https://github.com/alfdav/music-dl/releases/latest/download/latest.json"
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_edge_version_bumps_patch_and_uses_run_number():
    assert edge_version("1.6.1", "42") == "1.6.2-edge.42"


def test_apply_edge_version_updates_app_versions_and_endpoint(tmp_path):
    write_project(tmp_path)

    version = apply_edge_version(
        tmp_path,
        run_number="42",
        endpoint="https://github.com/alfdav/music-dl/releases/download/edge/latest.json",
    )

    assert version == "1.6.2-edge.42"
    assert 'version = "1.6.2-edge.42"' in (
        tmp_path / "tidaldl-py" / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert 'version = "1.6.2-edge.42"' in (
        tmp_path / "tidaldl-py" / "src-tauri" / "Cargo.toml"
    ).read_text(encoding="utf-8")

    tauri_config = json.loads(
        (tmp_path / "tidaldl-py" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    assert tauri_config["version"] == "1.6.2-edge.42"
    assert tauri_config["plugins"]["updater"]["endpoints"] == [
        "https://github.com/alfdav/music-dl/releases/download/edge/latest.json"
    ]


def test_build_manifest_maps_updater_artifacts_to_tauri_platforms(tmp_path):
    artifacts = tmp_path / "artifacts"
    (artifacts / "linux").mkdir(parents=True)
    (artifacts / "macos").mkdir()
    (artifacts / "windows").mkdir()

    (artifacts / "linux" / "music-dl_1.6.2-edge.42_amd64.AppImage").write_text(
        "linux", encoding="utf-8"
    )
    (artifacts / "linux" / "music-dl_1.6.2-edge.42_amd64.AppImage.sig").write_text(
        "linux-signature\n", encoding="utf-8"
    )
    (artifacts / "macos" / "music-dl.app.tar.gz").write_text(
        "macos", encoding="utf-8"
    )
    (artifacts / "macos" / "music-dl.app.tar.gz.sig").write_text(
        "macos-signature\n", encoding="utf-8"
    )
    (artifacts / "windows" / "music-dl_1.6.2-edge.42_x64_en-US.msi").write_text(
        "windows", encoding="utf-8"
    )
    (artifacts / "windows" / "music-dl_1.6.2-edge.42_x64_en-US.msi.sig").write_text(
        "windows-signature\n", encoding="utf-8"
    )

    manifest = build_manifest(
        artifacts_dir=artifacts,
        version="1.6.2-edge.42",
        base_url="https://github.com/alfdav/music-dl/releases/download/edge",
        notes="Rolling edge build",
        pub_date="2026-04-27T00:00:00Z",
    )

    assert manifest["version"] == "1.6.2-edge.42"
    assert manifest["platforms"]["linux-x86_64"] == {
        "url": "https://github.com/alfdav/music-dl/releases/download/edge/music-dl_1.6.2-edge.42_amd64.AppImage",
        "signature": "linux-signature",
    }
    assert manifest["platforms"]["darwin-aarch64"] == {
        "url": "https://github.com/alfdav/music-dl/releases/download/edge/music-dl.app.tar.gz",
        "signature": "macos-signature",
    }
    assert manifest["platforms"]["windows-x86_64"] == {
        "url": "https://github.com/alfdav/music-dl/releases/download/edge/music-dl_1.6.2-edge.42_x64_en-US.msi",
        "signature": "windows-signature",
    }
