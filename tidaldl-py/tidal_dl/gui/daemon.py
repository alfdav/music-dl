"""Local daemon runtime metadata and discovery helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import socket
import time
from collections.abc import Callable, Iterator
from typing import Literal
import urllib.error
import urllib.request

import uvicorn

from tidal_dl.helper.path import path_config_base

APP = "music-dl"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
HEALTH_PATH = "/api/server/health"
HEALTH_TIMEOUT_SEC = 2.0

DaemonStatus = Literal["starting", "ready", "stopping"]
DaemonMode = Literal["browser", "tauri-sidecar"]


@dataclass(frozen=True)
class DaemonMetadata:
    app: str
    version: str
    status: str
    pid: int
    host: str
    port: int
    base_url: str
    health_url: str
    mode: str
    started_at: float

    @classmethod
    def for_current_process(
        cls,
        *,
        port: int,
        mode: DaemonMode,
        status: DaemonStatus = "starting",
        host: str = DEFAULT_HOST,
        version: str | None = None,
    ) -> "DaemonMetadata":
        from tidal_dl import __version__

        actual_version = version or __version__
        base_url = f"http://{host}:{port}"
        return cls(
            app=APP,
            version=actual_version,
            status=status,
            pid=os.getpid(),
            host=host,
            port=port,
            base_url=base_url,
            health_url=f"{base_url}{HEALTH_PATH}",
            mode=mode,
            started_at=time.time(),
        )

    def with_status(self, status: DaemonStatus) -> "DaemonMetadata":
        return DaemonMetadata(**{**asdict(self), "status": status})


def metadata_path(config_dir: Path | None = None) -> Path:
    return (config_dir or Path(path_config_base())) / "daemon.json"


def write_metadata(meta: DaemonMetadata, *, config_dir: Path | None = None) -> None:
    path = metadata_path(config_dir=config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(meta), indent=2, sort_keys=True), encoding="utf-8")


def read_metadata(*, config_dir: Path | None = None) -> DaemonMetadata | None:
    path = metadata_path(config_dir=config_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return DaemonMetadata(**data)
    except (OSError, TypeError, ValueError):
        return None


def remove_metadata(meta: DaemonMetadata | None = None, *, config_dir: Path | None = None) -> None:
    path = metadata_path(config_dir=config_dir)
    current = read_metadata(config_dir=config_dir)
    if meta is not None and current is not None and current.pid != meta.pid:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_ready_music_dl(meta: DaemonMetadata) -> bool:
    try:
        with urllib.request.urlopen(meta.health_url, timeout=HEALTH_TIMEOUT_SEC) as response:
            if response.status < 200 or response.status >= 300:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, ValueError, urllib.error.URLError):
        return False
    return payload.get("app") == APP and payload.get("status") == "ready"


def clean_stale_metadata(
    *,
    config_dir: Path | None = None,
    pid_checker=pid_exists,
    ready_checker=is_ready_music_dl,
) -> bool:
    meta = read_metadata(config_dir=config_dir)
    if meta is None:
        return True
    if pid_checker(meta.pid):
        return True
    try:
        metadata_path(config_dir=config_dir).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def iter_candidate_ports(start: int) -> Iterator[int]:
    yield start
    for port in range(8766, 8866):
        if port != start:
            yield port


def select_port(
    requested_port: int,
    host: str = DEFAULT_HOST,
    *,
    port_checker: Callable[[str, int], bool] = port_is_free,
    candidates: Callable[[int], Iterator[int]] = iter_candidate_ports,
) -> int:
    for port in candidates(requested_port):
        if port_checker(host, port):
            return port
    raise RuntimeError("No free localhost port found for music-dl daemon")


def discover_ready_daemon(
    *,
    config_dir: Path | None = None,
    pid_checker=pid_exists,
    ready_checker=is_ready_music_dl,
) -> DaemonMetadata | None:
    meta = read_metadata(config_dir=config_dir)
    if meta is None:
        return None
    if pid_checker(meta.pid) and ready_checker(meta):
        return meta
    if not clean_stale_metadata(
        config_dir=config_dir,
        pid_checker=pid_checker,
        ready_checker=ready_checker,
    ):
        raise RuntimeError("Stale daemon metadata cleanup failed")
    return None


def make_uvicorn_config(meta: DaemonMetadata, *, bind_all: bool = False) -> uvicorn.Config:
    from tidal_dl.gui import create_app

    host = "0.0.0.0" if bind_all else meta.host

    def app_factory():
        return create_app(
            port=meta.port,
            daemon_meta=meta,
            write_daemon_metadata=True,
        )

    return uvicorn.Config(
        app_factory,
        factory=True,
        host=host,
        port=meta.port,
        log_level="warning",
    )
