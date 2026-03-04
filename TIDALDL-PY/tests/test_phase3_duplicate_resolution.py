"""test_phase3_duplicate_resolution.py

Unit tests for Phase 3: pre-flight ISRC duplicate resolution.

Covers:
  - IsrcIndex.get_path() returns stored path without pruning
  - _preflight_isrc_scan splits hits correctly
  - Saved preference bypasses prompt
  - 'copy' action produces COPIED outcome
  - 'redownload' bypasses ISRC check
  - Missing-source fallback under saved 'copy' preference
  - DownloadSummary counts COPIED correctly
  - duplicate_action config field exists with default 'ask'
"""

import pathlib
import shutil
import types
import unittest
from dataclasses import fields
from unittest.mock import MagicMock, patch

import pytest
from tidalapi import Track, Video

from tidal_dl.helper.isrc_index import IsrcIndex
from tidal_dl.model.downloader import DownloadOutcome, DownloadSummary
from tidal_dl.model.cfg import Settings as CfgSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_track(track_id: int, isrc: str | None = None) -> MagicMock:
    """Return a minimal Track-like mock that passes isinstance(x, Track)."""
    track = MagicMock(spec=Track)
    track.id = track_id
    track.isrc = isrc
    track.name = f"Track {track_id}"
    return track


# ---------------------------------------------------------------------------
# IsrcIndex.get_path
# ---------------------------------------------------------------------------

class TestIsrcIndexGetPath:
    """get_path() returns stored value without pruning stale entries."""

    def test_returns_none_for_unknown_isrc(self, tmp_path):
        idx = IsrcIndex(tmp_path / "idx.json")
        assert idx.get_path("US-ABC-00-00001") is None

    def test_returns_path_for_known_isrc(self, tmp_path):
        idx = IsrcIndex(tmp_path / "idx.json")
        p = tmp_path / "track.flac"
        p.touch()
        idx.add("US-ABC-00-00001", p)
        result = idx.get_path("US-ABC-00-00001")
        assert result == str(p.absolute())

    def test_does_not_prune_missing_file(self, tmp_path):
        """get_path must NOT remove entries even if the file is gone."""
        idx = IsrcIndex(tmp_path / "idx.json")
        p = tmp_path / "gone.flac"
        p.touch()
        idx.add("US-ABC-00-00002", p)
        p.unlink()  # Delete the file

        # contains() would prune; get_path() must not
        result = idx.get_path("US-ABC-00-00002")
        assert result is not None
        assert "gone.flac" in result

    def test_returns_none_for_empty_isrc(self, tmp_path):
        idx = IsrcIndex(tmp_path / "idx.json")
        assert idx.get_path("") is None

    def test_persists_across_load_save(self, tmp_path):
        idx_path = tmp_path / "idx.json"
        idx = IsrcIndex(idx_path)
        p = tmp_path / "track.flac"
        p.touch()
        idx.add("US-XYZ-00-00001", p)
        idx.save()

        idx2 = IsrcIndex(idx_path)
        idx2.load()
        assert idx2.get_path("US-XYZ-00-00001") == str(p.absolute())


# ---------------------------------------------------------------------------
# DownloadSummary with COPIED
# ---------------------------------------------------------------------------

class TestDownloadSummaryWithCopied:
    def test_copied_increments_on_record(self):
        s = DownloadSummary()
        s.record(DownloadOutcome.COPIED)
        assert s.copied == 1

    def test_copied_included_in_total(self):
        s = DownloadSummary()
        s.record(DownloadOutcome.DOWNLOADED)
        s.record(DownloadOutcome.COPIED)
        s.record(DownloadOutcome.SKIPPED)
        assert s.total == 3

    def test_downloaded_not_affected_by_copied(self):
        s = DownloadSummary()
        s.record(DownloadOutcome.COPIED)
        assert s.downloaded == 0

    def test_failed_not_affected_by_copied(self):
        s = DownloadSummary()
        s.record(DownloadOutcome.COPIED)
        assert s.failed == 0


