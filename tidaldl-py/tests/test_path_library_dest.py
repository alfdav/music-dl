"""Library destination resolution: prefer existing album folders, mint Artist/Album only."""

from pathlib import Path

from tidal_dl.helper.path import resolve_library_relative


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
