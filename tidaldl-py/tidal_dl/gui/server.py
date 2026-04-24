"""Uvicorn launcher for the music-dl GUI (browser mode).

Supports a restart loop: the ``/api/server/restart`` endpoint calls
:func:`request_restart` then triggers a graceful uvicorn shutdown.
When ``serve()`` returns, this module re-enters the loop and boots a
fresh server on the same port.
"""

import asyncio
import os
import webbrowser

import uvicorn

from tidal_dl.gui.daemon import (
    DaemonMetadata,
    discover_ready_daemon,
    make_uvicorn_config,
    remove_metadata,
    select_port,
    write_metadata,
)

# ── Restart plumbing ──────────────────────────────────────────────────────────

_restart_requested: bool = False
_server_instance: uvicorn.Server | None = None


def request_restart() -> None:
    """Flag the current run loop iteration for restart."""
    global _restart_requested
    _restart_requested = True


# ── Public entry point ────────────────────────────────────────────────────────


def run(
    port: int = 8765,
    open_browser: bool = True,
    *,
    discoverer=discover_ready_daemon,
    browser_open=webbrowser.open,
    server_factory=uvicorn.Server,
) -> None:
    global _restart_requested, _server_instance

    existing = discoverer()
    if existing is not None:
        if open_browser:
            browser_open(existing.base_url)
        print(f"music-dl GUI: {existing.base_url}")
        return

    # Bind 0.0.0.0 inside Docker so the host can reach us;
    # localhost everywhere else for security.
    bind_all = bool(os.environ.get("MUSIC_DL_BIND_ALL"))
    actual_port = select_port(port)
    meta = DaemonMetadata.for_current_process(port=actual_port, mode="browser")
    if open_browser:
        browser_open(meta.base_url)
    print(f"music-dl GUI: {meta.base_url}")

    try:
        while True:
            _restart_requested = False
            write_metadata(meta.with_status("starting"))

            config = make_uvicorn_config(meta, bind_all=bind_all)
            server = server_factory(config)
            _server_instance = server

            asyncio.run(server.serve())

            _server_instance = None

            if not _restart_requested:
                break
    finally:
        _server_instance = None
        remove_metadata(meta)
