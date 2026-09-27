"""test_phase3_duplicate_resolution.py

Unit tests for Phase 3: pre-flight ISRC duplicate resolution.

Covers:
  - LibraryDB.primary_path_for_isrc() returns stored path without pruning
  - _preflight_isrc_scan splits hits correctly
  - Saved preference bypasses prompt
  - 'copy' action produces COPIED outcome
  - 'redownload' bypasses ISRC check
  - Missing-source fallback under saved 'copy' preference
  - DownloadSummary counts COPIED correctly
  - duplicate_action config field exists with default 'copy'
"""

import pathlib
from concurrent.futures import Future
from threading import Event
from unittest.mock import MagicMock, patch

from tidalapi.media import Track, Video

from tidal_dl.helper.checkpoint import STATUS_DOWNLOADED
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.model.cfg import Settings as CfgSettings
from tidal_dl.model.downloader import DownloadOutcome, DownloadSummary

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
# LibraryDB.primary_path_for_isrc
# ---------------------------------------------------------------------------


class TestLibraryDbPrimaryPath:
    """primary_path_for_isrc() returns stored value without pruning stale entries."""

    def test_returns_none_for_unknown_isrc(self, tmp_path):
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        assert db.primary_path_for_isrc("US-ABC-00-00001") is None
        db.close()

    def test_returns_path_for_known_isrc(self, tmp_path):
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        p = tmp_path / "track.flac"
        p.touch()
        db.register_isrc_path("US-ABC-00-00001", p, commit=True)
        result = db.primary_path_for_isrc("US-ABC-00-00001")
        assert result == str(p.resolve())
        db.close()

    def test_does_not_prune_missing_file(self, tmp_path):
        """primary_path_for_isrc must still return fallback even if the file is gone."""
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        p = tmp_path / "gone.flac"
        p.touch()
        db.register_isrc_path("US-ABC-00-00002", p, commit=True)
        p.unlink()

        result = db.primary_path_for_isrc("US-ABC-00-00002")
        assert result is not None
        assert "gone.flac" in result
        db.close()

    def test_returns_none_for_empty_isrc(self, tmp_path):
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        assert db.primary_path_for_isrc("") is None
        db.close()

    def test_persists_across_reopen(self, tmp_path):
        db_path = tmp_path / "library.db"
        db = LibraryDB(db_path)
        db.open()
        p = tmp_path / "track.flac"
        p.touch()
        db.register_isrc_path("US-XYZ-00-00001", p, commit=True)
        db.close()

        db2 = LibraryDB(db_path)
        db2.open()
        assert db2.primary_path_for_isrc("US-XYZ-00-00001") == str(p.resolve())
        db2.close()


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

    def test_default_value_is_copy(self):
        cfg = CfgSettings()
        assert cfg.duplicate_action == "copy"


# ---------------------------------------------------------------------------
# _preflight_isrc_scan
# ---------------------------------------------------------------------------


def _make_download_obj(tmp_path, isrc_data: dict[str, str], duplicate_action: str = "skip"):
    """Build a minimal Download-like object for testing preflight scan."""
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    for isrc, path_str in isrc_data.items():
        db.record(path=path_str, status="downloaded", isrc=isrc)
    db.commit()

    settings_data = MagicMock()
    settings_data.skip_duplicate_isrc = True
    settings_data.duplicate_action = duplicate_action

    settings = MagicMock()
    settings.data = settings_data
    settings.save = MagicMock()

    dl = MagicMock()
    dl._library_db = db
    dl._library_db_for_current_thread = lambda: db
    dl.settings = settings
    dl.fn_logger = MagicMock()

    # Bind the real method to our mock object
    from tidal_dl.download import Download

    dl._preflight_isrc_scan = Download._preflight_isrc_scan.__get__(dl, type(dl))
    dl._prompt_duplicate_action = Download._prompt_duplicate_action.__get__(dl, type(dl))

    return dl


