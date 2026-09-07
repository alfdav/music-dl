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


def _record(db: LibraryDB, path: Path, isrc: str, *, album: str = "First Album", title: str = "Opening") -> None:
    db.record(
        str(path),
        status="tagged",
        isrc=isrc,
        artist="Artist One",
        title=title,
        album=album,
        quality="44100Hz/16bit",
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
# has_live_isrc / primary_path recover dead DB paths via same-folder identity
# ---------------------------------------------------------------------------


def test_has_live_isrc_true_when_db_path_dead_and_numbered_sibling_live(tmp_path, monkeypatch):
    album = tmp_path / "Composer" / "Catalogue"
    dead = album / "gone.flac"
    numbered = _flac(album / "12 - Catalogue Piece.flac")

    db = _open_db(tmp_path)
    db.register_isrc_path(ISRC_A, dead, commit=True)

    monkeypatch.setattr(
        "tidal_dl.helper.recording_identity.extract_audio_isrc",
        _extract_map({str(numbered): ISRC_A}),
    )

    assert db.has_live_isrc(ISRC_A)
    assert Path(db.primary_path_for_isrc(ISRC_A)).resolve() == numbered.resolve()
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
