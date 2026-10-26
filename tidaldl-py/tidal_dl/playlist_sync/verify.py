"""Strict source-to-candidate checks. Review is never treated as present."""

from __future__ import annotations

import re
from typing import Protocol

from tidal_dl.playlist_sync.matcher import (
    isrc_key,
    lead_artist,
    normalize_artist,
    normalize_title,
    strip_accents,
    strip_safe_suffixes,
)
from tidal_dl.playlist_sync.models import VerifyResult

# Markers that make a candidate a different recording unless the source has them too.
VERSION_MARKERS: tuple[str, ...] = (
    "cover",
    "karaoke",
    "tribute",
    "in the style of",
    "originally performed by",
    "instrumental",
    "live",
    "remix",
    "remixed",
    "sped up",
    "slowed",
    "8-bit",
    "8 bit",
    "en vivo",
    "en directo",
    "version",
    "tributo",
    "homenaje",
    "remezcla",
    "remezclado",
    "acelerada",
    "acelerado",
    "estilo de",
    "originalmente interpretada por",
)


def _marker_pattern(marker: str) -> re.Pattern[str]:
    parts = marker.split()
    body = r"[\s-]+".join(re.escape(part) for part in parts)
    return re.compile(rf"(?<!\w){body}(?!\w)")


_MARKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (strip_accents(marker).casefold(), _marker_pattern(strip_accents(marker).casefold()))
    for marker in dict.fromkeys(VERSION_MARKERS)
)


class _Side(Protocol):
    title: str
    artist: str
    album: str
    duration: float | None
    isrc: str | None
    version: str


def _marker_text(title: str, version: str, album: str) -> str:
    parts = []
    for part in (title, version, album):
        if not part:
            continue
        cleaned = strip_safe_suffixes(strip_accents(part).casefold())
        if cleaned:
            parts.append(cleaned)
    return " ".join(parts)


def markers_in(title: str, version: str = "", album: str = "") -> set[str]:
    text = _marker_text(title, version, album)
    return {name for name, pattern in _MARKER_PATTERNS if pattern.search(text)}


def _duration_state(source: _Side, candidate: _Side) -> str:
    if source.duration is None or candidate.duration is None:
        return "missing"
    delta = abs(float(source.duration) - float(candidate.duration))
    if delta <= 3:
        return "ok"
    if delta <= 5:
        return "borderline"
    return "reject"


def verify(source_track: _Side, candidate: _Side) -> VerifyResult:
    """Compare one source row to one candidate. confirmed is the only pass.

    With equal ISRCs, the lead artist is enough ("Lead, Guest" matches
    "Lead"). Without an ISRC match the full artist rule applies. Equal ISRCs
    with a different lead artist or a different title go to review.
    """
    full_artist_ok = bool(normalize_artist(source_track.artist)) and (
        normalize_artist(source_track.artist) == normalize_artist(candidate.artist)
    )
    lead_ok = bool(lead_artist(source_track.artist)) and (
        lead_artist(source_track.artist) == lead_artist(candidate.artist)
    )
    title_ok = bool(normalize_title(source_track.title)) and (
        normalize_title(source_track.title) == normalize_title(candidate.title)
    )
    source_isrc = isrc_key(source_track.isrc)
    candidate_isrc = isrc_key(candidate.isrc)
    isrc_equal = bool(source_isrc) and source_isrc == candidate_isrc
    isrc_conflict = bool(source_isrc) and bool(candidate_isrc) and source_isrc != candidate_isrc
    isrc_ok = isrc_equal
    artist_ok = full_artist_ok or (isrc_equal and lead_ok)
    duration_state = _duration_state(source_track, candidate)
    duration_ok = duration_state == "ok"
    source_markers = markers_in(source_track.title, source_track.version, source_track.album)
    candidate_markers = markers_in(candidate.title, candidate.version, candidate.album)
    version_ok = candidate_markers <= source_markers

    reasons: list[str] = []
    if not version_ok:
        confidence = "reject"
        reasons.append("version_marker")
    elif isrc_conflict:
        confidence = "reject"
        reasons.append("isrc_mismatch")
    elif isrc_equal and not artist_ok:
        confidence = "review"
        reasons.append("isrc_artist_mismatch")
    elif not artist_ok:
        confidence = "reject"
        reasons.append("artist_mismatch")
    elif isrc_equal and not title_ok:
        # Same recording code, different title, e.g. "(Live)" on one side only.
        confidence = "review"
        reasons.append("isrc_title_mismatch")
    elif not title_ok:
        confidence = "reject"
        reasons.append("title_mismatch")
    elif duration_state == "borderline":
        confidence = "review"
        reasons.append("duration_borderline")
    elif duration_state == "missing":
        confidence = "review"
        reasons.append("duration_missing")
    elif duration_state == "reject":
        confidence = "reject"
        reasons.append("duration_mismatch")
    else:
        confidence = "confirmed"

    return VerifyResult(
        artist_ok=artist_ok,
        title_ok=title_ok,
        duration_ok=duration_ok,
        isrc_ok=isrc_ok,
        version_ok=version_ok,
        confidence=confidence,
        reasons=tuple(reasons),
    )
