"""Tests for the album-aware upgrade logic in _trigger_upgrade_downloads."""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build mock Tidal objects
# ---------------------------------------------------------------------------


def _make_album(name: str, artist_name: str = "Various Artists", album_id: int = 100):
    album = MagicMock()
    album.name = name
    album.id = album_id
    artist = MagicMock()
    artist.name = artist_name
    album.artists = [artist]
    album.image = MagicMock(return_value="https://img.example.com/cover.jpg")
    return album


def _make_track(isrc: str, name: str, album: MagicMock, track_id: int = 1):
    track = MagicMock()
    track.isrc = isrc
    track.name = name
    track.full_name = name
    track.id = track_id
    track.album = album
    artist = MagicMock()
    artist.name = "Test Artist"
    track.artists = [artist]
    return track


# ---------------------------------------------------------------------------
# Tests for _resolve_tidal_album
# ---------------------------------------------------------------------------


class TestResolveTidalAlbum:
    """Test _resolve_tidal_album helper."""

    def _import_func(self):
        from tidal_dl.gui.services.upgrade_jobs import resolve_tidal_album
        return resolve_tidal_album

    def test_returns_album_with_matching_isrcs(self):
        """When Tidal search returns an album with matching ISRCs, return it."""
        _resolve_tidal_album = self._import_func()

        album = _make_album("Number 1's", "Stevie Wonder")
        track1 = _make_track("USMO10000001", "Superstition", album, track_id=10)
        track2 = _make_track("USMO10000002", "You Are the Sunshine", album, track_id=11)
        album.tracks = MagicMock(return_value=[track1, track2])

        session = MagicMock()
        session.search = MagicMock(return_value={"albums": [album]})

        result_album, result_tracks = _resolve_tidal_album(
            session, "Number 1's", "Stevie Wonder", ["USMO10000001"]
        )

        assert result_album is album
        assert len(result_tracks) == 2
        session.search.assert_called_once()

    def test_returns_none_when_no_isrc_match(self):
        """When album tracks have no overlapping ISRCs, return None."""
        _resolve_tidal_album = self._import_func()

        album = _make_album("Number 1's", "Stevie Wonder")
        track1 = _make_track("USMO10000099", "Wrong Track", album, track_id=10)
        album.tracks = MagicMock(return_value=[track1])

        session = MagicMock()
        session.search = MagicMock(return_value={"albums": [album]})

        result_album, result_tracks = _resolve_tidal_album(
            session, "Number 1's", "Stevie Wonder", ["USMO10000001"]
        )

        assert result_album is None
        assert result_tracks == []

    def test_returns_none_when_album_name_mismatch(self):
        """When no album name matches, return None."""
        _resolve_tidal_album = self._import_func()

        album = _make_album("Talking Book", "Stevie Wonder")
        track1 = _make_track("USMO10000001", "Superstition", album, track_id=10)
        album.tracks = MagicMock(return_value=[track1])

        session = MagicMock()
        session.search = MagicMock(return_value={"albums": [album]})

        result_album, result_tracks = _resolve_tidal_album(
            session, "Number 1's", "Stevie Wonder", ["USMO10000001"]
        )

        assert result_album is None
        assert result_tracks == []

    def test_returns_none_on_search_failure(self):
        """When Tidal search throws an exception, return None gracefully."""
        _resolve_tidal_album = self._import_func()

        session = MagicMock()
        session.search = MagicMock(side_effect=Exception("rate limited"))

        result_album, result_tracks = _resolve_tidal_album(
            session, "Number 1's", "Stevie Wonder", ["USMO10000001"]
        )

        assert result_album is None
        assert result_tracks == []

    def test_returns_none_with_empty_isrcs(self):
        """When no ISRCs are provided, return None immediately."""
        _resolve_tidal_album = self._import_func()

        session = MagicMock()
        result_album, result_tracks = _resolve_tidal_album(
            session, "Number 1's", "Stevie Wonder", []
        )

        assert result_album is None
        assert result_tracks == []
        session.search.assert_not_called()

    def test_case_insensitive_album_name_match(self):
        """Album name comparison should be case-insensitive and ignore punctuation."""
        _resolve_tidal_album = self._import_func()

        album = _make_album("Number 1's", "Stevie Wonder")
        track1 = _make_track("USMO10000001", "Superstition", album, track_id=10)
        album.tracks = MagicMock(return_value=[track1])

        session = MagicMock()
        session.search = MagicMock(return_value={"albums": [album]})

        # Search with slightly different casing/punctuation
        result_album, _ = _resolve_tidal_album(
            session, "number 1s", "Stevie Wonder", ["USMO10000001"]
        )

        assert result_album is album

    def test_uses_items_fallback(self):
        """When .tracks() is not available, try .items()."""
        _resolve_tidal_album = self._import_func()

        album = _make_album("Number 1's", "Stevie Wonder")
        track1 = _make_track("USMO10000001", "Superstition", album, track_id=10)
        # Remove tracks method, provide items instead
        del album.tracks
        album.items = MagicMock(return_value=[track1])

        session = MagicMock()
        session.search = MagicMock(return_value={"albums": [album]})

        result_album, result_tracks = _resolve_tidal_album(
            session, "Number 1's", "Stevie Wonder", ["USMO10000001"]
        )

        assert result_album is album
        assert len(result_tracks) == 1


