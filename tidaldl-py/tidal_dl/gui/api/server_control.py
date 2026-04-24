"""Server lifecycle API — health check and restart (browser mode)."""

import sys
import time

from fastapi import APIRouter, HTTPException, Request
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse

router = APIRouter(prefix="/server", tags=["server"])


@router.get("/health")
async def health(request: Request):
    """Structured readiness probe for daemon clients."""
    meta = request.app.state.daemon_meta
    return {
        "app": meta.app,
        "version": meta.version,
        "status": meta.status,
        "pid": meta.pid,
        "host": meta.host,
        "port": meta.port,
        "mode": meta.mode,
        "started_at": meta.started_at,
    }


@router.post("/restart")
async def restart():
    """Trigger a graceful server restart.

    Only works in browser mode (``music-dl gui``).  In sidecar / Tauri mode
    the desktop shell manages the process lifecycle, so this returns 400.
    """
    if getattr(sys, "frozen", False):
        raise HTTPException(
            status_code=400,
            detail="Restart is managed by the desktop app",
        )

    # Import lazily so the module-level reference is resolved at call time
    import tidal_dl.gui.server as srv

    srv.request_restart()

    # BackgroundTask runs *after* the response is fully sent to the client,
    # avoiding the race where call_later fires before the HTTP body is flushed.
    return JSONResponse(
        {"status": "restarting"},
        background=BackgroundTask(_trigger_shutdown),
    )


def _trigger_shutdown() -> None:
    """Set the uvicorn exit flag so ``serve()`` returns cleanly."""
    # Small grace period for the response to be fully flushed by the OS
    time.sleep(0.2)

    import tidal_dl.gui.server as srv

    if srv._server_instance is not None:
        srv._server_instance.should_exit = True
