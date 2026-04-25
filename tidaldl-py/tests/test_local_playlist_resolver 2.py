"""Local playlist resolver tests — name lookup and M3U parsing."""

from pathlib import Path

from tidal_dl.helper.local_playlist_resolver import parse_playlist_file, resolve_playlist_name


def test_resolve_playlist_name_prefers_casefolded_exact_match(tmp_path: Path):
    playlist_dir = tmp_path / "Playlists"
    playlist_dir.mkdir()
    (playlist_dir / "Night Drive.m3u8").write_text("#EXTM3U\nsong.flac\n", encoding="utf-8")

    match = resolve_playlist_name("night drive", [playlist_dir])

    assert match is not None
    assert match.name == "Night Drive.m3u8"


def test_resolve_playlist_name_returns_none_for_no_match(tmp_path: Path):
    playlist_dir = tmp_path / "Playlists"
    playlist_dir.mkdir()
    (playlist_dir / "Chill.m3u").write_text("track.flac\n", encoding="utf-8")

    assert resolve_playlist_name("nonexistent", [playlist_dir]) is None


def test_resolve_playlist_name_returns_none_for_empty_name(tmp_path: Path):
    assert resolve_playlist_name("", [tmp_path]) is None
    assert resolve_playlist_name("   ", [tmp_path]) is None


def test_resolve_playlist_name_ignores_non_playlist_files(tmp_path: Path):
    (tmp_path / "Night Drive.txt").write_text("not a playlist", encoding="utf-8")
    assert resolve_playlist_name("night drive", [tmp_path]) is None


def test_resolve_playlist_name_searches_multiple_roots(tmp_path: Path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_b / "Workout.m3u").write_text("track.flac\n", encoding="utf-8")

    match = resolve_playlist_name("workout", [dir_a, dir_b])
    assert match is not None
    assert match.name == "Workout.m3u"


def test_parse_playlist_file_skips_comments_and_blank_lines(tmp_path: Path):
    playlist = tmp_path / "set.m3u8"
    playlist.write_text("#EXTM3U\n\ntrack-a.flac\n# comment\ntrack-b.flac\n", encoding="utf-8")

    paths = parse_playlist_file(playlist)

    assert paths == ["track-a.flac", "track-b.flac"]


def test_parse_playlist_file_strips_whitespace(tmp_path: Path):
    playlist = tmp_path / "set.m3u"
    playlist.write_text("  track-a.flac  \ntrack-b.flac\n", encoding="utf-8")

    paths = parse_playlist_file(playlist)

    assert paths == ["track-a.flac", "track-b.flac"]
