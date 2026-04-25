"""Bot-facing API — resolve, playable source, download trigger/status.

These endpoints are consumed by the Discord bot process, not the GUI.
Auth uses a dedicated bearer token (MUSIC_DL_BOT_TOKEN env var), not CSRF.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from tidal_dl.gui.security import validate_bot_bearer

router = APIRouter(prefix="/bot")


def require_bot_auth(authorization: str | None = Header(default=None)) -> None:
    """Dependency that rejects requests without a valid bot bearer token."""
    if not validate_bot_bearer(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized bot client")


class ResolveRequest(BaseModel):
    query: str


@router.post("/play/resolve")
def resolve_play_request(
    payload: ResolveRequest,
    _: None = Depends(require_bot_auth),
) -> dict:
    """Resolve a /play input into choices or queueable items.

    Accepts free text, Tidal track/playlist URLs, or local playlist names.
    """
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    # Placeholder — Task 3 implements actual resolution
    return {"kind": "choices", "choices": []}
