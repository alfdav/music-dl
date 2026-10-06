"""Playlist source protocol. Tidal is wired here; other readers can follow."""

from __future__ import annotations

from typing import Protocol

from tidal_dl.playlist_sync.models import PlaylistRef, Track


class Source(Protocol):
    name: str

    def list_playlists(self) -> list[PlaylistRef]:
        """Playlists the user created on this source."""

    def list_tracks(self, playlist: PlaylistRef) -> list[Track]:
        """Tracks on one playlist. Callers skip this when the ledger is current."""
