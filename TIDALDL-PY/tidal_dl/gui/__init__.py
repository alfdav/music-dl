"""music-dl GUI — FastAPI application factory."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from tidal_dl.gui.api import api_router
from tidal_dl.gui.security import CSRFMiddleware, HostValidationMiddleware, generate_csrf_token

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(port: int = 8765) -> FastAPI:
    app = FastAPI(title="music-dl", docs_url="/api/docs", redoc_url=None)
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
        _TIDAL_PATHS = ("/api/search", "/api/download", "/api/playlists")

        async def dispatch(self, request: Request, call_next):
            if any(request.url.path.startswith(p) for p in self._TIDAL_PATHS):
                try:
                    from tidal_dl.config import Tidal as _Tidal
                    _Tidal()._ensure_token_fresh()
                except Exception:
                    pass
            return await call_next(request)

    app.add_middleware(TokenRefreshMiddleware)
    app.include_router(api_router, prefix="/api")

    @app.on_event("startup")
    def _restore_tidal_session():
        """Restore Tidal OAuth session from saved token on server start."""
        try:
            from tidal_dl.config import Tidal

            tidal = Tidal()
            tidal.login_token(quiet=True)
        except Exception:
            pass

    @app.get("/", response_class=HTMLResponse)
    async def index():
        import time
        html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
        # Cache-bust static assets so browser always gets fresh JS/CSS
        v = str(int(time.time()))
        html = html.replace('/style.css', f'/style.css?v={v}')
        html = html.replace('/app.js', f'/app.js?v={v}')
        return HTMLResponse(html.replace("__CSRF_TOKEN__", csrf_token))

    app.mount("/", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    return app
