"""In-process Tidal playlist reader. Reuses the playlist API helpers."""

from __future__ import annotations

from typing import Any

from tidal_dl.gui.api.playlists import fetch_user_playlists, playlist_track_catalog
from tidal_dl.playlist_sync.models import PlaylistRef, Track, _duration


def _updated_token(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return str(value.isoformat())
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value).strip()


def _track_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


class TidalSource:
    name = "tidal"

    def __init__(self, session: Any) -> None:
        self.session = session

    def list_playlists(self) -> list[PlaylistRef]:
        refs: list[PlaylistRef] = []
        for playlist in fetch_user_playlists(self.session):
            token = _updated_token(getattr(playlist, "last_updated", None))
            refs.append(
                PlaylistRef(
                    source=self.name,
                    source_playlist_id=_track_id(getattr(playlist, "id", "")),
                    name=str(getattr(playlist, "name", "") or ""),
                    last_updated=token or None,
                    num_tracks=int(getattr(playlist, "num_tracks", 0) or 0),
                )
            )
        return refs

    def list_tracks(self, playlist: PlaylistRef) -> list[Track]:
        playlist_obj = self.session.playlist(playlist.source_playlist_id)
        tracks: list[Track] = []
        for row in playlist_track_catalog(playlist_obj):
            isrc = str(row.get("isrc") or "").strip()
            raw_id = row.get("id")
            tracks.append(
                Track(
                    source=self.name,
                    source_track_id=_track_id(raw_id),
                    title=str(row.get("name") or ""),
                    artist=str(row.get("artist") or ""),
                    album=str(row.get("album") or ""),
                    duration=_duration(row.get("duration")),
                    isrc=isrc or None,
                    available=bool(row.get("available", True)),
                    version=str(row.get("version") or ""),
                    playlist_name=playlist.name,
                    source_playlist_id=playlist.source_playlist_id,
                )
            )
        return tracks
