"""Library destination resolution: prefer existing album folders, mint Artist/Album only."""

from pathlib import Path

from tidal_dl.helper.path import resolve_library_relative, resolve_live_library_path


def test_resolves_into_existing_artist_prefixed_album_folder(tmp_path: Path) -> None:
    artist = tmp_path / "Carlos Vives"
    (artist / "Carlos Vives - Clasicos de la Provincia").mkdir(parents=True)

    result = resolve_library_relative(
        tmp_path,
        "Carlos Vives/Clásicos de la Provincia/La gota fría",
    )

    assert result == "Carlos Vives/Carlos Vives - Clasicos de la Provincia/La gota fría"


def test_root_codec_folder_without_artist_prefix_is_not_reused(tmp_path: Path) -> None:
    (tmp_path / "Greatest Hits [FLAC]").mkdir()

    result = resolve_library_relative(
        tmp_path,
        "Billy Idol/Greatest Hits/White Wedding",
    )

    assert result == "Billy Idol/Greatest Hits/White Wedding"


def test_resolves_into_existing_root_artist_album_flac_folder(tmp_path: Path) -> None:
    (tmp_path / "Billy Idol - Greatest Hits [FLAC]").mkdir()

    result = resolve_library_relative(
        tmp_path,
        "Billy Idol/Greatest Hits/White Wedding",
    )

    assert result == "Billy Idol - Greatest Hits [FLAC]/White Wedding"


def test_remastered_edition_does_not_collapse_into_original(tmp_path: Path) -> None:
    artist = tmp_path / "Carlos Vives"
    (artist / "Clasicos de la Provincia").mkdir(parents=True)
    (artist / "Carlos Vives - Clasicos de la Provincia").mkdir()

    result = resolve_library_relative(
        tmp_path,
        "Carlos Vives/Clásicos de la Provincia 30 Años (Remastered & Expanded)"
        "/La gota fría (Remastered 30 años)",
    )

    assert result == (
        "Carlos Vives/Clásicos de la Provincia 30 Años (Remastered & Expanded)"
        "/La gota fría (Remastered 30 años)"
    )


def test_flattened_codec_folder_is_not_minted(tmp_path: Path) -> None:
    result = resolve_library_relative(
        tmp_path,
        "Billy Idol - Greatest Hits [FLAC]/White Wedding",
    )

    assert result == "Billy Idol/Greatest Hits/White Wedding"
    assert "[FLAC]" not in result
    assert not result.startswith("Billy Idol - ")


def test_artist_prefixed_album_folder_is_not_minted(tmp_path: Path) -> None:
    result = resolve_library_relative(
        tmp_path,
        "Carlos Vives/Carlos Vives - Clasicos de la Provincia/La gota fría",
    )

    assert result == "Carlos Vives/Clasicos de la Provincia/La gota fría"


def test_accent_folded_sibling_is_reused(tmp_path: Path) -> None:
    (tmp_path / "Carlos Vives" / "Clasicos de la Provincia").mkdir(parents=True)

    result = resolve_library_relative(
        tmp_path,
        "Carlos Vives/Clásicos de la Provincia/La gota fría",
    )

    assert result == "Carlos Vives/Clasicos de la Provincia/La gota fría"


def test_playlist_layout_is_left_alone(tmp_path: Path) -> None:
    relative = "Playlists/Road Trip/01. Billy Idol - White Wedding"

    assert resolve_library_relative(tmp_path, relative) == relative


def test_cd_subdir_is_kept_when_reusing_legacy_album(tmp_path: Path) -> None:
    (tmp_path / "Billy Idol - Greatest Hits [FLAC]").mkdir()

    result = resolve_library_relative(
        tmp_path,
        "Billy Idol/Greatest Hits/CD1/White Wedding",
    )

    assert result == "Billy Idol - Greatest Hits [FLAC]/CD1/White Wedding"


def test_flat_album_with_disc_reuses_existing_root_folder(tmp_path: Path) -> None:
    (tmp_path / "Billy Idol - Greatest Hits [FLAC]").mkdir()

    result = resolve_library_relative(
        tmp_path,
        "Billy Idol - Greatest Hits [FLAC]/CD1/White Wedding",
    )

    assert result == "Billy Idol - Greatest Hits [FLAC]/CD1/White Wedding"


def test_flat_album_with_disc_is_not_minted(tmp_path: Path) -> None:
    result = resolve_library_relative(
        tmp_path,
        "Billy Idol - Greatest Hits [FLAC]/CD1/White Wedding",
    )

    assert result == "Billy Idol/Greatest Hits/CD1/White Wedding"
    assert "[FLAC]" not in result
    assert not result.startswith("Billy Idol - ")


def test_prefers_bare_sibling_over_prefixed_when_both_exist(tmp_path: Path) -> None:
    artist = tmp_path / "Carlos Vives"
    (artist / "Clasicos de la Provincia").mkdir(parents=True)
    (artist / "Carlos Vives - Clasicos de la Provincia").mkdir()

    result = resolve_library_relative(
        tmp_path,
        "Carlos Vives/Clásicos de la Provincia/La gota fría",
    )

    assert result == "Carlos Vives/Clasicos de la Provincia/La gota fría"


def test_mix_layout_is_left_alone(tmp_path: Path) -> None:
    relative = "Mix/My Mix/Billy Idol - White Wedding"

    assert resolve_library_relative(tmp_path, relative) == relative


def test_reuses_v17_placeholder_folder_when_track_file_exists(tmp_path: Path) -> None:
    """v1.7 `_` dest is present; do not remint Artist/Album/Track."""
    legacy = tmp_path / "Artist" / "Album" / "_" / "Track.flac"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"existing")

    result = resolve_library_relative(tmp_path, "Artist/Album/Track")

    assert result == "Artist/Album/_/Track"


def test_empty_placeholder_dir_is_not_reused_for_new_track(tmp_path: Path) -> None:
    """`_` leftover without this file must not keep minting `_` for new tracks."""
    (tmp_path / "Artist" / "Album" / "_").mkdir(parents=True)
    sibling = tmp_path / "Artist" / "Album" / "_" / "Other.flac"
    sibling.write_bytes(b"other")

    result = resolve_library_relative(tmp_path, "Artist/Album/Track")

    assert result == "Artist/Album/Track"


def test_live_lookup_finds_v17_placeholder_from_collapsed_dest(tmp_path: Path) -> None:
    """scanned / history dest Artist/Album/Track.flac still resolves to `_`."""
    legacy = tmp_path / "Artist" / "Album" / "_" / "Track.flac"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"existing")
    collapsed = tmp_path / "Artist" / "Album" / "Track.flac"

    assert resolve_live_library_path(str(collapsed)) == str(legacy)
    assert resolve_live_library_path(str(legacy)) == str(legacy)
