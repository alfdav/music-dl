"""Uvicorn launcher for the music-dl GUI."""
import webbrowser

import uvicorn


def run(port: int = 8765, open_browser: bool = True) -> None:
    url = f"http://localhost:{port}"
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(
        "tidal_dl.gui:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
