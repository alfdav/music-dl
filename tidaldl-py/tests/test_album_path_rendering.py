"""Single-disc album templates must not mint a `_` folder.

Default ``format_album`` is
``{album_artist}/{album_title}/{track_volume_num_optional_CD}/{track_title}``.
On a one-disc album the optional CD token is empty. ``_sanitize_name`` used
to turn that into ``_``, so You Want It Darker landed in
``Leonard Cohen/You Want It Darker/_/``. Pre-existing on master; not #189.
"""

from __future__ import annotations

from tidalapi.album import Album
from tidalapi.artist import Role
from tidalapi.media import Track

from tidal_dl.model.cfg import Settings as ModelSettings
from tidal_dl.helper.path import format_path_media

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
