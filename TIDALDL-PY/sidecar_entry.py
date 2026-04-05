"""Sidecar entry point for Tauri — boots FastAPI without opening a browser.

PyInstaller onefile on macOS uses 'spawn' for multiprocessing. The child
re-executes this script, so freeze_support() must run before anything else
and the real work must be inside __name__ == '__main__'.
"""
import multiprocessing
import signal
import sys

multiprocessing.freeze_support()


def main() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    import asyncio

    import uvicorn

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    config = uvicorn.Config(
        "tidal_dl.gui:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