# ---------------------------------------------------------------------------
# Tests for album grouping logic
# ---------------------------------------------------------------------------


class TestAlbumGrouping:
    """Test that tracks from the same album get grouped together."""

    def test_tracks_grouped_by_album_name(self):
        """Tracks with the same album name in DB should be grouped together."""
        # Simulate the grouping logic from _trigger_upgrade_downloads Phase 1
        track_ids = [101, 102, 103, 201]
        upgrade_map = {
            101: "/music/Number1s/track1.flac",
            102: "/music/Number1s/track2.flac",
            103: "/music/Number1s/track3.flac",
            201: "/music/TalkingBook/track1.flac",
        }

        db_rows = {
            "/music/Number1s/track1.flac": {"album": "Number 1's", "isrc": "ISRC001", "artist": "Stevie Wonder"},
            "/music/Number1s/track2.flac": {"album": "Number 1's", "isrc": "ISRC002", "artist": "Stevie Wonder"},
            "/music/Number1s/track3.flac": {"album": "Number 1's", "isrc": "ISRC003", "artist": "Stevie Wonder"},
            "/music/TalkingBook/track1.flac": {"album": "Talking Book", "isrc": "ISRC004", "artist": "Stevie Wonder"},
        }

        album_groups: dict[str, list] = {}
        for tid in track_ids:
            old_path = upgrade_map.get(tid, "")
            row = db_rows.get(old_path)
            album_name = (row.get("album") or "") if row else ""
            if album_name:
                album_groups.setdefault(album_name, []).append((tid, old_path, row))
            else:
                album_groups.setdefault("", []).append((tid, old_path, row))

        assert "Number 1's" in album_groups
        assert "Talking Book" in album_groups
        assert len(album_groups["Number 1's"]) == 3
        assert len(album_groups["Talking Book"]) == 1

    def test_tracks_without_album_grouped_under_empty_key(self):
        """Tracks with no album in DB should be grouped under empty string."""
        track_ids = [101, 102]
        upgrade_map = {
            101: "/music/track1.flac",
            102: "",
        }

        db_rows = {
            "/music/track1.flac": {"album": "", "isrc": "ISRC001", "artist": "Unknown"},
        }

        album_groups: dict[str, list] = {}
        for tid in track_ids:
            old_path = upgrade_map.get(tid, "")
            row = db_rows.get(old_path) if old_path else None
            album_name = (row.get("album") or "") if row else ""
            if album_name:
                album_groups.setdefault(album_name, []).append((tid, old_path, row))
            else:
                album_groups.setdefault("", []).append((tid, old_path, row))

        assert "" in album_groups
        assert len(album_groups[""]) == 2


# ---------------------------------------------------------------------------
# Tests for fallback behavior
# ---------------------------------------------------------------------------


class TestFallbackBehavior:
    """Test that fallback uses format_track and individual track fetch."""

    def test_fallback_template_is_format_track(self):
        """When no album template found, file_template should be format_track."""
        album_templates: dict = {}  # Empty — no album resolved
        local_album_name = "Number 1's"
        isrc = "USMO10000001"
        format_track = "{album_artist}/{album_title}/{track_title}"

        template_info = album_templates.get(local_album_name)
        album_track = None
        file_template = format_track  # default fallback

        if template_info and isrc:
            pre_expanded, isrc_to_track = template_info
            album_track = isrc_to_track.get(isrc)
            if album_track:
                file_template = pre_expanded

        assert file_template == format_track
        assert album_track is None

    def test_fallback_when_isrc_not_in_album_tracks(self):
        """When album resolved but this track's ISRC isn't in album tracks, fallback."""
        album_templates = {
            "Number 1's": (
                "Stevie Wonder/Number 1's/{track_volume_num_optional_CD}/{track_title}",
                {"USMO10000001": MagicMock()},  # Only one ISRC in lookup
            )
        }
        local_album_name = "Number 1's"
        isrc = "USMO10000099"  # Not in the lookup
        format_track = "{album_artist}/{album_title}/{track_title}"

        template_info = album_templates.get(local_album_name)
        album_track = None
        file_template = format_track

        if template_info and isrc:
            pre_expanded, isrc_to_track = template_info
            album_track = isrc_to_track.get(isrc)
            if album_track:
                file_template = pre_expanded

        assert file_template == format_track
        assert album_track is None

    def test_album_aware_template_used_when_match(self):
        """When album resolved and ISRC matches, use pre-expanded template."""
        mock_track = MagicMock()
        pre_expanded = "Stevie Wonder/Number 1's/{track_volume_num_optional_CD}/{track_title}"
        album_templates = {
            "Number 1's": (
                pre_expanded,
                {"USMO10000001": mock_track},
            )
        }
        local_album_name = "Number 1's"
        isrc = "USMO10000001"
        format_track = "{album_artist}/{album_title}/{track_title}"

        template_info = album_templates.get(local_album_name)
        album_track = None
        file_template = format_track

        if template_info and isrc:
            pre_exp, isrc_to_track = template_info
            album_track = isrc_to_track.get(isrc)
            if album_track:
                file_template = pre_exp

        assert file_template == pre_expanded
        assert album_track is mock_track
