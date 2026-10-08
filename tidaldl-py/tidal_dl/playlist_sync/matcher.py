"""Title, artist, and playlist normalisation for sync dedupe."""

from __future__ import annotations

import re
import unicodedata
from typing import Protocol

from tidal_dl.playlist_sync.unicode_norm import nfc

_FEAT_PAREN = re.compile(
    r"[([]\s*(?:feat(?:uring)?\.?|ft\.?|with)\s+[^)\]]*[)\]]",
    re.IGNORECASE,
)
_FEAT_TAIL = re.compile(
    r"\s+(?:feat(?:uring)?\.?|ft\.?)\s+.*$",
    re.IGNORECASE,
)
_PRIMARY_SPLIT = re.compile(r"\s+(?:with|&|x)\s+", re.IGNORECASE)
# Sources often join credited artists with commas ("Lead, Guest"). The lead
# artist is whatever comes before the first comma, "with", "&", or "x".
_LEAD_SPLIT = re.compile(r"\s*,\s*|\s+(?:with|&|x)\s+", re.IGNORECASE)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_SAFE_PHRASE = r"""
    remaster(?:ed)?(?:\s+\d{4})?
    | \d{4}\s+remaster(?:ed)?
    | album\s+version
    | (?:mono|stereo)\s+version
"""
_SAFE_SUFFIX = re.compile(
    rf"""(?:
        \s*[([]\s*(?:{_SAFE_PHRASE})\s*[])]
        |
        \s+-\s+(?:{_SAFE_PHRASE})
        |
        ^(?:{_SAFE_PHRASE})$
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


class _Named(Protocol):
    artist: str
    title: str
    duration: float | None
    isrc: str | None


def strip_accents(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in folded if not unicodedata.combining(char))


def _collapse(value: str) -> str:
    return _SPACES.sub(" ", value).strip()


def strip_safe_suffixes(value: str) -> str:
    text = value or ""
    while True:
        updated = _SAFE_SUFFIX.sub("", text).strip()
        if updated == text:
            return text
        text = updated


def normalize_artist(artist: str) -> str:
    text = strip_accents(nfc(artist)).casefold()
    text = _FEAT_PAREN.sub(" ", text)
    text = _FEAT_TAIL.sub(" ", text)
    text = _PRIMARY_SPLIT.split(text, maxsplit=1)[0]
    text = _PUNCT.sub(" ", text)
    return _collapse(text)


def lead_artist(artist: str) -> str:
    """Normalised lead artist. Like normalize_artist, but a comma also ends the lead."""
    text = strip_accents(nfc(artist)).casefold()
    text = _FEAT_PAREN.sub(" ", text)
    text = _FEAT_TAIL.sub(" ", text)
    text = _LEAD_SPLIT.split(text, maxsplit=1)[0]
    text = _PUNCT.sub(" ", text)
    return _collapse(text)


def normalize_title(title: str) -> str:
    text = strip_accents(nfc(title)).casefold()
    text = _FEAT_PAREN.sub(" ", text)
    text = _FEAT_TAIL.sub(" ", text)
    text = strip_safe_suffixes(text)
    text = _PUNCT.sub(" ", text)
    return _collapse(text)


_LOOSE_PAREN = re.compile(
    r"\s*[([][^)\]]*\b(?:live|en vivo|ao vivo|remaster(?:ed)?|feat(?:uring)?|ft|with)\b[^)\]]*[)\]]",
    re.IGNORECASE,
)
_LOOSE_DASH = re.compile(r"\s+-\s+[^-]*\b(?:live|en vivo|ao vivo|remaster(?:ed)?)\b.*$", re.IGNORECASE)
_UNKNOWN_ARTISTS = frozenset({"", "various artists", "various", "varios artistas", "va"})


def loose_title(title: str) -> str:
    """Title for the "already on the playlist" check only.

    Also drops "(Live)", "(En Vivo)", "(feat. ...)" and remaster tags, so a row
    tagged without them still counts as the same song. Never used to confirm a
    download or an append.
    """
    text = strip_accents(nfc(title)).casefold()
    text = _LOOSE_PAREN.sub(" ", text)
    text = _LOOSE_DASH.sub(" ", text)
    return normalize_title(text)


def artist_unknown(artist: str) -> bool:
    """True for an empty or compilation artist such as "Various Artists"."""
    return normalize_artist(artist) in _UNKNOWN_ARTISTS


def normalize_playlist_name(name: str) -> str:
    return _collapse(strip_accents(nfc(name)).casefold())


def isrc_key(isrc: str | None) -> str:
    return (isrc or "").strip().upper()


def same_recording(left: _Named, right: _Named) -> bool:
    """True when two rows are the same recording for union dedupe.

    Both ISRCs present: equal codes only. A missing ISRC falls back to
    normalised primary artist + title and duration within 3 seconds.
    """
    left_isrc = isrc_key(left.isrc)
    right_isrc = isrc_key(right.isrc)
    if left_isrc and right_isrc:
        return left_isrc == right_isrc
    if normalize_artist(left.artist) != normalize_artist(right.artist):
        return False
    if normalize_title(left.title) != normalize_title(right.title):
        return False
    if left.duration is None or right.duration is None:
        return False
    return abs(float(left.duration) - float(right.duration)) <= 3
