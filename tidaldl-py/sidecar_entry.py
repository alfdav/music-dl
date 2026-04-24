"""Sidecar entry point for Tauri — boots FastAPI without opening a browser.

PyInstaller onefile on macOS uses 'spawn' for multiprocessing. The child
re-executes this script, so freeze_support() must run before anything else
and the real work must be inside __name__ == '__main__'.
"""
import multiprocessing
import signal
import sys

multiprocessing.freeze_support()


def _frozen_env_setup() -> None:
    """Configure environment for PyInstaller frozen mode on macOS."""
    if not getattr(sys, "frozen", False):
        return
    import os

    # SSL: certifi hook was removed from pyinstaller-hooks-contrib.
    # Finder-launched apps don't inherit shell env vars.
    if "SSL_CERT_FILE" not in os.environ:
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except ImportError:
            pass

    # Locale: Finder-launched frozen apps get US-ASCII instead of UTF-8.
    if not os.environ.get("LANG"):
        os.environ["LANG"] = "en_US.UTF-8"
    if not os.environ.get("LC_CTYPE"):
        os.environ["LC_CTYPE"] = "en_US.UTF-8"


def main() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    _frozen_env_setup()

    import asyncio

    from tidal_dl.gui.daemon import DaemonMetadata, make_uvicorn_config, remove_metadata, select_port, write_metadata

    requested_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    port = select_port(requested_port)
    meta = DaemonMetadata.for_current_process(port=port, mode="tauri-sidecar")
    write_metadata(meta.with_status("starting"))
    try:
        config = make_uvicorn_config(meta)
        server = asyncio.run(_serve(config))
    finally:
        remove_metadata(meta)


async def _serve(config):
    import uvicorn

    server = uvicorn.Server(config)
    await server.serve()
    return server


if __name__ == "__main__":
    main()
