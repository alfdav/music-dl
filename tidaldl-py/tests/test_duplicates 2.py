"""Tests for duplicate detection logic and cleanup/undo cycle."""
import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.gui.api.duplicates import (
    _normalize, _path_score, _find_duplicate_groups, _get_db,
    _staging_base, _write_manifest, _read_manifest, _find_active_manifest,
    _is_cleanup_running, _acquire_lock, _release_lock, _lock_path,
)


@pytest.fixture
def db(tmp_path):
    d = LibraryDB(tmp_path / "test.db")
    d.open()
    yield d
    d.close()


class TestNormalize:
    def test_lowercases(self):
        assert _normalize("Hello World") == "hello world"

    def test_collapses_whitespace(self):
        assert _normalize("  too   many   spaces  ") == "too many spaces"

    def test_empty(self):
        assert _normalize("") == ""


class TestPathScore:
    def test_recycle_bin(self):
        assert _path_score("/volume/#recycle/track.flac") >= 100

    def test_playlists_folder(self):
        assert _path_score("/music/- playlists/track.flac") >= 50

    def test_playlists_subfolder(self):
        assert _path_score("/music/playlists/summer/track.flac") >= 50

    def test_numbered_suffix(self):
        assert _path_score("/music/track_01.flac") >= 30

    def test_canonical_path_scores_low(self):
        assert _path_score("/music/Artist/Album/track.flac") < 30

    def test_deeper_path_scores_higher(self):
        shallow = _path_score("/a/b/track.flac")
        deep = _path_score("/a/b/c/d/e/track.flac")
        assert deep > shallow


class TestFindDuplicateGroups:
    def _seed_isrc_dupes(self, db):
        """Two copies of same ISRC+album, different paths and qualities."""
        db.record("/music/Artist/Album/01.flac", status="tagged", isrc="US123",
                  artist="A", title="Song", album="Alb", duration=200,
                  quality="96000Hz/24bit", fmt="FLAC")
        db.record("/music/playlists/summer/01.flac", status="tagged", isrc="US123",
                  artist="A", title="Song", album="Alb", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.commit()

    def test_isrc_grouping(self, db):
        self._seed_isrc_dupes(db)
        groups = _find_duplicate_groups(db)
        assert len(groups) == 1
        assert groups[0]["key"].startswith("isrc:")
        assert len(groups[0]["duplicates"]) == 1

    def test_keeper_is_higher_quality(self, db):
        self._seed_isrc_dupes(db)
        groups = _find_duplicate_groups(db)
        keeper = groups[0]["keeper"]
        assert "96000Hz/24bit" in keeper["quality"]

    def test_title_artist_fallback(self, db):
        """ISRC-less tracks grouped by normalized title+artist+duration."""
        db.record("/a/song.flac", status="tagged", artist="Artist", title="Song",
                  album="A1", duration=200, quality="44100Hz/16bit", fmt="FLAC")
        db.record("/b/song.flac", status="tagged", artist="Artist", title="Song",
                  album="A1", duration=201, quality="44100Hz/16bit", fmt="FLAC")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 1
        assert groups[0]["key"].startswith("meta:")

    def test_duration_tolerance_exceeded(self, db):
        """Duration difference > 2s = not duplicates."""
        db.record("/a/song.flac", status="tagged", artist="A", title="S",
                  duration=200, quality="44100Hz/16bit", fmt="FLAC")
        db.record("/b/song.flac", status="tagged", artist="A", title="S",
                  duration=210, quality="44100Hz/16bit", fmt="FLAC")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 0

    def test_single_track_no_group(self, db):
        db.record("/a.flac", status="tagged", isrc="UNIQUE", artist="A",
                  title="Solo", album="X", duration=200)
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 0

    def test_unreadable_excluded(self, db):
        db.record("/a.flac", status="tagged", isrc="DUP1", artist="A",
                  title="X", album="A", duration=200)
        db.record("/b.flac", status="unreadable", isrc="DUP1", artist="A",
                  title="X", album="A", duration=200)
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 0


class TestManifest:
    def test_write_and_read(self, tmp_path):
        moved = [{"original": "/a.flac", "staged": "/tmp/x.flac", "db_row": {}}]
        _write_manifest(tmp_path, moved, time.time() + 300)
        manifest = _read_manifest(tmp_path)
        assert manifest is not None
        assert len(manifest["moved_files"]) == 1

    def test_read_missing(self, tmp_path):
        assert _read_manifest(tmp_path) is None

    def test_read_corrupt(self, tmp_path):
        (tmp_path / "manifest.json").write_text("not json{{{")
        assert _read_manifest(tmp_path) is None


class TestLock:
    def test_acquire_release(self, tmp_path):
        with patch("tidal_dl.gui.api.duplicates.path_config_base", return_value=str(tmp_path)):
            assert not _is_cleanup_running()
            _acquire_lock()
            assert _is_cleanup_running()
            _release_lock()
            assert not _is_cleanup_running()

    def test_stale_lock_auto_cleared(self, tmp_path):
        with patch("tidal_dl.gui.api.duplicates.path_config_base", return_value=str(tmp_path)):
            _acquire_lock()
            lp = _lock_path()
            # Backdate the lock file to 15 minutes ago
            old_time = time.time() - 900
            os.utime(str(lp), (old_time, old_time))
            assert not _is_cleanup_running()  # should auto-clear


class TestCleanupCycle:
    """Integration test: preview → clean → undo with real temp files."""

    def _setup(self, tmp_path, db):
        """Create two duplicate files and register them in DB."""
        music = tmp_path / "music"
        music.mkdir()
        keeper = music / "Artist" / "Album"
        keeper.mkdir(parents=True)
        dupe = music / "playlists" / "summer"
        dupe.mkdir(parents=True)

        (keeper / "01.flac").write_bytes(b"keeper audio data")
        (dupe / "01.flac").write_bytes(b"duplicate audio data")

        db.record(str(keeper / "01.flac"), status="tagged", isrc="US123",
                  artist="A", title="Song", album="Alb", duration=200,
                  quality="96000Hz/24bit", fmt="FLAC")
        db.record(str(dupe / "01.flac"), status="tagged", isrc="US123",
                  artist="A", title="Song", album="Alb", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.commit()
        return keeper / "01.flac", dupe / "01.flac"

    def test_full_cycle(self, tmp_path, db):
        keeper_path, dupe_path = self._setup(tmp_path, db)
        staging = tmp_path / "staging"

        # Verify duplicates detected
        groups = _find_duplicate_groups(db)
        assert len(groups) == 1

        # Verify keeper is the higher-quality one
        assert groups[0]["keeper"]["path"] == str(keeper_path)

        # Verify dupe file exists before cleanup
        assert dupe_path.exists()
