"""Product-wide upgrade/re-download identity: never mint same-folder twins.

These fixtures are generic library shapes (numbered CD-rip name vs template
name). They must hold for any album/artist, not one catalogue example.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

from tidalapi.media import Track

from tidal_dl.gui.services.upgrade_jobs import cleanup_replaced_track_files
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.recording_identity import (
    adopt_original_name,
    collapse_folder_identity,
    live_identity_paths,
)
from tidal_dl.model.downloader import DownloadOutcome


ISRC_A = "US-LIB-00-00001"
ISRC_B = "GB-LIB-00-00002"


def _flac(path: Path, payload: bytes = b"audio") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _open_db(tmp_path: Path) -> LibraryDB:
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    return db


def _record(
    db: LibraryDB,
    path: Path,
    isrc: str,
    *,
    album: str = "First Album",
    title: str = "Opening",
    artist: str = "Artist One",
    quality: str = "44100Hz/16bit",
    duration: int | None = 181,
) -> None:
    db.record(
        str(path),
        status="tagged",
        isrc=isrc,
        artist=artist,
        title=title,
        album=album,
        quality=quality,
        duration=duration,
        fmt="FLAC",
    )


def _extract_map(mapping: dict[str, str | None]):
    def _extract(path: Path) -> str | None:
        return mapping.get(str(path))
    return _extract


def _make_track(track_id: int, isrc: str, name: str = "Opening") -> MagicMock:
    artist = MagicMock()
    artist.name = "Artist One"
    album = MagicMock()
    album.name = "First Album"
    album.artists = [artist]
    album.num_tracks = 10
    track = MagicMock(spec=Track)
    track.id = track_id
    track.isrc = isrc
    track.name = name
    track.full_name = name
    track.artists = [artist]
    track.artist = artist
    track.album = album
    track.track_num = 1
    track.volume_num = 1
    track.media_metadata_tags = []
    track.allow_streaming = True
    return track


def _download_for_paths(tmp_path: Path, *, skip_existing: bool = True):
    from tidal_dl.download import Download

    tidal = MagicMock()
    tidal.session = MagicMock()
    tidal.active_source = MagicMock()
    tidal.hifi_client = None
    tidal.stream_lock = MagicMock()
    tidal.stream_lock.__enter__ = MagicMock(return_value=None)
    tidal.stream_lock.__exit__ = MagicMock(return_value=False)
    tidal.api_cache = None

    abort = Event()
    run = Event()
    run.set()

    with patch("tidal_dl.download.path_config_base", return_value=str(tmp_path)):
        dl = Download(
            tidal_obj=tidal,
            path_base=str(tmp_path / "library"),
            fn_logger=MagicMock(),
            skip_existing=skip_existing,
            event_abort=abort,
            event_run=run,
        )
    dl._library_db = LibraryDB(tmp_path / "library.db")
    dl._library_db.open()
    dl.settings.data.skip_duplicate_isrc = True
    dl.settings.data.album_track_num_pad_min = 1
    dl.settings.data.filename_delimiter_artist = ", "
    dl.settings.data.filename_delimiter_album_artist = ", "
    dl.settings.data.use_primary_album_artist = False
    return dl


# ---------------------------------------------------------------------------
# Helper: same-folder identity from ISRC / live path
# ---------------------------------------------------------------------------


def test_live_identity_finds_numbered_sibling_via_db(tmp_path):
    album = tmp_path / "Artist One" / "First Album"
    numbered = _flac(album / "01 - Opening.flac")
    dest = album / "Opening.flac"

    db = _open_db(tmp_path)
    _record(db, numbered, ISRC_A)
    db.commit()

    found = live_identity_paths(isrc=ISRC_A, directory=album, db=db, dest_path=dest)
    db.close()

    assert [p.resolve() for p in found] == [numbered.resolve()]


def test_live_identity_recovers_tagged_sibling_when_db_path_is_dead(tmp_path):
    album = tmp_path / "Artist Two" / "Second Record"
    dead = album / "Opening.flac"
    numbered = _flac(album / "03. Opening.flac")
    other = _flac(album / "04 - Other Song.flac")

    db = _open_db(tmp_path)
    _record(db, dead, ISRC_A)
    db.commit()

    found = live_identity_paths(
        isrc=ISRC_A,
        directory=album,
        db=db,
        dest_path=album / "Opening.flac",
        extract_isrc=_extract_map({
            str(numbered): ISRC_A,
            str(other): ISRC_B,
        }),
    )
    db.close()

    assert [p.resolve() for p in found] == [numbered.resolve()]


def test_live_identity_does_not_treat_template_name_as_identity_without_isrc(tmp_path):
    album = tmp_path / "Artist One" / "First Album"
    template_name = _flac(album / "Opening.flac")
    numbered = _flac(album / "01 - Opening.flac")

    db = _open_db(tmp_path)
    _record(db, numbered, ISRC_A)
    _record(db, template_name, ISRC_B, title="Opening")
    db.commit()

    found = live_identity_paths(
        isrc=ISRC_A,
        directory=album,
        db=db,
        dest_path=template_name,
        extract_isrc=_extract_map({
            str(numbered): ISRC_A,
            str(template_name): ISRC_B,
        }),
    )
    db.close()

    assert [p.resolve() for p in found] == [numbered.resolve()]


def test_live_identity_ignores_other_folder_and_other_isrc(tmp_path):
    album_a = tmp_path / "Artist One" / "First Album"
    album_b = tmp_path / "Artist One" / "Other Edition"
    live_a = _flac(album_a / "01 - Opening.flac")
    live_b = _flac(album_b / "01 - Opening.flac")
    other = _flac(album_a / "02 - Later.flac")

    db = _open_db(tmp_path)
    _record(db, live_a, ISRC_A)
    _record(db, live_b, ISRC_A, album="Other Edition")
    _record(db, other, ISRC_B, title="Later")
    db.commit()

    found = live_identity_paths(isrc=ISRC_A, directory=album_a, db=db)
    db.close()

    assert [p.resolve() for p in found] == [live_a.resolve()]
    assert live_b.exists()
    assert other.exists()


# ---------------------------------------------------------------------------
# has_live_isrc / download-skip / is_local must match library lookup
# ---------------------------------------------------------------------------


def _live_library_row(db, isrc: str):
    from tidal_dl.gui.api.search import _live_library_row as lookup

    return lookup(db, isrc)


def test_has_live_isrc_false_when_tag_scan_sibling_is_not_library_resolvable(
    tmp_path, monkeypatch,
):
    """Unindexed tag-scan hits under a dead path are not playable library files."""
    album = tmp_path / "Composer" / "Catalogue"
    dead = album / "gone.flac"
    numbered = _flac(album / "12 - Catalogue Piece.flac")

    db = _open_db(tmp_path)
    db.register_isrc_path(ISRC_A, dead, commit=True)

    monkeypatch.setattr(
        "tidal_dl.helper.recording_identity.extract_audio_isrc",
        _extract_map({str(numbered): ISRC_A}),
    )

    assert _live_library_row(db, ISRC_A) is None
    assert not db.has_live_isrc(ISRC_A)
    assert db.primary_live_path_for_isrc(ISRC_A) is None
    db.close()


def test_has_live_isrc_true_when_recovered_sibling_is_library_playable(tmp_path):
    """An indexed live sibling is resolvable the same way search lookup is."""
    album = tmp_path / "Composer" / "Catalogue"
    dead = album / "gone.flac"
    numbered = _flac(album / "12 - Catalogue Piece.flac")

    db = _open_db(tmp_path)
    db.register_isrc_path(ISRC_A, dead, commit=True)
    _record(db, numbered, ISRC_A, title="Catalogue Piece")
    db.commit()

    row = _live_library_row(db, ISRC_A)
    assert row is not None
    assert Path(row["path"]).resolve() == numbered.resolve()
    assert db.has_live_isrc(ISRC_A)
    assert Path(db.primary_live_path_for_isrc(ISRC_A)).resolve() == numbered.resolve()
    db.close()


def test_has_live_isrc_false_when_only_dead_path_and_no_sibling(tmp_path):
    album = tmp_path / "Composer" / "Catalogue"
    album.mkdir(parents=True)
    dead = album / "gone.flac"

    db = _open_db(tmp_path)
    db.register_isrc_path(ISRC_A, dead, commit=True)
    assert not db.has_live_isrc(ISRC_A)
    assert db.primary_path_for_isrc(ISRC_A) is not None
    db.close()


def test_skip_duplicate_isrc_does_not_skip_when_tag_scan_sibling_is_unplayable(
    tmp_path, monkeypatch,
):
    """Global ISRC skip must not fire when search cannot resolve a playable path."""
    other = tmp_path / "elsewhere" / "Other Album"
    dead = other / "Missing Path.flac"
    numbered = _flac(other / "07 - Second Theme.flac")

    dl = _download_for_paths(tmp_path, skip_existing=True)
    dl._library_db.register_isrc_path(ISRC_A, dead, commit=True)

    monkeypatch.setattr(
        "tidal_dl.helper.recording_identity.extract_audio_isrc",
        _extract_map({str(numbered): ISRC_A}),
    )

    track = _make_track(505, ISRC_A, name="Second Theme")
    with patch.object(dl, "extension_guess", return_value=".flac"):
        _dest, _ext, skip_file, _skip_dl = dl._prepare_file_paths_and_skip_logic(
            track, "{track_title}", None, 0, 0
        )
    library_row = _live_library_row(dl._library_db, ISRC_A)
    is_local = dl._library_db.has_live_isrc(ISRC_A)
    dl._library_db.close()

    assert library_row is None
    assert is_local is False
    assert skip_file is False


def test_skip_duplicate_isrc_skips_when_indexed_sibling_is_library_playable(tmp_path):
    other = tmp_path / "elsewhere" / "Other Album"
    numbered = _flac(other / "07 - Second Theme.flac")

    dl = _download_for_paths(tmp_path, skip_existing=True)
    _record(dl._library_db, numbered, ISRC_A, title="Second Theme")
    dl._library_db.commit()

    track = _make_track(506, ISRC_A, name="Second Theme")
    with patch.object(dl, "extension_guess", return_value=".flac"):
        _dest, _ext, skip_file, _skip_dl = dl._prepare_file_paths_and_skip_logic(
            track, "{track_title}", None, 0, 0
        )
    live = dl._library_db.primary_live_path_for_isrc(ISRC_A)
    library_row = _live_library_row(dl._library_db, ISRC_A)
    dl._library_db.close()

    assert skip_file is True
    assert Path(live).resolve() == numbered.resolve()
    assert Path(library_row["path"]).resolve() == numbered.resolve()


# ---------------------------------------------------------------------------
# skip_existing + skip_duplicate_isrc must skip template/path mismatch twins
# ---------------------------------------------------------------------------


def test_skip_logic_skips_numbered_cd_rip_when_template_omits_track_num(tmp_path):
    album = tmp_path / "library"
    numbered = _flac(album / "01 - Opening.flac")

    dl = _download_for_paths(tmp_path, skip_existing=True)
    _record(dl._library_db, numbered, ISRC_A)
    dl._library_db.commit()

    track = _make_track(501, ISRC_A, name="Opening")
    with patch.object(dl, "extension_guess", return_value=".flac"):
        dest, _ext, skip_file, _skip_dl = dl._prepare_file_paths_and_skip_logic(
            track, "{track_title}", None, 0, 0
        )
    dl._library_db.close()

    assert skip_file is True
    assert dest.resolve() == numbered.resolve()
    assert not (album / "Opening.flac").exists()


def test_skip_logic_skips_when_db_path_dead_but_tagged_cd_rip_is_live(tmp_path, monkeypatch):
    album = tmp_path / "library"
    dead = album / "Missing Path.flac"
    numbered = _flac(album / "07 - Second Theme.flac")

    dl = _download_for_paths(tmp_path, skip_existing=True)
    dl._library_db.register_isrc_path(ISRC_A, dead, commit=True)

    monkeypatch.setattr(
        "tidal_dl.helper.recording_identity.extract_audio_isrc",
        _extract_map({str(numbered): ISRC_A}),
    )

    track = _make_track(502, ISRC_A, name="Second Theme")
    with patch.object(dl, "extension_guess", return_value=".flac"):
        dest, _ext, skip_file, _skip_dl = dl._prepare_file_paths_and_skip_logic(
            track, "{track_title}", None, 0, 0
        )
    dl._library_db.close()

    assert skip_file is True
    assert dest.resolve() == numbered.resolve()
    assert numbered.exists()
    assert not (album / "Second Theme.flac").exists()


# ---------------------------------------------------------------------------
# Redownload / upgrade must replace identity, not leave LOSSLESS+HI-RES twins
# ---------------------------------------------------------------------------


def test_redownload_replaces_numbered_sibling_instead_of_minting_template_twin(tmp_path):
    album = tmp_path / "library"
    numbered = _flac(album / "01 - Opening.flac", b"lossless")

    dl = _download_for_paths(tmp_path, skip_existing=False)
    _record(dl._library_db, numbered, ISRC_A)
    dl._library_db.commit()

    track = _make_track(503, ISRC_A, name="Opening")

    def fake_download(media, path_media_dst, *_args, **_kwargs):
        written = Path(path_media_dst)
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_bytes(b"hires")
        return True, written

    with (
        patch.object(dl, "_validate_and_prepare_media", return_value=track),
        patch.object(dl, "extension_guess", return_value=".flac"),
        patch.object(dl, "_adjust_quality_settings", return_value=(None, None)),
        patch.object(dl, "_download_and_process_media", side_effect=fake_download),
        patch.object(dl, "_perform_post_processing", return_value=None),
    ):
        outcome, result_path = dl.item(
            file_template="{track_title}",
            media=track,
            duplicate_action_override="redownload",
        )

    audio_files = sorted(p.name for p in album.glob("*.flac"))
    dl._library_db.close()

    assert outcome == DownloadOutcome.DOWNLOADED
    assert Path(result_path).is_file()
    assert Path(result_path).read_bytes() == b"hires"
    assert audio_files == [Path(result_path).name]
    assert "Opening.flac" in audio_files or "01 - Opening.flac" in audio_files
    assert not (len(audio_files) == 2 and "Opening.flac" in audio_files and "01 - Opening.flac" in audio_files)


def test_copy_skips_when_identity_already_lives_in_destination_folder(tmp_path):
    album = tmp_path / "library"
    numbered = _flac(album / "01 - Opening.flac", b"existing")
    source = _flac(tmp_path / "elsewhere" / "Opening.flac", b"source-copy")

    dl = _download_for_paths(tmp_path, skip_existing=True)
    _record(dl._library_db, numbered, ISRC_A)
    dl._library_db.register_isrc_path(ISRC_A, source, commit=True)
    dl._library_db.commit()

    track = _make_track(504, ISRC_A, name="Opening")

    with (
        patch.object(dl, "_validate_and_prepare_media", return_value=track),
        patch.object(dl, "extension_guess", return_value=".flac"),
        patch.object(dl, "_adjust_quality_settings", return_value=(None, None)),
        patch.object(dl, "_download_and_process_media") as download,
        patch.object(dl, "_perform_post_processing", return_value=None),
    ):
        outcome, result_path = dl.item(
            file_template="{track_title}",
            media=track,
            duplicate_action_override="copy",
        )

    audio_files = sorted(p.name for p in album.glob("*.flac"))
    dl._library_db.close()

    download.assert_not_called()
    assert outcome == DownloadOutcome.SKIPPED
    assert Path(result_path).resolve() == numbered.resolve()
    assert audio_files == ["01 - Opening.flac"]
    assert numbered.read_bytes() == b"existing"


# ---------------------------------------------------------------------------
# Upgrade cleanup: stale old_path / album-metadata mismatch / unindexed sibling
# ---------------------------------------------------------------------------


def test_cleanup_removes_unindexed_numbered_sibling_when_old_path_is_stale(tmp_path, monkeypatch):
    album = tmp_path / "Artist Three" / "Third LP"
    stale = album / "Opening.flac"
    numbered = _flac(album / "01 - Opening.flac", b"lossless")
    new_path = _flac(album / "Opening_01.flac", b"hires")

    db = _open_db(tmp_path)
    _record(db, stale, ISRC_A)
    db.commit()

    monkeypatch.setattr(
        "tidal_dl.helper.recording_identity.extract_audio_isrc",
        _extract_map({str(numbered): ISRC_A, str(new_path): ISRC_A}),
    )
    monkeypatch.setattr(
        "tidal_dl.gui.services.upgrade_jobs.trash_file",
        lambda p: os.remove(p) if os.path.exists(p) else None,
    )

    removed = cleanup_replaced_track_files(
        db, old_path=str(stale), new_path=str(new_path), isrc=ISRC_A
    )
    db.commit()
    db.close()

    assert numbered.resolve() in {Path(p).resolve() for p in removed}
    assert not numbered.exists()
    assert new_path.exists()
    assert not stale.exists()


def test_cleanup_same_dir_same_isrc_even_when_album_tags_differ(tmp_path, monkeypatch):
    album = tmp_path / "Artist Four" / "Shared Folder"
    old_path = _flac(album / "01 - Opening.flac", b"old")
    twin = _flac(album / "Opening.flac", b"other-name")
    new_path = _flac(album / "Opening_01.flac", b"hires")

    db = _open_db(tmp_path)
    _record(db, old_path, ISRC_A, album="Shared Folder")
    _record(db, twin, ISRC_A, album="")
    db.commit()

    monkeypatch.setattr(
        "tidal_dl.gui.services.upgrade_jobs.trash_file",
        lambda p: os.remove(p) if os.path.exists(p) else None,
    )

    removed = cleanup_replaced_track_files(db, old_path=str(old_path), new_path=str(new_path))
    db.commit()
    db.close()

    assert {Path(p).name for p in removed} == {"01 - Opening.flac", "Opening.flac"}
    assert not old_path.exists()
    assert not twin.exists()
    assert new_path.exists()


def test_collapse_folder_identity_keeps_other_recordings(tmp_path, monkeypatch):
    album = tmp_path / "Artist One" / "First Album"
    keep = _flac(album / "02 - Later.flac", b"other-track")
    twin = _flac(album / "01 - Opening.flac", b"lossless")
    replacement = _flac(album / "Opening.flac", b"hires")

    db = _open_db(tmp_path)
    _record(db, keep, ISRC_B, title="Later")
    _record(db, twin, ISRC_A)
    db.commit()

    monkeypatch.setattr(
        "tidal_dl.gui.services.upgrade_jobs.trash_file",
        lambda p: os.remove(p) if os.path.exists(p) else None,
    )

    removed = collapse_folder_identity(
        db,
        isrc=ISRC_A,
        keep_path=replacement,
        extra_paths=[twin],
    )
    db.commit()
    db.close()

    assert {Path(p).resolve() for p in removed} == {twin.resolve()}
    assert keep.exists()
    assert replacement.exists()
    assert not twin.exists()


# ---------------------------------------------------------------------------
# adopt_original_name must keep a live ISRC row on the final path
# ---------------------------------------------------------------------------


def _assert_live_metadata(row: dict | None, path: Path, *, title: str = "Opening") -> None:
    assert row is not None
    assert Path(row["path"]).resolve() == path.resolve()
    assert row.get("artist") == "Artist One"
    assert row.get("title") == title
    assert row.get("album") == "First Album"
    assert row.get("quality") == "44100Hz/16bit"
    assert int(row.get("duration") or 0) == 181


def test_adopt_original_name_migrates_isrc_row_to_final_path(tmp_path, monkeypatch):
    """Collapse + adopt must not drop the only live ISRC index row."""
    album = tmp_path / "Artist One" / "First Album"
    original = _flac(album / "01 - Opening.flac", b"lossless")
    keep = _flac(album / "Opening.flac", b"hires")

    db = _open_db(tmp_path)
    _record(db, original, ISRC_A)
    _record(db, keep, ISRC_A)
    db.commit()

    monkeypatch.setattr(
        "tidal_dl.gui.services.upgrade_jobs.trash_file",
        lambda p: os.remove(p) if os.path.exists(p) else None,
    )

    removed = collapse_folder_identity(db, isrc=ISRC_A, keep_path=keep)
    final = adopt_original_name(keep, removed, db, isrc=ISRC_A)
    db.commit()

    live = _live_library_row(db, ISRC_A)
    assert final.resolve() == original.resolve()
    assert original.exists()
    assert original.read_bytes() == b"hires"
    assert not keep.exists()
    assert db.get(str(keep)) is None
    assert db.has_live_isrc(ISRC_A)
    _assert_live_metadata(db.get(str(original)), original)
    assert live is not None
    assert Path(live["path"]).resolve() == original.resolve()
    db.close()


def test_adopt_original_name_reregisters_when_keep_row_is_missing(tmp_path, monkeypatch):
    """No keep-path row: still index the adopted name from the known ISRC."""
    album = tmp_path / "Artist One" / "First Album"
    original = _flac(album / "01 - Opening.flac", b"lossless")
    keep = _flac(album / "Opening.flac", b"hires")

    db = _open_db(tmp_path)
    _record(db, original, ISRC_A)
    db.commit()

    monkeypatch.setattr(
        "tidal_dl.gui.services.upgrade_jobs.trash_file",
        lambda p: os.remove(p) if os.path.exists(p) else None,
    )

    removed = collapse_folder_identity(db, isrc=ISRC_A, keep_path=keep)
    assert db.get(str(original)) is None
    assert db.get(str(keep)) is None

    final = adopt_original_name(keep, removed, db, isrc=ISRC_A)
    db.commit()

    assert final.resolve() == original.resolve()
    assert original.exists()
    assert db.has_live_isrc(ISRC_A)
    assert Path(db.primary_live_path_for_isrc(ISRC_A)).resolve() == original.resolve()
    db.close()


def test_redownload_keeps_live_isrc_after_adopt_without_tag_register(tmp_path):
    """item() replace path must stay local even if tag registration is a no-op."""
    album = tmp_path / "library"
    numbered = _flac(album / "01 - Opening.flac", b"lossless")

    dl = _download_for_paths(tmp_path, skip_existing=False)
    _record(dl._library_db, numbered, ISRC_A)
    dl._library_db.commit()

    track = _make_track(507, ISRC_A, name="Opening")

    def fake_download(media, path_media_dst, *_args, **_kwargs):
        written = Path(path_media_dst)
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_bytes(b"hires")
        return True, written

    with (
        patch.object(dl, "_validate_and_prepare_media", return_value=track),
        patch.object(dl, "extension_guess", return_value=".flac"),
        patch.object(dl, "_adjust_quality_settings", return_value=(None, None)),
        patch.object(dl, "_download_and_process_media", side_effect=fake_download),
        patch.object(dl, "_perform_post_processing", return_value=None),
        patch("tidal_dl.download.items.register_downloaded_track", return_value=None),
    ):
        outcome, result_path = dl.item(
            file_template="{track_title}",
            media=track,
            duplicate_action_override="redownload",
        )

    live = _live_library_row(dl._library_db, ISRC_A)
    is_local = dl._library_db.has_live_isrc(ISRC_A)
    final = Path(result_path)
    dl._library_db.close()

    assert outcome == DownloadOutcome.DOWNLOADED
    assert final.is_file()
    assert final.read_bytes() == b"hires"
    assert is_local is True
    assert live is not None
    assert Path(live["path"]).resolve() == final.resolve()
    assert sorted(p.name for p in album.glob("*.flac")) == [final.name]


def test_item_preserves_migrated_metadata_after_adopt(tmp_path):
    """item() must not stub-upsert the final path after a successful migrate."""
    album = tmp_path / "library"
    numbered = _flac(album / "01 - Opening.flac", b"lossless")

    dl = _download_for_paths(tmp_path, skip_existing=False)
    dl.settings.data.skip_duplicate_isrc = False
    _record(dl._library_db, numbered, ISRC_A)
    dl._library_db.commit()

    track = _make_track(508, ISRC_A, name="Opening")

    def fake_download(media, path_media_dst, *_args, **_kwargs):
        written = Path(path_media_dst)
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_bytes(b"hires")
        _record(dl._library_db, written, ISRC_A)
        dl._library_db.commit()
        return True, written

    with (
        patch.object(dl, "_validate_and_prepare_media", return_value=track),
        patch.object(dl, "extension_guess", return_value=".flac"),
        patch.object(dl, "_adjust_quality_settings", return_value=(None, None)),
        patch.object(dl, "_download_and_process_media", side_effect=fake_download),
        patch.object(dl, "_perform_post_processing", return_value=None),
        patch("tidal_dl.download.items.register_downloaded_track", return_value=None),
    ):
        outcome, result_path = dl.item(
            file_template="{track_title}",
            media=track,
            duplicate_action_override="redownload",
        )

    final = Path(result_path)
    row = dl._library_db.get(str(final))
    live = _live_library_row(dl._library_db, ISRC_A)
    is_local = dl._library_db.has_live_isrc(ISRC_A)
    dl._library_db.close()

    assert outcome == DownloadOutcome.DOWNLOADED
    assert final.is_file()
    assert is_local is True
    _assert_live_metadata(row, final)
    assert live is not None
    assert Path(live["path"]).resolve() == final.resolve()