class TestPreflightIsrcScan:
    def test_returns_empty_when_isrc_dedup_disabled(self, tmp_path):
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

    def test_album_copies_existing_source(self, tmp_path):
        source = tmp_path / "track.flac"
        source.touch()
        dl = _make_download_obj(tmp_path, {"US-ABC-00-00010": str(source)}, duplicate_action="skip")

        track = _make_track(10, "US-ABC-00-00010")
        result = dl._preflight_isrc_scan([track], ensure_complete=True)
        assert result == {"10": "copy"}

    def test_album_redownloads_missing_source(self, tmp_path):
        dl = _make_download_obj(
            tmp_path,
            {"US-ABC-00-00011": str(tmp_path / "gone.flac")},
            duplicate_action="skip",
        )
        track = _make_track(11, "US-ABC-00-00011")
        result = dl._preflight_isrc_scan([track], ensure_complete=True)
        assert result == {"11": "redownload"}

    def test_album_ignores_saved_skip_preference(self, tmp_path):
        """Even if duplicate_action='skip' is saved, albums always copy/redownload."""
        source = tmp_path / "track.flac"
        source.touch()
        dl = _make_download_obj(tmp_path, {"US-ABC-00-00012": str(source)}, duplicate_action="skip")

        track = _make_track(12, "US-ABC-00-00012")
        result = dl._preflight_isrc_scan([track], ensure_complete=True)
        # Must be 'copy', NOT 'skip'
        assert result == {"12": "copy"}

    def test_skips_checkpoint_downloaded_tracks_only_when_the_dest_file_exists(self, tmp_path):
        source = tmp_path / "track.flac"
        source.touch()
        dest = tmp_path / "out" / "track.flac"
        dest.parent.mkdir()
        dest.write_bytes(b"flac")
        dl = _make_download_obj(tmp_path, {"US-ABC-00-00007": str(source)}, duplicate_action="skip")
        dl.skip_existing = False
        dl.path_base = str(tmp_path / "out")

        def prepare(media, template, quality, pos, total, bypass_isrc=False):
            return dest, ".flac", dest.is_file(), False

        dl._prepare_file_paths_and_skip_logic = prepare
        track = _make_track(7, "US-ABC-00-00007")
        checkpoint = MagicMock()
        from tidal_dl.helper.checkpoint import STATUS_DOWNLOADED

        checkpoint.status_of.return_value = STATUS_DOWNLOADED

        present = dl._preflight_isrc_scan(
            [track], checkpoint=checkpoint, file_template="{track_title}"
        )
        assert present == {}

        dest.unlink()
        missing = dl._preflight_isrc_scan(
            [track], checkpoint=checkpoint, file_template="{track_title}"
        )
        assert missing == {"7": "skip"}


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
        dl._library_db = LibraryDB(tmp_path / "library.db")
        dl._library_db.open()
        return dl

    def test_copy_copies_file_to_destination(self, tmp_path):
        src = tmp_path / "src.flac"
        src.write_bytes(b"audio data")

        dl = self._build_minimal_download(tmp_path)
        dl._library_db.register_isrc_path("US-TST-00-00001", src, commit=True)

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
        dest_flac = pathlib.Path(result_path)
        assert dest_flac.is_file()
        assert dest_flac.read_bytes() == b"audio data"

    def test_copy_keeps_the_audio_when_copystat_hits_smb_arch_flag(self, tmp_path, monkeypatch):
        """macOS `arch` on an SMB source makes shutil.copystat raise EPERM. The bytes still land."""
        import shutil

        src = tmp_path / "src.flac"
        src.write_bytes(b"audio data")

        def reject_flags(_src, _dst, **_kwargs):
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(shutil, "copystat", reject_flags)
        dl = self._build_minimal_download(tmp_path)
        dl._library_db.register_isrc_path("US-TST-00-00002", src, commit=True)

        track = _make_track(100, "US-TST-00-00002")
        track.isrc = "US-TST-00-00002"
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
        dest_flac = pathlib.Path(result_path)
        assert dest_flac.is_file()
        assert dest_flac.read_bytes() == b"audio data"
        assert dl.fn_logger.warning.called

    def test_copy_io_error_fails_only_that_track(self, tmp_path, monkeypatch):
        import shutil

        src = tmp_path / "src.flac"
        src.write_bytes(b"audio data")

        def reject_data(_src, _dst, **_kwargs):
            raise OSError("read failed")

        monkeypatch.setattr(shutil, "copyfile", reject_data)
        dl = self._build_minimal_download(tmp_path)
        dl._library_db.register_isrc_path("US-TST-00-00003", src, commit=True)

        track = _make_track(101, "US-TST-00-00003")
        track.isrc = "US-TST-00-00003"
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

        assert outcome == DownloadOutcome.FAILED
        assert not (tmp_path / "output" / "dest.flac").is_file()
        assert result_path == ""

    def test_prepare_paths_skip_existing_uses_canonical_path(self, tmp_path):
        """skip_existing must check the canonical path before any _01 uniquify."""
        dl = self._build_minimal_download(tmp_path)

        track = _make_track(101, "US-TST-00-01001")
        track.full_name = "Track 101"
        track.name = "Track 101"
        track.media_metadata_tags = []
        track.album = MagicMock()

        existing = tmp_path / "output" / "Track 101.flac"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"existing")

        with patch.object(dl, "extension_guess", return_value=".flac"):
            path_media_dst, file_extension_dummy, skip_file, skip_download = dl._prepare_file_paths_and_skip_logic(
                track,
                "{track_title}",
                None,
                0,
                0,
            )

        assert path_media_dst == existing.absolute()
        assert file_extension_dummy == ".flac"
        assert skip_file is True
        assert skip_download is False

    def test_item_returns_and_indexes_final_stream_extension(self, tmp_path):
        """item() must report the final stream extension, not the dummy guess."""
        dl = self._build_minimal_download(tmp_path)

        track = _make_track(102, "US-TST-00-01002")
        track.isrc = "US-TST-00-01002"
        track.full_name = "Track 102"
        track.name = "Track 102"
        track.media_metadata_tags = []
        track.album = MagicMock()
        track.allow_streaming = True

        dummy_path = (tmp_path / "output" / "Track 102.flac").absolute()
        final_path = dummy_path.with_suffix(".m4a")

        with (
            patch.object(dl, "_validate_and_prepare_media", return_value=track),
            patch.object(dl, "_prepare_file_paths_and_skip_logic", return_value=(dummy_path, ".flac", False, False)),
            patch.object(dl, "_adjust_quality_settings", return_value=(None, None)),
            patch.object(dl, "_get_stream_info", return_value=(MagicMock(), ".m4a", False, None)),
            patch.object(dl, "_perform_actual_download", return_value=True),
            patch.object(dl, "_perform_post_processing", return_value=None),
        ):
            outcome, result_path = dl.item(
                file_template="{track_title}",
                media=track,
            )

        assert outcome == DownloadOutcome.DOWNLOADED
        assert result_path == final_path
        assert dl._library_db.primary_path_for_isrc(track.isrc) == str(final_path.resolve())

    def test_detect_downloaded_audio_extension_keeps_planned_flac(self, tmp_path):
        from tidal_dl.download import Download

        dl = self._build_minimal_download(tmp_path)
        detect = Download._detect_downloaded_audio_extension.__get__(dl, Download)

        mp4_path = tmp_path / "download.bin"
        mp4_path.write_bytes(b"\x00\x00\x00\x18ftypiso8\x00\x00\x00\x00payload")

        # Dest planned .flac: do not rename boxed audio to .m4a.
        assert detect(mp4_path, ".flac") == ".flac"
        # AAC/lossy dest stays .m4a when the box is not FLAC.
        assert detect(mp4_path, ".m4a", codecs="aac") == ".m4a"

    def test_item_uses_corrected_extension_from_downloaded_file(self, tmp_path):
        """item() must propagate the final extension detected from downloaded bytes."""
        dl = self._build_minimal_download(tmp_path)

        track = _make_track(103, "US-TST-00-01003")
        track.isrc = "US-TST-00-01003"
        track.full_name = "Track 103"
        track.name = "Track 103"
        track.media_metadata_tags = []
        track.album = MagicMock()
        track.allow_streaming = True

        dummy_path = (tmp_path / "output" / "Track 103.flac").absolute()
        final_path = dummy_path.with_suffix(".m4a")

        with (
            patch.object(dl, "_validate_and_prepare_media", return_value=track),
            patch.object(dl, "_prepare_file_paths_and_skip_logic", return_value=(dummy_path, ".flac", False, False)),
            patch.object(dl, "_adjust_quality_settings", return_value=(None, None)),
            patch.object(dl, "_get_stream_info", return_value=(MagicMock(), ".flac", False, None)),
            patch.object(dl, "_perform_actual_download", return_value=(True, final_path)),
            patch.object(dl, "_perform_post_processing", return_value=None),
        ):
            outcome, result_path = dl.item(
                file_template="{track_title}",
                media=track,
            )

        assert outcome == DownloadOutcome.DOWNLOADED
        assert result_path == final_path
        assert dl._library_db.primary_path_for_isrc(track.isrc) == str(final_path.resolve())


