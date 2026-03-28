"""Sidecar entry point for Tauri — boots FastAPI without opening a browser."""
import sys

import uvicorn


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    uvicorn.run(
        "tidal_dl.gui:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
