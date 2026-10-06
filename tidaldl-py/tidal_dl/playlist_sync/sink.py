"""Plex sink protocol. This PR ships a no-op sink; the writer comes later."""

from __future__ import annotations

from typing import Protocol

from tidal_dl.playlist_sync.models import Track


class PlexSink(Protocol):
    def list_tracks(self, name: str) -> list[Track]:
        """Tracks already on the named playlist, in current order."""

    def append(self, name: str, tracks: list[Track]) -> None:
        """Append tracks. Never remove or reorder existing rows."""

    def find(self, track: Track) -> list[Track]:
        """Candidate tracks already in the Plex library, not only this playlist."""


class NullPlexSink:
    def list_tracks(self, name: str) -> list[Track]:
        return []

    def append(self, name: str, tracks: list[Track]) -> None:
        return None

    def find(self, track: Track) -> list[Track]:
        return []