class TestCheckpointOutcomeMapping:
    """COPIED/SKIPPED are terminal successes for checkpoint resume semantics."""

    @staticmethod
    def _run_process_download_futures(outcome: DownloadOutcome):
        from tidal_dl.download import Download

        dl = Download.__new__(Download)
        dl.event_abort = Event()
        process_fn = Download._process_download_futures.__get__(dl, Download)

        progress = MagicMock()
        checkpoint = MagicMock()
        track = _make_track(42, "US-TST-42-00001")

        future = Future()
        future.set_result((outcome, pathlib.Path("C:/tmp/result.flac")))

        process_fn(
            [future],
            progress=progress,
            progress_task=1,
            progress_stdout=True,
            summary=None,
            checkpoint=checkpoint,
            future_to_item={future: track},
        )

        return checkpoint

    def test_copied_marks_checkpoint_downloaded(self):
        checkpoint = self._run_process_download_futures(DownloadOutcome.COPIED)
        checkpoint.mark.assert_called_once_with("42", STATUS_DOWNLOADED)

    def test_skipped_marks_checkpoint_downloaded(self):
        checkpoint = self._run_process_download_futures(DownloadOutcome.SKIPPED)
        checkpoint.mark.assert_called_once_with("42", STATUS_DOWNLOADED)

    def test_one_track_exception_does_not_drop_the_rest(self):
        from tidal_dl.download import Download
        from tidal_dl.helper.checkpoint import STATUS_FAILED

        dl = Download.__new__(Download)
        dl.event_abort = Event()
        dl.fn_logger = MagicMock()
        process_fn = Download._process_download_futures.__get__(dl, Download)

        good_track = _make_track(1, "US-TST-00-00011")
        bad_track = _make_track(2, "US-TST-00-00012")
        good = Future()
        good.set_result((DownloadOutcome.DOWNLOADED, pathlib.Path("/tmp/good.flac")))
        bad = Future()
        bad.set_exception(PermissionError(1, "Operation not permitted"))
        summary = DownloadSummary()
        checkpoint = MagicMock()

        process_fn(
            [bad, good],
            progress=MagicMock(),
            progress_task=1,
            progress_stdout=True,
            summary=summary,
            checkpoint=checkpoint,
            future_to_item={bad: bad_track, good: good_track},
        )

        assert summary.downloaded == 1
        assert summary.failed == 1
        marked = {call.args for call in checkpoint.mark.call_args_list}
        assert ("1", STATUS_DOWNLOADED) in marked
        assert ("2", STATUS_FAILED) in marked


