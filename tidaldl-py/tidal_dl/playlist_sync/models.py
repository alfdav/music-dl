"""Shared playlist-sync records. Reports are JSON-serialisable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tidal_dl.playlist_sync.unicode_norm import nfc


def _duration(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PlaylistRef:
    source: str
    source_playlist_id: str
    name: str
    last_updated: str | None = None
    num_tracks: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", nfc(self.name))


@dataclass(frozen=True)
class Track:
    source: str
    source_track_id: str
    title: str
    artist: str
    album: str = ""
    duration: float | None = None
    isrc: str | None = None
    available: bool = True
    version: str = ""
    playlist_name: str = ""
    source_playlist_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", nfc(self.title))
        object.__setattr__(self, "artist", nfc(self.artist))
        object.__setattr__(self, "album", nfc(self.album))
        object.__setattr__(self, "version", nfc(self.version))
        object.__setattr__(self, "playlist_name", nfc(self.playlist_name))

    def source_view(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "isrc": self.isrc,
        }


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    artist: str
    duration: float | None = None
    isrc: str | None = None
    album: str = ""
    version: str = ""
    path: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", nfc(self.id))
        object.__setattr__(self, "title", nfc(self.title))
        object.__setattr__(self, "artist", nfc(self.artist))
        object.__setattr__(self, "album", nfc(self.album))
        object.__setattr__(self, "version", nfc(self.version))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "isrc": self.isrc,
        }


def candidate_from_track(track: Track) -> Candidate:
    return Candidate(
        id=track.source_track_id,
        title=track.title,
        artist=track.artist,
        duration=track.duration,
        isrc=track.isrc,
        album=track.album,
        version=track.version,
    )


def candidate_from_mapping(row: dict[str, Any]) -> Candidate:
    raw_id = row.get("id", row.get("tidal_id"))
    if raw_id is None:
        raw_id = row.get("path", "")
    return Candidate(
        id="" if raw_id is None else str(raw_id),
        title=str(row.get("title") or row.get("name") or ""),
        artist=str(row.get("artist") or ""),
        album=str(row.get("album") or ""),
        duration=_duration(row.get("duration")),
        isrc=(str(row.get("isrc")).strip() or None) if row.get("isrc") else None,
        version=str(row.get("version") or ""),
        path=str(row.get("path") or ""),
    )


def coerce_track(item: Track | dict[str, Any], *, source: str, playlist_name: str = "") -> Track:
    if isinstance(item, Track):
        if item.playlist_name or not playlist_name:
            return item
        return Track(
            source=item.source,
            source_track_id=item.source_track_id,
            title=item.title,
            artist=item.artist,
            album=item.album,
            duration=item.duration,
            isrc=item.isrc,
            available=item.available,
            version=item.version,
            playlist_name=playlist_name,
            source_playlist_id=item.source_playlist_id,
        )
    raw_id = item.get("source_track_id", item.get("id", ""))
    isrc = item.get("isrc")
    return Track(
        source=str(item.get("source") or source),
        source_track_id="" if raw_id is None else str(raw_id),
        title=str(item.get("title") or item.get("name") or ""),
        artist=str(item.get("artist") or ""),
        album=str(item.get("album") or ""),
        duration=_duration(item.get("duration")),
        isrc=(str(isrc).strip() or None) if isrc else None,
        available=bool(item.get("available", True)),
        version=str(item.get("version") or ""),
        playlist_name=str(item.get("playlist_name") or playlist_name),
        source_playlist_id=str(item.get("source_playlist_id") or ""),
    )


@dataclass(frozen=True)
class VerifyResult:
    artist_ok: bool
    title_ok: bool
    duration_ok: bool
    isrc_ok: bool
    version_ok: bool
    confidence: str
    reasons: tuple[str, ...]

    def fields_matched(self) -> list[str]:
        names: list[str] = []
        if self.artist_ok:
            names.append("artist")
        if self.title_ok:
            names.append("title")
        if self.duration_ok:
            names.append("duration")
        if self.isrc_ok:
            names.append("isrc")
        if self.version_ok:
            names.append("version")
        return names

    def to_dict(self) -> dict[str, Any]:
        return {
            "artist_ok": self.artist_ok,
            "title_ok": self.title_ok,
            "duration_ok": self.duration_ok,
            "isrc_ok": self.isrc_ok,
            "version_ok": self.version_ok,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }


@dataclass
class PlaylistReport:
    name: str
    tidal_count: int = 0
    apple_count: int = 0
    plex_count: int = 0
    union_count: int = 0
    to_download: int = 0
    unmatched: int = 0
    unobtainable: int = 0
    already_local: int = 0
    needs_review: list[dict[str, Any]] = field(default_factory=list)
    tracks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tidal_count": self.tidal_count,
            "apple_count": self.apple_count,
            "plex_count": self.plex_count,
            "union_count": self.union_count,
            "to_download": self.to_download,
            "unmatched": self.unmatched,
            "unobtainable": self.unobtainable,
            "already_local": self.already_local,
            "needs_review": self.needs_review,
            "tracks": self.tracks,
        }


@dataclass
class CycleReport:
    added: list[dict[str, Any]] = field(default_factory=list)
    downloaded: list[dict[str, Any]] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    unobtainable: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    needs_review: list[dict[str, Any]] = field(default_factory=list)
    download_mismatch: list[dict[str, Any]] = field(default_factory=list)
    halted_reason: str | None = None
    playlists: list[PlaylistReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "downloaded": self.downloaded,
            "unmatched": self.unmatched,
            "unobtainable": self.unobtainable,
            "skipped": self.skipped,
            "needs_review": self.needs_review,
            "download_mismatch": self.download_mismatch,
            "halted_reason": self.halted_reason,
            "playlists": [playlist.to_dict() for playlist in self.playlists],
        }


@dataclass(frozen=True)
class DownloadResult:
    status: str
    path: str | None = None
    http_status: int | None = None
    error: str | None = None
