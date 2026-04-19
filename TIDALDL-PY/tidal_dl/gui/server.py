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

# ── Restart plumbing ──────────────────────────────────────────────────────────

_restart_requested: bool = False
_server_instance: uvicorn.Server | None = None


def request_restart() -> None:
    """Flag the current run loop iteration for restart."""
    global _restart_requested
    _restart_requested = True


# ── Public entry point ────────────────────────────────────────────────────────


def run(port: int = 8765, open_browser: bool = True) -> None:
    global _restart_requested, _server_instance

    url = f"http://localhost:{port}"
    if open_browser:
        webbrowser.open(url)

    # Bind 0.0.0.0 inside Docker so the host can reach us;
    # localhost everywhere else for security.
    host = "0.0.0.0" if os.environ.get("MUSIC_DL_BIND_ALL") else "127.0.0.1"

    while True:
        _restart_requested = False

        config = uvicorn.Config(
            "tidal_dl.gui:create_app",
            factory=True,
            host=host,
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        _server_instance = server

        asyncio.run(server.serve())

        _server_instance = None

        if not _restart_requested:
            break
