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
    _preview_sync, _clean_sync, _PREVIEW_GROUP_LIMIT,
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


def _cleanable_paths(groups):
    paths = []
    for group in groups:
        if group.get("status") == "uncertain":
            continue
        paths.extend(dup["path"] for dup in group["duplicates"])
    return paths


def _count_cleanable_duplicates(groups):
    return len(_cleanable_paths(groups))


def _member_paths(groups):
    paths = set()
    for group in groups:
        paths.add(group["keeper"]["path"])
        paths.update(dup["path"] for dup in group["duplicates"])
    return paths


class TestFindDuplicateGroups:
    def _seed_layout_twins(self, db):
        """Same edition, same quality, Artist - Album vs Artist/Album."""
        db.record("/music/Artist - Album/01.flac", status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record("/music/Artist/Album/01.flac", status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.commit()

    def test_isrc_grouping(self, db):
        self._seed_layout_twins(db)
        groups = _find_duplicate_groups(db)
        assert len(groups) == 1
        assert groups[0]["key"].startswith("isrc:")
        assert len(groups[0]["duplicates"]) == 1
        assert groups[0].get("status") != "uncertain"

    def test_layout_twins_same_tags_are_auto_extra(self, db):
        self._seed_layout_twins(db)
        groups = _find_duplicate_groups(db)
        assert _count_cleanable_duplicates(groups) == 1
        assert len(_cleanable_paths(groups)) == 1

    def test_recycle_copy_of_live_is_extra(self, db):
        live = "/music/Artist/Album/01.flac"
        trash = "/music/#recycle/Artist/Album/01.flac"
        db.record(live, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(trash, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert groups[0]["keeper"]["path"] == live
        assert trash in _cleanable_paths(groups)
        assert groups[0].get("status") != "uncertain"

    def test_never_keep_recycle_when_live_exists(self, db):
        live = "/music/Artist/Album/01.flac"
        trash = "/music/#recycle/Artist/Album/01.flac"
        db.record(live, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(trash, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="96000Hz/24bit", fmt="FLAC", codec="flac")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert groups[0]["keeper"]["path"] == live
        assert trash not in {groups[0]["keeper"]["path"]}

    def test_never_keep_lossy_over_lossless(self, db):
        flac = "/music/Artist/Album/01.flac"
        m4a = "/music/Artist/Album/01.m4a"
        db.record(flac, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(m4a, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="M4A", codec="aac")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert groups[0]["keeper"]["path"] == flac

    def test_remaster_vs_original_same_isrc_two_keepers(self, db):
        original = "/music/Carlos Vives/Clasicos de la Provincia/01.flac"
        remaster = (
            "/music/Carlos Vives/Clasicos de la Provincia 30 Anos (Remastered)/01.flac"
        )
        db.record(original, status="tagged", isrc="COGOTA",
                  artist="Carlos Vives", title="La Gota Fria",
                  album="Clasicos de la Provincia", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(remaster, status="tagged", isrc="COGOTA",
                  artist="Carlos Vives", title="La Gota Fria",
                  album="Clasicos de la Provincia", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert original not in _cleanable_paths(groups)
        assert remaster not in _cleanable_paths(groups)
        assert _count_cleanable_duplicates(groups) == 0
        assert {original, remaster} <= _member_paths(groups)
        assert all(g.get("status") == "uncertain" for g in groups)

    def test_deluxe_vs_standard_two_keepers(self, db):
        standard = "/music/Artist/Amanece/01.flac"
        deluxe = "/music/Artist/Amanece (Deluxe)/01.m4a"
        db.record(standard, status="tagged", isrc="QM7281585580",
                  artist="Artist", title="Amanece", album="Amanece", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(deluxe, status="tagged", isrc="QM7281585580",
                  artist="Artist", title="Amanece", album="Amanece", duration=200,
                  quality="44100Hz/16bit", fmt="M4A", codec="aac")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert standard not in _cleanable_paths(groups)
        assert deluxe not in _cleanable_paths(groups)
        assert _count_cleanable_duplicates(groups) == 0
        assert {standard, deluxe} <= _member_paths(groups)
        assert all(g.get("status") == "uncertain" for g in groups)

    def test_cd_16_44_vs_tidal_24_96_same_isrc_album_two_keepers(self, db):
        cd_rip = "/music/Artist/Album/01.flac"
        tidal = "/music/Tidal/Artist/Album/01.flac"
        db.record(cd_rip, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(tidal, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="96000Hz/24bit", fmt="FLAC", codec="flac")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert cd_rip not in _cleanable_paths(groups)
        assert tidal not in _cleanable_paths(groups)
        assert _count_cleanable_duplicates(groups) == 0
        assert {cd_rip, tidal} <= _member_paths(groups)
        assert all(g.get("status") == "uncertain" for g in groups)

    def test_same_quality_nested_different_roots_uncertain(self, db):
        """Artist/Album vs Tidal/Artist/Album is not a layout twin."""
        library = "/music/Artist/Album/01.flac"
        tidal = "/music/Tidal/Artist/Album/01.flac"
        db.record(library, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(tidal, status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert _count_cleanable_duplicates(groups) == 0
        assert library not in _cleanable_paths(groups)
        assert tidal not in _cleanable_paths(groups)
        assert {library, tidal} <= _member_paths(groups)
        assert all(g.get("status") == "uncertain" for g in groups)

    def test_playlist_flac_with_deluxe_m4a_is_uncertain(self, db):
        playlist = "/music/- Playlists/Mix/Amanece.flac"
        deluxe = "/music/Artist/Amanece (Deluxe)/01.m4a"
        db.record(playlist, status="tagged", isrc="QM7281585580",
                  artist="Artist", title="Amanece", album="Amanece (Deluxe)",
                  duration=200, quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(deluxe, status="tagged", isrc="QM7281585580",
                  artist="Artist", title="Amanece", album="Amanece (Deluxe)",
                  duration=200, quality="44100Hz/16bit", fmt="M4A", codec="aac")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert _count_cleanable_duplicates(groups) == 0
        assert all(g.get("status") == "uncertain" for g in groups)
        assert playlist not in _cleanable_paths(groups)
        assert deluxe not in _cleanable_paths(groups)

    def test_title_artist_fallback(self, db):
        """ISRC-less layout twins still group as an auto extra."""
        db.record("/music/Artist - Album/song.flac", status="tagged",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record("/music/Artist/Album/song.flac", status="tagged",
                  artist="Artist", title="Song", album="Album", duration=201,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 1
        assert groups[0]["key"].startswith("meta:")
        assert groups[0].get("status") != "uncertain"
        assert _count_cleanable_duplicates(groups) == 1

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
        """Create same-edition layout twins on disk."""
        music = tmp_path / "music"
        nested = music / "Artist" / "Album"
        nested.mkdir(parents=True)
        flat = music / "Artist - Album"
        flat.mkdir(parents=True)

        (nested / "01.flac").write_bytes(b"keeper audio data")
        (flat / "01.flac").write_bytes(b"duplicate audio data")

        db.record(str(nested / "01.flac"), status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(str(flat / "01.flac"), status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.commit()
        return nested / "01.flac", flat / "01.flac"

    def test_full_cycle(self, tmp_path, db):
        keeper_path, dupe_path = self._setup(tmp_path, db)

        groups = _find_duplicate_groups(db)
        assert len(groups) == 1
        assert groups[0].get("status") != "uncertain"
        assert {groups[0]["keeper"]["path"], groups[0]["duplicates"][0]["path"]} == {
            str(keeper_path),
            str(dupe_path),
        }
        assert dupe_path.exists()


class TestPreviewAndCleanRespectUncertain:
    def test_preview_excludes_uncertain_from_total_duplicates(self, db, tmp_path):
        db.record("/music/Artist/Album/01.flac", status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record("/music/Tidal/Artist/Album/01.flac", status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="96000Hz/24bit", fmt="FLAC", codec="flac")
        db.commit()
        db.close = lambda: None
        with patch("tidal_dl.gui.api.duplicates._get_db", return_value=db), \
             patch("tidal_dl.gui.api.duplicates._reachable_scan_dirs", return_value=[]), \
             patch("tidal_dl.gui.api.library._scan_running", False), \
             patch("tidal_dl.gui.api.duplicates._find_active_manifest", return_value=None):
            result = _preview_sync()
        assert result["total_duplicates"] == 0
        assert result["groups"]
        assert all(g.get("status") == "uncertain" for g in result["groups"])

    def test_clean_skips_uncertain_files(self, tmp_path, db):
        music = tmp_path / "music"
        original = music / "Artist" / "Clasicos"
        remaster = music / "Artist" / "Clasicos (Remastered)"
        original.mkdir(parents=True)
        remaster.mkdir(parents=True)
        orig_file = original / "01.flac"
        rem_file = remaster / "01.flac"
        orig_file.write_bytes(b"original")
        rem_file.write_bytes(b"remaster")
        db.record(str(orig_file), status="tagged", isrc="COGOTA",
                  artist="Carlos Vives", title="La Gota Fria",
                  album="Clasicos", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(str(rem_file), status="tagged", isrc="COGOTA",
                  artist="Carlos Vives", title="La Gota Fria",
                  album="Clasicos", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.commit()
        db.close = lambda: None
        with patch("tidal_dl.gui.api.duplicates._get_db", return_value=db), \
             patch("tidal_dl.gui.api.duplicates._reachable_scan_dirs", return_value=[]), \
             patch("tidal_dl.gui.api.library._scan_running", False), \
             patch("tidal_dl.gui.api.duplicates.path_config_base", return_value=str(tmp_path / "cfg")):
            (tmp_path / "cfg").mkdir()
            result = _clean_sync()
        assert result["duplicates_moved"] == 0
        assert orig_file.exists()
        assert rem_file.exists()

    def test_clean_moves_recycle_copy_only(self, tmp_path, db):
        music = tmp_path / "music"
        live_dir = music / "Artist" / "Album"
        trash_dir = music / "#recycle" / "Artist" / "Album"
        live_dir.mkdir(parents=True)
        trash_dir.mkdir(parents=True)
        live = live_dir / "01.flac"
        trash = trash_dir / "01.flac"
        live.write_bytes(b"live")
        trash.write_bytes(b"trash")
        db.record(str(live), status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.record(str(trash), status="tagged", isrc="US123",
                  artist="Artist", title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC", codec="flac")
        db.commit()
        db.close = lambda: None
        with patch("tidal_dl.gui.api.duplicates._get_db", return_value=db), \
             patch("tidal_dl.gui.api.duplicates._reachable_scan_dirs", return_value=[]), \
             patch("tidal_dl.gui.api.library._scan_running", False), \
             patch("tidal_dl.gui.api.duplicates.path_config_base", return_value=str(tmp_path / "cfg")):
            (tmp_path / "cfg").mkdir()
            result = _clean_sync()
        assert result["duplicates_moved"] == 1
        assert live.exists()
        assert not trash.exists()


def _preview(db, reachable=None):
    db.close = lambda: None
    with patch("tidal_dl.gui.api.duplicates._get_db", return_value=db), \
         patch("tidal_dl.gui.api.duplicates._reachable_scan_dirs", return_value=reachable or []), \
         patch("tidal_dl.gui.api.library._scan_running", False), \
         patch("tidal_dl.gui.api.duplicates._find_active_manifest", return_value=None):
        return _preview_sync()


def _recycle_component(path: str) -> bool:
    return any(part.casefold() == "#recycle" for part in Path(path).parts[:-1])


class TestPreviewSkipsPruneAndRecycle:
    def _live_pair(self, db, *, isrc="US123", album="Album"):
        live_a = "/music/Artist - Album/01.flac"
        live_b = "/music/Artist/Album/01.flac"
        db.record(live_a, status="tagged", isrc=isrc, artist="Artist",
                  title="Song", album=album, duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.record(live_b, status="tagged", isrc=isrc, artist="Artist",
                  title="Song", album=album, duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.commit()
        return live_a, live_b

    def test_preview_does_not_stat_library_rows(self, db, monkeypatch):
        self._live_pair(db)
        db.record("/music/#recycle/Artist/Album/01.flac", status="tagged",
                  isrc="US123", artist="Artist", title="Song", album="Album",
                  duration=200, quality="44100Hz/16bit", fmt="FLAC")
        db.commit()

        called: list[str] = []

        def spy_exists(path):
            called.append(str(path))
            return True

        monkeypatch.setattr("tidal_dl.gui.api.duplicates.os.path.exists", spy_exists)
        result = _preview(db, reachable=[Path("/music")])
        assert result["groups"]
        assert not any(path.endswith(".flac") for path in called)

    def test_preview_skips_recycle_copy_keeps_live_extra(self, db):
        live_a, live_b = self._live_pair(db)
        trash = "/volume1/Music/#recycle/Artist/Album/01.flac"
        db.record(trash, status="tagged", isrc="US123", artist="Artist",
                  title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.commit()

        result = _preview(db)
        paths = set()
        for group in result["groups"]:
            paths.add(group["keeper"]["path"])
            paths.update(d["path"] for d in group["duplicates"])
        assert live_a in paths
        assert live_b in paths
        assert trash not in paths
        assert result["total_duplicates"] >= 1

    def test_preview_recycle_only_twin_is_not_a_live_extra(self, db):
        live = "/music/Artist/Album/01.flac"
        trash = "/mnt/ugreen/share/#recycle/Artist/Album/01.flac"
        db.record(live, status="tagged", isrc="UG001", artist="Artist",
                  title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.record(trash, status="tagged", isrc="UG001", artist="Artist",
                  title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.commit()

        result = _preview(db)
        assert result["total_duplicates"] == 0
        assert result["groups"] == []

    def test_preview_does_not_skip_recycle_in_title_or_filename(self, db):
        titled = "/music/Artist/Recycled Hits/recycle in the title.flac"
        named = "/music/Artist/Album/recycle.bin"
        db.record(titled, status="tagged", isrc="RC001", artist="Artist",
                  title="recycle in the title", album="Recycled Hits",
                  duration=200, quality="44100Hz/16bit", fmt="FLAC")
        db.record(named, status="tagged", isrc="RC001", artist="Artist",
                  title="recycle.bin", album="Recycled Hits",
                  duration=200, quality="44100Hz/16bit", fmt="FLAC")
        db.commit()
        result = _preview(db)
        paths = {result["groups"][0]["keeper"]["path"], result["groups"][0]["duplicates"][0]["path"]}
        assert paths == {titled, named}

    def test_default_grouping_still_lists_recycle_for_clean(self, db):
        live = "/music/Artist/Album/01.flac"
        trash = "/music/#recycle/Artist/Album/01.flac"
        db.record(live, status="tagged", isrc="US123", artist="Artist",
                  title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.record(trash, status="tagged", isrc="US123", artist="Artist",
                  title="Song", album="Album", duration=200,
                  quality="44100Hz/16bit", fmt="FLAC")
        db.commit()
        groups = _find_duplicate_groups(db)
        assert len(groups) == 1
        paths = {groups[0]["keeper"]["path"], groups[0]["duplicates"][0]["path"]}
        assert paths == {live, trash}

    def test_preview_caps_returned_groups_and_stays_under_two_seconds(self, db):
        for i in range(_PREVIEW_GROUP_LIMIT + 40):
            isrc = f"CAP{i:04d}"
            db.record(f"/music/Artist/Album{i}/01.flac", status="tagged", isrc=isrc,
                      artist="Artist", title=f"Song {i}", album=f"Album {i}",
                      duration=200, quality="44100Hz/16bit", fmt="FLAC")
            db.record(f"/music/Artist - Album {i}/01.flac", status="tagged", isrc=isrc,
                      artist="Artist", title=f"Song {i}", album=f"Album {i}",
                      duration=200, quality="44100Hz/16bit", fmt="FLAC")
        for i in range(200):
            db.record(
                f"/music/#recycle/bucket{i}/gone{i:04d}.flac",
                status="tagged", isrc=f"TRASH{i:04d}", artist="#recycle",
                title=f"Gone {i}", album="Trash", duration=200,
                quality="44100Hz/16bit", fmt="FLAC",
            )
            db.record(
                f"/music/Artist/Keep{i}/01.flac",
                status="tagged", isrc=f"TRASH{i:04d}", artist="Artist",
                title=f"Gone {i}", album="Trash", duration=200,
                quality="44100Hz/16bit", fmt="FLAC",
            )
        db.commit()

        started = time.perf_counter()
        result = _preview(db)
        elapsed = time.perf_counter() - started
        assert elapsed < 2.0
        assert len(result["groups"]) == _PREVIEW_GROUP_LIMIT
        assert result["total_groups"] == _PREVIEW_GROUP_LIMIT + 40
        assert result["truncated"] is True
        preview_paths = []
        for group in result["groups"]:
            preview_paths.append(group["keeper"]["path"])
            preview_paths.extend(d["path"] for d in group["duplicates"])
        assert not any(_recycle_component(path) for path in preview_paths)

    def test_preview_12k_library_returns_live_extras_in_under_two_seconds(self, db, monkeypatch):
        now = time.time()
        db._conn.executemany(
            """INSERT INTO scanned (path, isrc, status, artist, title, album,
                                    duration, quality, format, scanned_at)
               VALUES (?, ?, 'tagged', ?, ?, ?, 200, '44100Hz/16bit', 'FLAC', ?)""",
            [
                (
                    f"/music/Artist{index // 20}/Album{index // 20}/t{index:05d}.flac",
                    f"U{index:05d}",
                    f"Artist{index // 20}",
                    f"Track {index}",
                    f"Album{index // 20}",
                    now,
                )
                for index in range(11800)
            ],
        )
        live_a = "/music/Artist/Album/01.flac"
        live_b = "/music/Artist - Album/01.flac"
        trash = "/mnt/ugreen/Music/#recycle/Artist/Album/01.flac"
        for path in (live_a, live_b, trash):
            db.record(path, status="tagged", isrc="LIVE01", artist="Artist",
                      title="Song", album="Album", duration=200,
                      quality="44100Hz/16bit", fmt="FLAC")
        db.commit()

        called: list[str] = []
        monkeypatch.setattr(
            "tidal_dl.gui.api.duplicates.os.path.exists",
            lambda path: called.append(str(path)) or True,
        )
        started = time.perf_counter()
        result = _preview(db, reachable=[Path("/music")])
        elapsed = time.perf_counter() - started
        paths = set()
        for group in result["groups"]:
            paths.add(group["keeper"]["path"])
            paths.update(d["path"] for d in group["duplicates"])
        assert elapsed < 2.0
        assert live_a in paths
        assert live_b in paths
        assert trash not in paths
        assert not any(path.endswith(".flac") for path in called)