UNAVAILABLE_REASON = "This item is not available for listening anymore on TIDAL."


def _unavailable_track(track_id: int, name: str):
    track = _make_track(track_id, f"US-UNAV-{track_id:05d}")
    track.name = name
    track.allow_streaming = False
    track.album = None
    track.artists = []
    return track


def _run_collection(tmp_path, tracks, bind_item):
    from types import SimpleNamespace

    from rich.progress import Progress
    from tidalapi.album import Album

    from tidal_dl.download import Download

    album = object.__new__(Album)
    album.id = 88
    dl = Download.__new__(Download)
    dl.fn_logger = MagicMock()
    dl.path_base = str(tmp_path / "library")
    dl.event_abort = Event()
    dl.progress = Progress(disable=True)
    dl.progress_overall = None
    dl.settings = SimpleNamespace(
        data=SimpleNamespace(
            downloads_concurrent_max=2,
            playlist_create=False,
            skip_duplicate_isrc=False,
        )
    )
    dl._validate_and_prepare_media = lambda *args, **kwargs: album
    dl._setup_collection_download_context = lambda *args, **kwargs: (
        "{track_title}",
        "La Adictiva",
        "La Adictiva",
        tracks,
        False,
    )
    dl._preflight_isrc_scan = lambda *args, **kwargs: {}
    dl.item = bind_item(dl)
    panels: list[object] = []
    with (
        patch("tidal_dl.download.collections.path_config_base", return_value=str(tmp_path)),
        patch(
            "tidal_dl.download.collections.Console",
            lambda *args, **kwargs: SimpleNamespace(print=panels.append),
        ),
    ):
        ok = dl.items(file_template="{track_title}", media=album)
    text = "\n".join(str(getattr(panel, "renderable", panel)) for panel in panels)
    return ok, text


