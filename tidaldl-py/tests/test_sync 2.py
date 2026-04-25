"""Tests for the sync command's playlist diff logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from unittest.mock import MagicMock, patch

from rich.console import Console

from tidal_dl.cli import _sync_diff_playlists, _sync_print_summary, _sync_prompt_playlists


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


# --- _sync_diff_playlists tests ---


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


# --- _sync_print_summary tests ---


def test_summary_table_renders():
    diff = [
        {"name": "Chill", "total": 42, "local": 38, "missing": 4, "share_url": ""},
        {"name": "Done", "total": 10, "local": 10, "missing": 0, "share_url": ""},
    ]
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=80)

    _sync_print_summary(diff, console)

    output = buf.getvalue()
    assert "Chill" in output
    assert "42" in output
    assert "4" in output
    assert "Done" in output


# --- _sync_prompt_playlists tests ---


def test_prompt_yes_selects_playlist():
    diff = [{"name": "Chill", "total": 10, "local": 6, "missing": 4, "share_url": "https://tidal.com/playlist/123"}]
    with patch("builtins.input", return_value="y"):
        urls = _sync_prompt_playlists(diff)
    assert urls == ["https://tidal.com/playlist/123"]


def test_prompt_no_skips_playlist():
    diff = [{"name": "Chill", "total": 10, "local": 6, "missing": 4, "share_url": "https://tidal.com/playlist/123"}]
    with patch("builtins.input", return_value="n"):
        urls = _sync_prompt_playlists(diff)
    assert urls == []


def test_prompt_all_selects_remaining():
    diff = [
        {"name": "A", "total": 5, "local": 0, "missing": 5, "share_url": "https://tidal.com/playlist/1"},
        {"name": "B", "total": 3, "local": 0, "missing": 3, "share_url": "https://tidal.com/playlist/2"},
    ]
    with patch("builtins.input", return_value="a"):
        urls = _sync_prompt_playlists(diff)
    assert urls == ["https://tidal.com/playlist/1", "https://tidal.com/playlist/2"]


def test_prompt_quit_stops_early():
    diff = [
        {"name": "A", "total": 5, "local": 0, "missing": 5, "share_url": "https://tidal.com/playlist/1"},
        {"name": "B", "total": 3, "local": 0, "missing": 3, "share_url": "https://tidal.com/playlist/2"},
    ]
    with patch("builtins.input", return_value="q"):
        urls = _sync_prompt_playlists(diff)
    assert urls == []


def test_prompt_skips_zero_missing():
    diff = [
        {"name": "Done", "total": 10, "local": 10, "missing": 0, "share_url": "https://tidal.com/playlist/1"},
        {"name": "Has Missing", "total": 5, "local": 2, "missing": 3, "share_url": "https://tidal.com/playlist/2"},
    ]
    with patch("builtins.input", return_value="y"):
        urls = _sync_prompt_playlists(diff)
    assert urls == ["https://tidal.com/playlist/2"]


def test_prompt_empty_input_defaults_to_yes():
    diff = [{"name": "Chill", "total": 10, "local": 6, "missing": 4, "share_url": "https://tidal.com/playlist/123"}]
    with patch("builtins.input", return_value=""):
        urls = _sync_prompt_playlists(diff)
    assert urls == ["https://tidal.com/playlist/123"]


def test_prompt_all_on_second_playlist():
    diff = [
        {"name": "A", "total": 5, "local": 0, "missing": 5, "share_url": "https://tidal.com/playlist/1"},
        {"name": "B", "total": 3, "local": 0, "missing": 3, "share_url": "https://tidal.com/playlist/2"},
        {"name": "C", "total": 4, "local": 1, "missing": 3, "share_url": "https://tidal.com/playlist/3"},
    ]
    with patch("builtins.input", side_effect=["n", "a"]):
        urls = _sync_prompt_playlists(diff)
    assert urls == ["https://tidal.com/playlist/2", "https://tidal.com/playlist/3"]


def test_prompt_yes_flag_selects_all():
    diff = [
        {"name": "A", "total": 5, "local": 0, "missing": 5, "share_url": "https://tidal.com/playlist/1"},
        {"name": "B", "total": 3, "local": 1, "missing": 2, "share_url": "https://tidal.com/playlist/2"},
        {"name": "Done", "total": 10, "local": 10, "missing": 0, "share_url": "https://tidal.com/playlist/3"},
    ]
    urls = _sync_prompt_playlists(diff, auto_yes=True)
    assert urls == ["https://tidal.com/playlist/1", "https://tidal.com/playlist/2"]
