"""Single-disc album templates must not mint a `_` folder.

Default ``format_album`` is
``{album_artist}/{album_title}/{track_volume_num_optional_CD}/{track_title}``.
On a one-disc album the optional CD token is empty. ``_sanitize_name`` used
to turn that into ``_``, so You Want It Darker landed in
``Leonard Cohen/You Want It Darker/_/``. Pre-existing on master; not #189.
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

from tidalapi.album import Album
from tidalapi.artist import Role
from tidalapi.media import Track

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.path import format_path_media
from tidal_dl.model.cfg import Settings as ModelSettings

_DEFAULT_ALBUM = ModelSettings().format_album
_QUALITY_ALBUM = "{album_artist}/{album_title}/{track_quality}/{track_title}"


class _Artist:
    def __init__(self, name: str):
        self.name = name
        self.roles = [Role.main]


class _Album(Album):
    def __init__(self, name: str, *, num_volumes: int = 1):
        self.name = name
        self.artists = [_Artist("Leonard Cohen")]
        self.num_volumes = num_volumes


class _Track(Track):
    def __init__(
        self,
        title: str,
        album: _Album,
        *,
        volume_num: int = 1,
        tags: list[str] | None = None,
    ):
        self.full_name = title
        self.name = title
        self.album = album
        self.volume_num = volume_num
        self.media_metadata_tags = tags


def test_single_disc_album_omits_empty_cd_segment():
    track = _Track(
        "If I Didn't Have Your Love",
        _Album("You Want It Darker", num_volumes=1),
        tags=["LOSSLESS"],
    )

    path = format_path_media(_DEFAULT_ALBUM, track)

    assert path == "Leonard Cohen/You Want It Darker/If I Didn't Have Your Love"
    assert "/_/" not in f"/{path}/"
    assert path.split("/")[2] != "_"


def test_multi_disc_album_keeps_cd_segment():
    track = _Track(
        "If I Didn't Have Your Love",
        _Album("You Want It Darker", num_volumes=2),
        volume_num=2,
        tags=["LOSSLESS"],
    )

    path = format_path_media(_DEFAULT_ALBUM, track)

    assert path == "Leonard Cohen/You Want It Darker/CD2/If I Didn't Have Your Love"


def test_capped_quality_label_is_lossless_not_underscore():
    """Session-capped delivery labels the quality segment LOSSLESS, not `_`."""
    track = _Track(
        "If I Didn't Have Your Love",
        _Album("You Want It Darker", num_volumes=1),
        tags=["LOSSLESS"],
    )

    path = format_path_media(_QUALITY_ALBUM, track)

    assert path == "Leonard Cohen/You Want It Darker/LOSSLESS/If I Didn't Have Your Love"
    assert "/_/" not in f"/{path}/"


def test_empty_quality_label_collapses_instead_of_underscore():
    track = _Track(
        "If I Didn't Have Your Love",
        _Album("You Want It Darker", num_volumes=1),
        tags=[],
    )

    path = format_path_media(_QUALITY_ALBUM, track)

    assert path == "Leonard Cohen/You Want It Darker/If I Didn't Have Your Love"
    assert "/_/" not in f"/{path}/"


def _download_for_legacy_placeholder(tmp_path: Path):
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
            path_base=str(tmp_path),
            fn_logger=MagicMock(),
            skip_existing=True,
            event_abort=abort,
            event_run=run,
        )
    dl._library_db = LibraryDB(tmp_path / "library.db")
    dl._library_db.open()
    # Path check only: a v1.7 `_` library must skip even when ISRC is off / unindexed.
    dl.settings.data.skip_duplicate_isrc = False
    dl.settings.data.symlink_to_track = False
    return dl


def test_skip_existing_reuses_v17_placeholder_folder(tmp_path: Path):
    """v1.7 wrote Artist/Album/_/Track.flac. Collapse must skip, not remint."""
    legacy = (
        tmp_path
        / "Leonard Cohen"
        / "You Want It Darker"
        / "_"
        / "If I Didn't Have Your Love.flac"
    )
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"existing")

    track = _Track(
        "If I Didn't Have Your Love",
        _Album("You Want It Darker", num_volumes=1),
        tags=["LOSSLESS"],
    )
    dl = _download_for_legacy_placeholder(tmp_path)

    with patch.object(dl, "extension_guess", return_value=".flac"):
        dest, ext, skip_file, skip_download = dl._prepare_file_paths_and_skip_logic(
            track,
            _DEFAULT_ALBUM,
            None,
            0,
            0,
        )
    dl._library_db.close()

    collapsed = tmp_path / "Leonard Cohen" / "You Want It Darker" / "If I Didn't Have Your Love.flac"
    assert skip_file is True
    assert skip_download is False
    assert ext == ".flac"
    assert dest.resolve() == legacy.resolve()
    assert legacy.is_file()
    assert not collapsed.exists()


def test_preflight_skips_legacy_placeholder_instead_of_promising_copy(tmp_path: Path):
    """scanned `_/` files are already at dest — pre-count must say skip, not copy."""
    legacy = (
        tmp_path
        / "Leonard Cohen"
        / "You Want It Darker"
        / "_"
        / "If I Didn't Have Your Love.flac"
    )
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"existing")

    track = _Track(
        "If I Didn't Have Your Love",
        _Album("You Want It Darker", num_volumes=1),
        tags=["LOSSLESS"],
    )
    track.id = 66024828
    track.isrc = "CAB679603552"
    dl = _download_for_legacy_placeholder(tmp_path)
    dl.settings.data.skip_duplicate_isrc = True
    dl.settings.data.format_album = _DEFAULT_ALBUM
    dl._library_db.record(str(legacy), status="tagged", isrc=track.isrc)
    dl._library_db.register_isrc_path(track.isrc, legacy, commit=True)

    with patch.object(dl, "extension_guess", return_value=".flac"):
        resolved = dl._preflight_isrc_scan(
            [track],
            ensure_complete=True,
            file_template=_DEFAULT_ALBUM,
        )

    info_messages = [str(call.args[0]) for call in dl.fn_logger.info.call_args_list]
    dl._library_db.close()

    assert resolved == {"66024828": "skip"}
    assert any("will be skipped" in message for message in info_messages)
    assert not any("will be copied" in message for message in info_messages)


_PLAYLIST_DEST = "Playlists/Favorites/{track_title}"
_MIX_DEST = "Mix/Radio/{track_title}"


def _register_isrc_file(dl, track, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(b"existing")
    dl._library_db.record(str(path), status="tagged", isrc=track.isrc)
    dl._library_db.register_isrc_path(track.isrc, path, commit=True)


def _cohen_track() -> _Track:
    track = _Track(
        "If I Didn't Have Your Love",
        _Album("You Want It Darker", num_volumes=1),
        tags=["LOSSLESS"],
    )
    track.id = 66024828
    track.isrc = "CAB679603552"
    return track


def test_preflight_copies_when_isrc_lives_in_other_album(tmp_path: Path):
    """Same ISRC in another album folder must still land in the playlist dest."""
    album_file = (
        tmp_path
        / "Leonard Cohen"
        / "Songs of Leonard Cohen"
        / "If I Didn't Have Your Love.flac"
    )
    track = _cohen_track()
    dl = _download_for_legacy_placeholder(tmp_path)
    dl.settings.data.skip_duplicate_isrc = True
    _register_isrc_file(dl, track, album_file)

    with patch.object(dl, "extension_guess", return_value=".flac"):
        resolved = dl._preflight_isrc_scan(
            [track],
            ensure_complete=True,
            file_template=_PLAYLIST_DEST,
        )

    info_messages = [str(call.args[0]) for call in dl.fn_logger.info.call_args_list]
    dl._library_db.close()

    assert resolved == {"66024828": "copy"}
    assert any("will be copied" in message for message in info_messages)
    assert not any("will be skipped" in message for message in info_messages)
    playlist_dest = tmp_path / "Playlists" / "Favorites" / "If I Didn't Have Your Love.flac"
    assert not playlist_dest.exists()
    assert album_file.is_file()


def test_preflight_copies_when_isrc_lives_in_other_playlist(tmp_path: Path):
    """Same ISRC in a playlist folder must still land in the mix dest."""
    playlist_file = (
        tmp_path / "Playlists" / "Favorites" / "If I Didn't Have Your Love.flac"
    )
    track = _cohen_track()
    dl = _download_for_legacy_placeholder(tmp_path)
    dl.settings.data.skip_duplicate_isrc = True
    _register_isrc_file(dl, track, playlist_file)

    with patch.object(dl, "extension_guess", return_value=".flac"):
        resolved = dl._preflight_isrc_scan(
            [track],
            ensure_complete=True,
            file_template=_MIX_DEST,
        )

    info_messages = [str(call.args[0]) for call in dl.fn_logger.info.call_args_list]
    dl._library_db.close()

    assert resolved == {"66024828": "copy"}
    assert any("will be copied" in message for message in info_messages)
    assert not any("will be skipped" in message for message in info_messages)
    mix_dest = tmp_path / "Mix" / "Radio" / "If I Didn't Have Your Love.flac"
    assert not mix_dest.exists()
    assert playlist_file.is_file()


def test_preflight_skips_normal_album_rerun(tmp_path: Path):
    """A collapsed Artist/Album/Track file is already at dest — album re-run skips."""
    dest = (
        tmp_path
        / "Leonard Cohen"
        / "You Want It Darker"
        / "If I Didn't Have Your Love.flac"
    )
    track = _cohen_track()
    dl = _download_for_legacy_placeholder(tmp_path)
    dl.settings.data.skip_duplicate_isrc = True
    dl.settings.data.format_album = _DEFAULT_ALBUM
    _register_isrc_file(dl, track, dest)

    with patch.object(dl, "extension_guess", return_value=".flac"):
        resolved = dl._preflight_isrc_scan(
            [track],
            ensure_complete=True,
            file_template=_DEFAULT_ALBUM,
        )

    info_messages = [str(call.args[0]) for call in dl.fn_logger.info.call_args_list]
    dl._library_db.close()

    assert resolved == {"66024828": "skip"}
    assert any("will be skipped" in message for message in info_messages)
    assert not any("will be copied" in message for message in info_messages)
    assert dest.is_file()


_PLAYLIST_LIST_POS = "Playlists/Favorites/{list_pos}. {artist_name} - {track_title}"


def test_preflight_skips_playlist_file_at_real_list_pos(tmp_path: Path):
    """Default playlist dest uses {list_pos}. Position 0 is not the numbered dest."""
    track = _cohen_track()
    track.artists = [_Artist("Leonard Cohen")]
    track.artist = _Artist("Leonard Cohen")
    real_dest = tmp_path / "Playlists" / "Favorites" / "1. Leonard Cohen - If I Didn't Have Your Love.flac"
    wrong_zero = tmp_path / "Playlists" / "Favorites" / "0. Leonard Cohen - If I Didn't Have Your Love.flac"
    dl = _download_for_legacy_placeholder(tmp_path)
    dl.settings.data.skip_duplicate_isrc = True
    _register_isrc_file(dl, track, real_dest)

    with patch.object(dl, "extension_guess", return_value=".flac"):
        resolved = dl._preflight_isrc_scan(
            [track],
            ensure_complete=True,
            file_template=_PLAYLIST_LIST_POS,
        )

    info_messages = [str(call.args[0]) for call in dl.fn_logger.info.call_args_list]
    dl._library_db.close()

    assert resolved == {"66024828": "skip"}
    assert any("will be skipped" in message for message in info_messages)
    assert not any("will be copied" in message for message in info_messages)
    assert real_dest.is_file()
    assert not wrong_zero.exists()


def test_preflight_copies_when_only_zero_list_pos_file_exists(tmp_path: Path):
    """A leftover 0. dest from the old preflight must not count as this job's dest."""
    track = _cohen_track()
    track.artists = [_Artist("Leonard Cohen")]
    track.artist = _Artist("Leonard Cohen")
    wrong_zero = tmp_path / "Playlists" / "Favorites" / "0. Leonard Cohen - If I Didn't Have Your Love.flac"
    dl = _download_for_legacy_placeholder(tmp_path)
    dl.settings.data.skip_duplicate_isrc = True
    _register_isrc_file(dl, track, wrong_zero)

    with patch.object(dl, "extension_guess", return_value=".flac"):
        resolved = dl._preflight_isrc_scan(
            [track],
            ensure_complete=True,
            file_template=_PLAYLIST_LIST_POS,
        )

    info_messages = [str(call.args[0]) for call in dl.fn_logger.info.call_args_list]
    dl._library_db.close()

    assert resolved == {"66024828": "copy"}
    assert any("will be copied" in message for message in info_messages)
    assert not any("will be skipped" in message for message in info_messages)