def _download_real_item(dl, media):
    """Run item() with the real media validator, not the collection stub."""
    from tidal_dl.download import Download

    saved = dl._validate_and_prepare_media
    dl._validate_and_prepare_media = lambda *args, **kwargs: Download._validate_and_prepare_media(dl, *args, **kwargs)
    try:
        return Download.item(dl, "{track_title}", media=media)
    finally:
        dl._validate_and_prepare_media = saved


def test_unavailable_plus_success_exits_zero_and_lists_unavailable(tmp_path):
    """Unavailable tracks are listed on their own and do not fail the command."""
    from tidal_dl.model.downloader import DownloadOutcome

    kept = _make_track(1, "US-TST-00-00021")
    kept.name = "Kept Song"
    kept.allow_streaming = True
    gone = _unavailable_track(2, "Te Quiero")
    downloaded: list[int] = []

    def bind_item(dl):
        def item(media=None, **kwargs):
            if getattr(media, "allow_streaming", True) is False:
                return _download_real_item(dl, media)
            downloaded.append(media.id)
            return DownloadOutcome.DOWNLOADED, tmp_path / "ok.flac"

        return item

    ok, text = _run_collection(tmp_path, [kept, gone], bind_item)

    assert ok is True
    assert downloaded == [1]
    assert "Unavailable on TIDAL" in text
    assert "Te Quiero" in text
    assert UNAVAILABLE_REASON in text
    assert "download failed" not in text


def test_real_failure_stays_separate_from_unavailable(tmp_path):
    """A real failure still exits non-zero. Unavailable tracks stay on their own list."""
    from tidal_dl.download.streams import QualityMismatchError
    from tidal_dl.model.downloader import DownloadOutcome

    kept = _make_track(1, "US-TST-00-00031")
    kept.name = "Kept Song"
    kept.allow_streaming = True
    gone = _unavailable_track(2, "Te Quiero")
    broken = _make_track(3, "US-TST-00-00033")
    broken.name = "Broken Song"
    broken.allow_streaming = True

    def bind_item(dl):
        def item(media=None, **kwargs):
            if getattr(media, "allow_streaming", True) is False:
                return _download_real_item(dl, media)
            if media.id == 3:
                raise QualityMismatchError("requested HI_RES_LOSSLESS but received LOSSLESS")
            return DownloadOutcome.DOWNLOADED, tmp_path / "ok.flac"

        return item

    ok, text = _run_collection(tmp_path, [kept, gone, broken], bind_item)

    assert ok is False
    assert "QualityMismatchError" in text
    assert "requested HI_RES_LOSSLESS but received LOSSLESS" in text
    assert "Unavailable on TIDAL" in text
    assert "Te Quiero" in text
    assert UNAVAILABLE_REASON in text
    assert "Broken Song: download failed" not in text
    failure_line = next(line for line in text.splitlines() if "QualityMismatchError" in line)
    unavailable_line = next(line for line in text.splitlines() if "Te Quiero" in line)
    assert "Unavailable on TIDAL" not in failure_line
    assert "QualityMismatchError" not in unavailable_line


def test_output_file_check_does_not_change_skip_existing(tmp_path):
    from tidal_dl.download.duplicates import track_file_is_in_output

    dest = tmp_path / "song.flac"
    dest.write_bytes(b"flac")
    observed: list[bool] = []

    class Downloader:
        def __init__(self):
            self.skip_existing = False

        def _prepare_file_paths_and_skip_logic(self, *args, **kwargs):
            observed.append(self.skip_existing)
            return dest, ".flac", False, False

    dl = Downloader()
    track = _make_track(7, "US-TST-00-00007")
    assert track_file_is_in_output(dl, track, "{track_title}", 1, 1) is True
    assert observed == [False]
    assert dl.skip_existing is False

    dest.unlink()
    assert track_file_is_in_output(dl, track, "{track_title}", 1, 1) is False
    assert dl.skip_existing is False


