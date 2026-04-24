"""music-dl GUI — FastAPI application factory."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from tidal_dl.gui.api import api_router
from tidal_dl.gui.daemon import DaemonMetadata, write_metadata
from tidal_dl.gui.security import CSRFMiddleware, HostValidationMiddleware, generate_csrf_token

try:
    from tidal_dl import __version__ as _APP_VERSION
except Exception:
    _APP_VERSION = "0.0.0"

import sys as _sys

# PyInstaller onefile extracts datas to sys._MEIPASS; modules live in PYZ.
# Path(__file__).parent points into PYZ, not the extraction dir.
if getattr(_sys, "frozen", False) and hasattr(_sys, "_MEIPASS"):
    _STATIC_DIR = Path(_sys._MEIPASS) / "tidal_dl" / "gui" / "static"
else:
    _STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    port: int = 8765,
    daemon_meta: DaemonMetadata | None = None,
    write_daemon_metadata: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Restore Tidal OAuth session and capture event loop on server start."""
        import asyncio

        loop = asyncio.get_running_loop()
        from tidal_dl.gui.api.downloads import set_event_loop
        from tidal_dl.gui.api.upgrade import set_scan_event_loop

        set_event_loop(loop)
        set_scan_event_loop(loop)

        try:
            from tidal_dl.config import Tidal

            tidal = Tidal()
            tidal.login_token(quiet=True)
        except Exception:
            pass
        app.state.daemon_meta = app.state.daemon_meta.with_status("ready")
        if app.state.write_daemon_metadata:
            write_metadata(app.state.daemon_meta)
        yield

    app = FastAPI(title="music-dl", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    app.state.daemon_meta = daemon_meta or DaemonMetadata.for_current_process(
        port=port,
        mode="browser",
        status="starting",
    )
    app.state.write_daemon_metadata = write_daemon_metadata
    csrf_token = generate_csrf_token()
    app.state.csrf_token = csrf_token

    allowed_hosts = [f"localhost:{port}", f"127.0.0.1:{port}"]
    app.add_middleware(HostValidationMiddleware, allowed_hosts=allowed_hosts)
    app.add_middleware(CSRFMiddleware, csrf_token=csrf_token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://localhost:{port}", f"http://127.0.0.1:{port}"],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["X-CSRF-Token", "Content-Type"],
    )
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class TokenRefreshMiddleware(BaseHTTPMiddleware):
        _SKIP_PREFIXES = (
            "/api/settings", "/api/auth", "/api/setup",
            "/api/library/scan", "/api/queue",
        )

        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if path.startswith("/api/") and not any(
                path.startswith(p) for p in self._SKIP_PREFIXES
            ):
                try:
                    from tidal_dl.config import Tidal as _Tidal
                    _Tidal()._ensure_token_fresh()
                except Exception:
                    pass
            return await call_next(request)

    app.add_middleware(TokenRefreshMiddleware)
    app.include_router(api_router, prefix="/api")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        import time
        html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
        # Cache-bust static assets so browser always gets fresh JS/CSS
        v = str(int(time.time()))
        html = html.replace('/style.css', f'/style.css?v={v}')
        html = html.replace('/routes.js', f'/routes.js?v={v}')
        html = html.replace('/app.js', f'/app.js?v={v}')
        html = html.replace("__APP_VERSION__", _APP_VERSION)
        return HTMLResponse(html.replace("__CSRF_TOKEN__", csrf_token))

    app.mount("/", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    return app
