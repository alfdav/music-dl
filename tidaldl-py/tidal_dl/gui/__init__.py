"""music-dl GUI — FastAPI application factory."""
from contextlib import asynccontextmanager
from pathlib import Path
import threading

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
    job_db_path: Path | None = None,
    daemon_meta: DaemonMetadata | None = None,
    write_daemon_metadata: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Open the job DB, recover the queue, then mark ready.

        Tidal restore and Discord bot start run after ready so a dead
        network or first-run bun install cannot pin the Tauri spinner.
        """
        import asyncio

        loop = asyncio.get_running_loop()
        from tidal_dl.gui.api.bot_control import start_configured_bot, stop_running_bot
        from tidal_dl.gui.api.upgrade import set_scan_event_loop
        from tidal_dl.gui.services.download_job_service import DownloadJobService

        service = DownloadJobService(db_path=job_db_path)
        service.events.set_event_loop(loop)
        app.state.download_jobs = service
        set_scan_event_loop(loop)

        app.state.source_restore_attempted = False
        app.state.source_restored = False
        app.state.source_restore_error = None
        app.state.daemon_meta = app.state.daemon_meta.with_status("ready")
        if app.state.write_daemon_metadata:
            write_metadata(app.state.daemon_meta)

        def _restore_tidal_source() -> None:
            try:
                from tidal_dl.config import Settings, Tidal
                from tidal_dl.gui.api.settings import TOKEN_KEEPALIVE_WINDOW_SEC, keep_tidal_session_alive

                tidal = Tidal(Settings())
                app.state.source_restore_attempted = True
                app.state.source_restored = tidal.resolve_source(
                    lambda _message: None,
                    allow_interactive_login=False,
                )
                if app.state.source_restored:
                    tidal.token_persist()
                keep_tidal_session_alive(tidal, refresh_window_sec=TOKEN_KEEPALIVE_WINDOW_SEC)
            except Exception as exc:
                app.state.source_restore_attempted = True
                app.state.source_restore_error = str(exc)

        after_ready: list[threading.Thread] = []
        shutting_down = threading.Event()

        def _start_bot_after_ready() -> None:
            if shutting_down.is_set():
                return
            start_configured_bot(app)

        def _token_keepalive() -> None:
            from tidal_dl.gui.api.settings import run_token_keepalive

            run_token_keepalive(shutting_down)

        after_ready.append(
            threading.Thread(
                target=_restore_tidal_source,
                name="tidal-source-restore",
                daemon=True,
            )
        )
        after_ready.append(
            threading.Thread(
                target=_token_keepalive,
                name="tidal-token-keepalive",
                daemon=True,
            )
        )
        after_ready.append(
            threading.Thread(
                target=_start_bot_after_ready,
                name="discord-bot-start",
                daemon=True,
            )
        )
        for thread in after_ready:
            thread.start()
        try:
            yield
        finally:
            shutting_down.set()
            for thread in after_ready:
                thread.join(timeout=2)
            stop_running_bot(app)
            service.stop_worker()

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
            "/api/settings", "/api/setup",
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
        for asset in ('routes.js', 'api.js', 'views.js', 'player.js'):
            html = html.replace(f'/{asset}', f'/{asset}?v={v}')
        html = html.replace("__APP_VERSION__", _APP_VERSION)
        return HTMLResponse(html.replace("__CSRF_TOKEN__", csrf_token))

    app.mount("/", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    return app
