"""Tests for local playlist resolver — covers all R5 acceptance criteria."""

from pathlib import Path

import pytest

from tidal_dl.helper.local_playlist_resolver import (
    parse_playlist_file,
    resolve_playlist_name,
)


class TestParsePlaylistFile:
    """parse_playlist_file tests."""

    def test_m3u_returns_tracks_in_order(self, tmp_path: Path):
        """R5: .m3u file returns tracks in order."""
        playlist = tmp_path / "chill.m3u"
        playlist.write_text("/music/track1.flac\n/music/track2.flac\n/music/track3.flac\n")
        assert parse_playlist_file(playlist) == [
            "/music/track1.flac", "/music/track2.flac", "/music/track3.flac"
        ]

    def test_m3u8_returns_tracks_in_order(self, tmp_path: Path):
        """R5: .m3u8 file returns tracks in order."""
        playlist = tmp_path / "vibes.m3u8"
        playlist.write_text("/music/a.flac\n/music/b.flac\n")
        assert parse_playlist_file(playlist) == ["/music/a.flac", "/music/b.flac"]

    def test_skips_comments_and_blank_lines(self, tmp_path: Path):
        """R5: Comment lines and blank lines skipped during parsing."""
        playlist = tmp_path / "mixed.m3u"
        playlist.write_text(
            "#EXTM3U\n#EXTINF:180,Artist - Song\n/music/song.flac\n\n   \n"
            "#comment\n/music/other.flac\n"
        )
        assert parse_playlist_file(playlist) == ["/music/song.flac", "/music/other.flac"]

    def test_resolves_relative_paths_against_playlist_dir(self, tmp_path: Path):
        """F-002: Relative M3U entries resolve against the playlist's directory.

        music-dl writes relative paths in generated playlists, so parsing must
        resolve them to absolute paths using the .m3u file as the base — not
        the process cwd.
        """
        album_dir = tmp_path / "My Album"
        album_dir.mkdir()
        (album_dir / "01-track.flac").write_text("")
        (album_dir / "02-track.flac").write_text("")
        playlist = album_dir / "playlist.m3u8"
        playlist.write_text("#EXTM3U\n01-track.flac\n02-track.flac\n")

        result = parse_playlist_file(playlist)
        assert len(result) == 2
        assert result[0] == str((album_dir / "01-track.flac").resolve())
        assert result[1] == str((album_dir / "02-track.flac").resolve())

    def test_nonexistent_file_returns_empty(self, tmp_path: Path):
        assert parse_playlist_file(tmp_path / "nope.m3u") == []


class TestResolvePlaylistName:
    """resolve_playlist_name tests."""

    def test_matching_m3u(self, tmp_path: Path):
        """R5: .m3u file matched case-insensitively."""
        (tmp_path / "Chill Vibes.m3u").write_text("/music/a.flac\n")
        match = resolve_playlist_name("Chill Vibes", [tmp_path])
        assert match is not None
        assert match.name == "Chill Vibes.m3u"

    def test_matching_m3u8(self, tmp_path: Path):
        """R5: .m3u8 file matched case-insensitively."""
        (tmp_path / "Night Drive.m3u8").write_text("/music/x.flac\n")
        match = resolve_playlist_name("Night Drive", [tmp_path])
        assert match is not None
        assert match.name == "Night Drive.m3u8"

    def test_case_insensitive(self, tmp_path: Path):
        """R5: Name matching ignores case differences."""
        (tmp_path / "night drive.m3u8").write_text("/music/1.flac\n")
        match = resolve_playlist_name("Night Drive", [tmp_path])
        assert match is not None

    def test_no_match_returns_none(self, tmp_path: Path):
        """R5: No matching file returns None."""
        (tmp_path / "other.m3u").write_text("/music/z.flac\n")
        assert resolve_playlist_name("nonexistent", [tmp_path]) is None

    def test_nonexistent_directory(self, tmp_path: Path):
        """R5: Nonexistent root returns None."""
        assert resolve_playlist_name("anything", [tmp_path / "no_such_dir"]) is None

    def test_uppercase_extension_matched(self, tmp_path: Path):
        """F-009: Extensions matched case-insensitively on case-sensitive FS.

        Linux/NAS filesystems are case-sensitive — a playlist file named
        'Night Drive.M3U8' must still resolve for query 'night drive'.
        """
        (tmp_path / "Night Drive.M3U8").write_text("#EXTM3U\nx.flac\n")
        match = resolve_playlist_name("night drive", [tmp_path])
        assert match is not None
        assert match.name == "Night Drive.M3U8"

    def test_recursive_search_finds_nested_playlists(self, tmp_path: Path):
        """F-001: Playlists are often written to nested paths; search must recurse.

        music-dl writes playlists into album-named subdirectories, so a
        top-level-only search misses the common case.
        """
        nested = tmp_path / "Albums" / "My Album"
        nested.mkdir(parents=True)
        (nested / "My Album.m3u8").write_text("#EXTM3U\n01.flac\n")

        match = resolve_playlist_name("My Album", [tmp_path])
        assert match is not None
        assert match.name == "My Album.m3u8"
