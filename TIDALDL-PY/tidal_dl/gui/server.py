"""Uvicorn launcher for the music-dl GUI."""
import os
import webbrowser

import uvicorn


def run(port: int = 8765, open_browser: bool = True) -> None:
    url = f"http://localhost:{port}"
    if open_browser:
        webbrowser.open(url)
    # Bind 0.0.0.0 inside Docker so the host can reach us;
    # localhost everywhere else for security.
    host = "0.0.0.0" if os.environ.get("MUSIC_DL_BIND_ALL") else "127.0.0.1"
    uvicorn.run(
        "tidal_dl.gui:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="warning",
    )