# ---------------------------------------------------------------------------
# duplicate_action config field
# ---------------------------------------------------------------------------

class TestDuplicateActionConfig:
    def test_field_exists_in_cfg_settings(self):
        cfg = CfgSettings()
        assert hasattr(cfg, "duplicate_action")

    def test_default_value_is_ask(self):
        cfg = CfgSettings()
        assert cfg.duplicate_action == "ask"


# ---------------------------------------------------------------------------
# _preflight_isrc_scan
# ---------------------------------------------------------------------------

def _make_download_obj(tmp_path, isrc_data: dict[str, str], duplicate_action: str = "skip"):
    """Build a minimal Download-like object for testing preflight scan."""
    from tidal_dl.helper.isrc_index import IsrcIndex

    idx = IsrcIndex(tmp_path / "isrc_index.json")
    for isrc, path_str in isrc_data.items():
        fake_path = pathlib.Path(path_str)
        # add raw without requiring file existence (use internal dict directly)
        with idx._lock:
            idx._data[isrc] = path_str

    settings_data = MagicMock()
    settings_data.skip_duplicate_isrc = True
    settings_data.duplicate_action = duplicate_action

    settings = MagicMock()
    settings.data = settings_data
    settings.save = MagicMock()

    dl = MagicMock()
    dl._isrc_index = idx
    dl.settings = settings
    dl.fn_logger = MagicMock()

    # Bind the real method to our mock object
    from tidal_dl.download import Download
    dl._preflight_isrc_scan = Download._preflight_isrc_scan.__get__(dl, type(dl))
    dl._prompt_duplicate_action = Download._prompt_duplicate_action.__get__(dl, type(dl))

    return dl


class TestPreflightIsrcScan:
    def test_returns_empty_when_isrc_dedup_disabled(self, tmp_path):
        from tidal_dl.download import Download

        dl = _make_download_obj(tmp_path, {})
        dl.settings.data.skip_duplicate_isrc = False

        track = _make_track(1, "US-ABC-00-00001")
        result = dl._preflight_isrc_scan([track])
        assert result == {}

    def test_returns_empty_when_no_hits(self, tmp_path):
        dl = _make_download_obj(tmp_path, {})
        track = _make_track(1, "US-ABC-00-00001")
        result = dl._preflight_isrc_scan([track])
        assert result == {}

    def test_splits_existing_source_correctly(self, tmp_path):
        source = tmp_path / "track.flac"
        source.touch()
        dl = _make_download_obj(tmp_path, {"US-ABC-00-00001": str(source)}, duplicate_action="skip")

        track = _make_track(1, "US-ABC-00-00001")
        result = dl._preflight_isrc_scan([track])
        assert result == {"1": "skip"}

    def test_splits_missing_source_correctly(self, tmp_path):
        dl = _make_download_obj(
            tmp_path,
            {"US-ABC-00-00002": str(tmp_path / "gone.flac")},
            duplicate_action="skip",
        )
        track = _make_track(2, "US-ABC-00-00002")
        result = dl._preflight_isrc_scan([track])
        assert result == {"2": "skip"}

    def test_saved_copy_preference_applied_to_existing_source(self, tmp_path):
        source = tmp_path / "track.flac"
        source.touch()
        dl = _make_download_obj(tmp_path, {"US-ABC-00-00003": str(source)}, duplicate_action="copy")

        track = _make_track(3, "US-ABC-00-00003")
        result = dl._preflight_isrc_scan([track])
        assert result == {"3": "copy"}

    def test_saved_copy_preference_redownloads_missing_source(self, tmp_path):
        dl = _make_download_obj(
            tmp_path,
            {"US-ABC-00-00004": str(tmp_path / "gone.flac")},
            duplicate_action="copy",
        )
        track = _make_track(4, "US-ABC-00-00004")
        result = dl._preflight_isrc_scan([track])
        # Missing source under 'copy' preference → redownload
        assert result == {"4": "redownload"}

    def test_saved_redownload_preference_applied(self, tmp_path):
        source = tmp_path / "track.flac"
        source.touch()
        dl = _make_download_obj(tmp_path, {"US-ABC-00-00005": str(source)}, duplicate_action="redownload")

        track = _make_track(5, "US-ABC-00-00005")
        result = dl._preflight_isrc_scan([track])
        assert result == {"5": "redownload"}

    def test_skips_non_track_items(self, tmp_path):
        source = tmp_path / "track.flac"
        source.touch()
        dl = _make_download_obj(tmp_path, {"US-ABC-00-00006": str(source)}, duplicate_action="skip")

        # Video mock does not pass isinstance(x, Track)
        video = MagicMock(spec=Video)
        result = dl._preflight_isrc_scan([video])
        assert result == {}

    def test_skips_checkpoint_downloaded_tracks(self, tmp_path):
        source = tmp_path / "track.flac"
        source.touch()
        dl = _make_download_obj(tmp_path, {"US-ABC-00-00007": str(source)}, duplicate_action="skip")

        track = _make_track(7, "US-ABC-00-00007")
        checkpoint = MagicMock()
        from tidal_dl.helper.checkpoint import STATUS_DOWNLOADED
        checkpoint.status_of.return_value = STATUS_DOWNLOADED

        result = dl._preflight_isrc_scan([track], checkpoint=checkpoint)
        assert result == {}


