"""Bot-facing API endpoints.

All routes live under /bot and are gated by bearer-token
authentication via the require_bot_auth dependency.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from tidal_dl.gui.security import validate_bot_bearer

router = APIRouter(prefix="/bot")


def require_bot_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency that enforces bot bearer-token auth."""
    if not validate_bot_bearer(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized bot client")


@router.post("/play/resolve")
def resolve_placeholder(_: None = Depends(require_bot_auth)) -> dict:
    """Placeholder resolve endpoint — will be implemented in T-009."""
    return {"items": []}