def test_quality_mismatch_is_listed_and_the_collection_still_finishes(tmp_path):
    """A per-track QualityMismatchError must not vanish into exit 0."""
    from types import SimpleNamespace

    from rich.progress import Progress
    from tidalapi.album import Album

    from tidal_dl.download import Download
    from tidal_dl.download.streams import QualityMismatchError

    album = object.__new__(Album)
    album.id = 77
    good = _make_track(1, "US-TST-00-00011")
    bad = _make_track(2, "US-TST-00-00012")
    tracks = [good, bad]
    downloaded: list[int] = []

    dl = Download.__new__(Download)
    dl.fn_logger = MagicMock()
    dl.path_base = str(tmp_path / "library")
    dl.event_abort = Event()
    dl.progress = Progress(disable=True)
    dl.progress_overall = None
    dl.settings = SimpleNamespace(
        data=SimpleNamespace(
            downloads_concurrent_max=2,
            playlist_create=False,
            skip_duplicate_isrc=False,
        )
    )
    dl._validate_and_prepare_media = lambda *args, **kwargs: album
    dl._setup_collection_download_context = lambda *args, **kwargs: (
        "{track_title}",
        "The Album",
        "The Album",
        tracks,
        False,
    )
    dl._preflight_isrc_scan = lambda *args, **kwargs: {}

    def item(media=None, **kwargs):
        if getattr(media, "id", None) == 2:
            raise QualityMismatchError("requested HI_RES_LOSSLESS but received LOSSLESS")
        downloaded.append(media.id)
        return DownloadOutcome.DOWNLOADED, pathlib.Path("/tmp/ok.flac")

    dl.item = item
    panels: list[object] = []

    with (
        patch("tidal_dl.download.collections.path_config_base", return_value=str(tmp_path)),
        patch(
            "tidal_dl.download.collections.Console",
            lambda *args, **kwargs: SimpleNamespace(print=panels.append),
        ),
    ):
        ok = dl.items(file_template="{track_title}", media=album)

    assert ok is False
    assert downloaded == [1]
    text = "\n".join(str(getattr(panel, "renderable", panel)) for panel in panels)
    assert "QualityMismatchError" in text
    assert "requested HI_RES_LOSSLESS but received LOSSLESS" in text
    assert "Failed:" in text


def test_checkpoint_path_includes_the_resolved_output_dir(tmp_path):
    from tidal_dl.helper.checkpoint import checkpoint_path_for

    first = checkpoint_path_for(tmp_path, "playlist_9", str(tmp_path / "fresh"))
    second = checkpoint_path_for(tmp_path, "playlist_9", str(tmp_path / "other"))
    stale = tmp_path / "checkpoints" / "playlist_9.json"

    assert first != second
    assert first != stale
    assert first.parent == tmp_path / "checkpoints"
    assert "playlist_9" in first.name
    assert first.name != second.name


def test_checkpoint_skip_requires_the_file_in_this_output_dir(tmp_path):
    """A downloaded checkpoint for another folder must not skip a fresh --output."""
    from rich.progress import Progress

    from tidal_dl.download import Download
    from tidal_dl.helper.checkpoint import STATUS_DOWNLOADED, DownloadCheckpoint

    out = tmp_path / "fresh"
    dest = out / "song.flac"
    dl = Download.__new__(Download)
    dl.settings = type("S", (), {"data": type("D", (), {"downloads_concurrent_max": 1})()})()
    dl.event_abort = Event()
    dl.fn_logger = MagicMock()
    dl.path_base = str(out)
    dl.skip_existing = False
    calls: list[int] = []

    def item(media=None, **kwargs):
        calls.append(media.id)
        return DownloadOutcome.DOWNLOADED, dest

    def prepare(media, template, quality, pos, total, bypass_isrc=False):
        return dest, ".flac", dest.is_file(), False

    dl.item = item
    dl._prepare_file_paths_and_skip_logic = prepare
    track = _make_track(7, "US-TST-00-00007")
    checkpoint = DownloadCheckpoint(
        path=tmp_path / "cp.json",
        collection_id="playlist_9",
        collection_type="playlist",
        output_dir=str(out.resolve()),
    )
    checkpoint.initialize_tracks(["7"])
    checkpoint.mark("7", STATUS_DOWNLOADED)

    def run_once() -> DownloadSummary:
        summary = DownloadSummary()
        with Progress(disable=True) as progress:
            task = progress.add_task("collection", total=1)
            dl._execute_collection_downloads(
                [track],
                "{track_title}",
                None,
                None,
                False,
                False,
                1,
                progress,
                task,
                False,
                summary=summary,
                checkpoint=checkpoint,
            )
        return summary

    missing = run_once()
    assert calls == [7]
    assert missing.skipped == 0
    assert missing.downloaded == 1

    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"full-flac")
    calls.clear()
    present = run_once()
    assert calls == []
    assert present.skipped == 1
    assert present.downloaded == 0
