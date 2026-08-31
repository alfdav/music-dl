"""Parse Tidal catalog URLs and bare numeric ids for GUI search intake."""

from __future__ import annotations

import re
from typing import NamedTuple

_TIDAL_REF_RE = re.compile(
    r"""
    ^\s*
    (?:https?://)?
    (?:(?:www|listen|desktop)\.)?
    tidal\.com
    /(?:browse/)?
    (?P<kind>track|album|artist|playlist)
    /(?P<id>[A-Za-z0-9-]+)
    (?:/u)?
    /?
    (?:[?#].*)?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_BARE_ID_RE = re.compile(r"^\s*(\d+)\s*$")

_TYPE_HINT = {
    "tracks": "track",
    "albums": "album",
    "artists": "artist",
    "playlists": "playlist",
}


class TidalRef(NamedTuple):
    kind: str
    id: str


def parse_tidal_ref(query: str, type_hint: str | None = None) -> TidalRef | None:
    """Return a Tidal catalog ref from a URL or a bare numeric id."""
    raw = (query or "").strip()
    if not raw:
        return None
    match = _TIDAL_REF_RE.match(raw)
    if match:
        return TidalRef(kind=match.group("kind").lower(), id=match.group("id"))
    bare = _BARE_ID_RE.match(raw)
    if bare and type_hint in _TYPE_HINT:
        return TidalRef(kind=_TYPE_HINT[type_hint], id=bare.group(1))
    return None


def looks_like_web_url(query: str) -> bool:
    """True when the query looks like a URL and must not be sent to Tidal search."""
    raw = (query or "").strip().lower()
    if raw.startswith(("http://", "https://")):
        return True
    return "tidal.com/" in raw
