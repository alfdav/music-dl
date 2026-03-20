"""Tests for the sync command's playlist diff logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from tidal_dl.cli import _sync_diff_playlists


@dataclass
class FakeTrack:
    isrc: str | None = None
    name: str = "Track"


@dataclass
class FakePlaylist:
    name: str = "My Playlist"
    id: str = "123"
    share_url: str = "https://tidal.com/playlist/123"
    _tracks: list[FakeTrack] = field(default_factory=list)

    def tracks(self, limit: int = 100, offset: int = 0) -> list[FakeTrack]:
        return self._tracks[offset : offset + limit]


def _make_isrc_index(known_isrcs: set[str]) -> MagicMock:
    idx = MagicMock()
    idx.contains.side_effect = lambda isrc: isrc in known_isrcs
    idx.load.return_value = None
    return idx


def test_diff_finds_missing_tracks():
    playlist = FakePlaylist(
        name="Chill",
        _tracks=[FakeTrack(isrc="US1234"), FakeTrack(isrc="US5678"), FakeTrack(isrc="US9999")],
    )
    idx = _make_isrc_index({"US1234"})

    result = _sync_diff_playlists([playlist], idx)

    assert len(result) == 1
    assert result[0]["name"] == "Chill"
    assert result[0]["total"] == 3
    assert result[0]["local"] == 1
    assert result[0]["missing"] == 2
    assert result[0]["share_url"] == "https://tidal.com/playlist/123"


def test_diff_all_local():
    playlist = FakePlaylist(
        name="Done",
        _tracks=[FakeTrack(isrc="US1111"), FakeTrack(isrc="US2222")],
    )
    idx = _make_isrc_index({"US1111", "US2222"})

    result = _sync_diff_playlists([playlist], idx)

    assert result[0]["missing"] == 0


def test_diff_tracks_without_isrc_count_as_missing():
    playlist = FakePlaylist(
        name="Odd",
        _tracks=[FakeTrack(isrc=None), FakeTrack(isrc="US1111")],
    )
    idx = _make_isrc_index({"US1111"})

    result = _sync_diff_playlists([playlist], idx)

    assert result[0]["missing"] == 1
    assert result[0]["total"] == 2


def test_diff_empty_playlist():
    playlist = FakePlaylist(name="Empty", _tracks=[])
    idx = _make_isrc_index(set())

    result = _sync_diff_playlists([playlist], idx)

    assert result[0]["total"] == 0
    assert result[0]["missing"] == 0


def test_diff_paginates_large_playlist():
    """Verify the pagination loop fetches tracks beyond the first page."""
    tracks = [FakeTrack(isrc=f"US{i:04d}") for i in range(150)]
    playlist = FakePlaylist(name="Big", _tracks=tracks)
    idx = _make_isrc_index(set())

    result = _sync_diff_playlists([playlist], idx)

    assert result[0]["total"] == 150
    assert result[0]["missing"] == 150
