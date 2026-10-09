"""Plex sink protocol. A missing return is success so older fakes keep working."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from tidal_dl.playlist_sync.models import AppendResult, Track


class PlexSink(Protocol):
    def list_tracks(self, name: str) -> list[Track]:
        """Tracks already on the named playlist, in current order."""

    def append(
        self,
        name: str,
        tracks: list[Track],
        paths: Sequence[str | None] | None = None,
    ) -> AppendResult | None:
        """Append tracks. Never remove or reorder existing rows.

        ``paths`` is the local file for each track, in the same order. A None
        return means the append succeeded.
        """

    def find(self, track: Track) -> list[Track]:
        """Candidate tracks already in the Plex library, not only this playlist."""


class NullPlexSink:
    def list_tracks(self, name: str) -> list[Track]:
        return []

    def append(
        self,
        name: str,
        tracks: list[Track],
        paths: Sequence[str | None] | None = None,
    ) -> None:
        return None

    def find(self, track: Track) -> list[Track]:
        return []