# ---------------------------------------------------------------------------
# item() copy action
# ---------------------------------------------------------------------------

class TestItemCopyAction:
    """item() correctly copies source file and returns COPIED outcome."""

    def _build_minimal_download(self, tmp_path):
        """Build enough of a Download to test item() copy path."""
        from threading import Event
        from tidal_dl.download import Download

        tidal = MagicMock()
        tidal.session = MagicMock()
        tidal.active_source = MagicMock()
        tidal.hifi_client = None
        tidal.stream_lock = MagicMock()
        tidal.stream_lock.__enter__ = MagicMock(return_value=None)
        tidal.stream_lock.__exit__ = MagicMock(return_value=False)
        tidal.api_cache = None

        logger = MagicMock()
        abort = Event()
        run = Event()
        run.set()

        with patch("tidal_dl.download.path_config_base", return_value=str(tmp_path)):
            dl = Download(
                tidal_obj=tidal,
                path_base=str(tmp_path / "output"),
                fn_logger=logger,
                skip_existing=True,
                event_abort=abort,
                event_run=run,
            )
        return dl

    def test_copy_copies_file_to_destination(self, tmp_path):
        src = tmp_path / "src.flac"
        src.write_bytes(b"audio data")

        dl = self._build_minimal_download(tmp_path)
        dl._isrc_index.add("US-TST-00-00001", src)

        track = _make_track(99, "US-TST-00-00001")
        track.isrc = "US-TST-00-00001"
        track.album = MagicMock()
        track.allow_streaming = True
        track.media_metadata_tags = []

        with (
            patch.object(dl, "_validate_and_prepare_media", return_value=track),
            patch.object(dl, "_prepare_file_paths_and_skip_logic") as mock_paths,
        ):
            dst = tmp_path / "output" / "dest.flac"
            dst.parent.mkdir(parents=True, exist_ok=True)
            mock_paths.return_value = (dst.with_suffix(".m4a"), ".m4a", False, False)

            outcome, result_path = dl.item(
                file_template="test/{track_title}",
                media=track,
                duplicate_action_override="copy",
            )

        assert outcome == DownloadOutcome.COPIED
        # File should exist at destination (with src extension)
        dest_flac = result_path
        assert dest_flac.is_file()
        assert dest_flac.read_bytes() == b"audio data"
