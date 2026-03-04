"""File path formatting, sanitization, and template expansion."""

import math
import os
import pathlib
import posixpath
import re
import sys
from copy import deepcopy
from urllib.parse import unquote, urlsplit

from pathvalidate import sanitize_filename, sanitize_filepath
from pathvalidate.error import ValidationError
from tidalapi import Album, Mix, Playlist, Track, UserPlaylist, Video
from tidalapi.media import AudioExtensions

from tidal_dl.constants import (
    FILENAME_LENGTH_MAX,
    FILENAME_SANITIZE_PLACEHOLDER,
    FORMAT_TEMPLATE_EXPLICIT,
    UNIQUIFY_THRESHOLD,
    MediaType,
)
from tidal_dl.helper.tidal import name_builder_album_artist, name_builder_artist, name_builder_title


# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------

def path_home() -> str:
    if "XDG_CONFIG_HOME" in os.environ:
        return os.environ["XDG_CONFIG_HOME"]
    elif "HOME" in os.environ:
        return os.environ["HOME"]
    elif "HOMEDRIVE" in os.environ and "HOMEPATH" in os.environ:
        return os.path.join(os.environ["HOMEDRIVE"], os.environ["HOMEPATH"])
    else:
        return os.path.abspath("./")


def path_config_base() -> str:
    path_user_custom: str = os.environ.get("XDG_CONFIG_HOME", "")
    path_config: str = ".config" if not path_user_custom else ""
    return os.path.join(path_home(), path_config, "tidal-dl")


def path_file_log() -> str:
    return os.path.join(path_config_base(), "app.log")


def path_file_token() -> str:
    return os.path.join(path_config_base(), "token.json")


def path_file_settings() -> str:
    return os.path.join(path_config_base(), "settings.json")


# ---------------------------------------------------------------------------
# Template expansion
# ---------------------------------------------------------------------------

def format_path_media(
    fmt_template: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    album_track_num_pad_min: int = 0,
    list_pos: int = 0,
    list_total: int = 0,
    delimiter_artist: str = ", ",
    delimiter_album_artist: str = ", ",
    use_primary_album_artist: bool = False,
) -> str:
    """Expand a format template string using media object attributes.

    Args:
        fmt_template (str): Template with ``{placeholder}`` tokens.
        media: TIDAL media object.
        album_track_num_pad_min (int): Minimum zero-pad width for track numbers.
        list_pos (int): Position in list (for {list_pos}).
        list_total (int): Total items in list.
        delimiter_artist (str): Delimiter for multiple artists.
        delimiter_album_artist (str): Delimiter for multiple album artists.
        use_primary_album_artist (bool): Use first album artist for folder paths.

    Returns:
        str: Expanded and sanitized path string.
    """
    result = fmt_template
    regex = r"\{(.+?)\}"

    for _matchNum, match in enumerate(re.finditer(regex, fmt_template, re.MULTILINE), start=1):
        template_str = match.group()
        result_fmt = format_str_media(
            match.group(1),
            media,
            album_track_num_pad_min,
            list_pos,
            list_total,
            delimiter_artist=delimiter_artist,
            delimiter_album_artist=delimiter_album_artist,
            use_primary_album_artist=use_primary_album_artist,
        )

        if result_fmt != match.group(1):
            value = (
                sanitize_filename(result_fmt)
                if result_fmt != FORMAT_TEMPLATE_EXPLICIT
                else FORMAT_TEMPLATE_EXPLICIT
            )
            result = result.replace(template_str, value)

    return result


def format_str_media(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    album_track_num_pad_min: int = 0,
    list_pos: int = 0,
    list_total: int = 0,
    delimiter_artist: str = ", ",
    delimiter_album_artist: str = ", ",
    use_primary_album_artist: bool = False,
) -> str:
    """Resolve a single template token name to a string value.

    Args:
        name (str): Token name (without braces).
        media: TIDAL media object.
        album_track_num_pad_min (int): Minimum zero-pad width.
        list_pos (int): Position in list.
        list_total (int): Total items in list.
        delimiter_artist (str): Artist name delimiter.
        delimiter_album_artist (str): Album artist name delimiter.
        use_primary_album_artist (bool): Use first album artist.

    Returns:
        str: Resolved value or original name if no match.
    """
    try:
        for formatter in (
            _format_names,
            _format_numbers,
            _format_ids,
            _format_durations,
            _format_dates,
            _format_metadata,
            _format_volumes,
        ):
            result = formatter(
                name,
                media,
                album_track_num_pad_min,
                list_pos,
                list_total,
                delimiter_artist=delimiter_artist,
                delimiter_album_artist=delimiter_album_artist,
                use_primary_album_artist=use_primary_album_artist,
            )

            if result is not None:
                return result
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        print(f"Error formatting path for media attribute '{name}': {e}")

    return name


# ---------------------------------------------------------------------------
# Per-category formatters
# ---------------------------------------------------------------------------

def _format_artist_names(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    delimiter_artist: str = ", ",
    delimiter_album_artist: str = ", ",
    *_args,
    use_primary_album_artist: bool = False,
    **kwargs,
) -> str | None:
    if name == "artist_name" and isinstance(media, Track | Video):
        if use_primary_album_artist and hasattr(media, "album") and media.album and media.album.artists:
            return media.album.artists[0].name
        if hasattr(media, "artists"):
            return name_builder_artist(media, delimiter=delimiter_artist)
        elif hasattr(media, "artist"):
            return media.artist.name
    elif name == "album_artist":
        return name_builder_album_artist(media, first_only=True)
    elif name == "album_artists":
        return name_builder_album_artist(media, delimiter=delimiter_album_artist)
    return None


def _format_titles(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    *_args,
    **kwargs,
) -> str | None:
    if name == "track_title" and isinstance(media, Track | Video):
        return name_builder_title(media)
    elif name == "mix_name" and isinstance(media, Mix):
        return media.title
    elif name == "playlist_name" and isinstance(media, Playlist | UserPlaylist):
        return media.name
    elif name == "album_title":
        if isinstance(media, Album):
            return media.name
        elif isinstance(media, Track):
            return media.album.name
    return None


def _format_names(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    *args,
    delimiter_artist: str = ", ",
    delimiter_album_artist: str = ", ",
    use_primary_album_artist: bool = False,
    **kwargs,
) -> str | None:
    result = _format_artist_names(
        name,
        media,
        delimiter_artist=delimiter_artist,
        delimiter_album_artist=delimiter_album_artist,
        use_primary_album_artist=use_primary_album_artist,
    )

    if result is not None:
        return result

    return _format_titles(name, media)


def _format_numbers(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    album_track_num_pad_min: int,
    list_pos: int,
    list_total: int,
    *_args,
    **kwargs,
) -> str | None:
    if name == "album_track_num" and isinstance(media, Track | Video):
        return calculate_number_padding(
            album_track_num_pad_min,
            media.track_num,
            media.album.num_tracks if hasattr(media, "album") else 1,
        )
    elif name == "album_num_tracks" and isinstance(media, Track | Video):
        return str(media.album.num_tracks if hasattr(media, "album") else 1)
    elif name == "list_pos" and isinstance(media, Track | Video):
        return calculate_number_padding(album_track_num_pad_min, list_pos, list_total)
    return None


def _format_ids(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    *_args,
    **kwargs,
) -> str | None:
    if (
        (name == "track_id" and isinstance(media, Track))
        or (name == "playlist_id" and isinstance(media, Playlist))
        or (name == "video_id" and isinstance(media, Video))
    ):
        return str(media.id)
    elif name == "album_id":
        if isinstance(media, Album):
            return str(media.id)
        elif isinstance(media, Track):
            return str(media.album.id)
    elif name == "isrc" and isinstance(media, Track):
        return media.isrc
    elif name == "album_artist_id" and isinstance(media, Album):
        return str(media.artist.id)
    elif name == "track_artist_id" and isinstance(media, Track):
        return str(media.album.artist.id)
    return None


def _format_durations(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    *_args,
    **kwargs,
) -> str | None:
    if name == "track_duration_seconds" and isinstance(media, Track | Video):
        return str(media.duration)
    elif name == "track_duration_minutes" and isinstance(media, Track | Video):
        m, s = divmod(media.duration, 60)
        return f"{m:01d}:{s:02d}"
    elif name == "album_duration_seconds" and isinstance(media, Album):
        return str(media.duration)
    elif name == "album_duration_minutes" and isinstance(media, Album):
        m, s = divmod(media.duration, 60)
        return f"{m:01d}:{s:02d}"
    return None


def _format_dates(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    *_args,
    **kwargs,
) -> str | None:
    if name == "album_year":
        if isinstance(media, Album):
            return str(media.year)
        elif isinstance(media, Track):
            return str(media.album.year)
    elif name == "album_date":
        if isinstance(media, Album):
            return media.release_date.strftime("%Y-%m-%d") if media.release_date else None
        elif isinstance(media, Track):
            return media.album.release_date.strftime("%Y-%m-%d") if media.album.release_date else None
    return None


def _format_metadata(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    *_args,
    **kwargs,
) -> str | None:
    if name == "video_quality" and isinstance(media, Video):
        return media.video_quality
    elif name == "track_quality" and isinstance(media, Track):
        return ", ".join(tag for tag in media.media_metadata_tags if tag is not None)
    elif (name == "track_explicit" and isinstance(media, Track | Video)) or (
        name == "album_explicit" and isinstance(media, Album)
    ):
        return FORMAT_TEMPLATE_EXPLICIT if media.explicit else ""
    elif name == "media_type":
        if isinstance(media, Album):
            return media.type
        elif isinstance(media, Track):
            return media.album.type
    return None


def _format_volumes(
    name: str,
    media: Track | Album | Playlist | UserPlaylist | Video | Mix,
    *_args,
    **kwargs,
) -> str | None:
    if name == "album_num_volumes" and isinstance(media, Album):
        return str(media.num_volumes)
    elif name == "track_volume_num" and isinstance(media, Track | Video):
        return str(media.volume_num)
    elif name == "track_volume_num_optional" and isinstance(media, Track | Video):
        num_volumes: int = media.album.num_volumes if hasattr(media, "album") else 1
        return "" if num_volumes == 1 else str(media.volume_num)
    elif name == "track_volume_num_optional_CD" and isinstance(media, Track | Video):
        num_volumes: int = media.album.num_volumes if hasattr(media, "album") else 1
        return "" if num_volumes == 1 else f"CD{media.volume_num!s}"
    return None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def calculate_number_padding(padding_minimum: int, item_position: int, items_max: int) -> str:
    """Return zero-padded number string.

    Args:
        padding_minimum (int): Minimum digit width.
        item_position (int): The item's position.
        items_max (int): The total count.

    Returns:
        str: Zero-padded number.
    """
    if items_max > 0:
        count_digits = max(int(math.log10(items_max)) + 1, padding_minimum)
        return str(item_position).zfill(count_digits)
    return str(item_position)


def get_format_template(
    media: Track | Album | Playlist | UserPlaylist | Video | Mix | MediaType,
    settings: object,
) -> str | bool:
    """Return the configured format template for the given media type.

    Args:
        media: A TIDAL media object or MediaType enum value.
        settings: Settings object with format_* attributes.

    Returns:
        str | bool: Template string or False if not recognised.
    """
    if isinstance(media, Track) or media == MediaType.TRACK:
        return settings.data.format_track
    elif isinstance(media, Album) or media in (MediaType.ALBUM, MediaType.ARTIST):
        return settings.data.format_album
    elif isinstance(media, Playlist | UserPlaylist) or media == MediaType.PLAYLIST:
        return settings.data.format_playlist
    elif isinstance(media, Mix) or media == MediaType.MIX:
        return settings.data.format_mix
    elif isinstance(media, Video) or media == MediaType.VIDEO:
        return settings.data.format_video
    return False


def path_file_sanitize(
    path_file: pathlib.Path,
    adapt: bool = False,
    uniquify: bool = False,
) -> pathlib.Path:
    """Sanitize a file path to be OS-safe, optionally making it unique.

    Args:
        path_file (pathlib.Path): Input path.
        adapt (bool): Fall back to home dir on absolute-path errors.
        uniquify (bool): Append a numeric suffix if the file already exists.

    Returns:
        pathlib.Path: Sanitized path.
    """
    sanitized_filename = sanitize_filename(
        path_file.name, replacement_text="_", validate_after_sanitize=True, platform="auto"
    )

    if not sanitized_filename.endswith(path_file.suffix):
        sanitized_filename = (
            sanitized_filename[: -len(path_file.suffix) - len(FILENAME_SANITIZE_PLACEHOLDER)]
            + FILENAME_SANITIZE_PLACEHOLDER
            + path_file.suffix
        )

    sanitized_path = pathlib.Path(
        *[
            (
                sanitize_filename(part, replacement_text="_", validate_after_sanitize=True, platform="auto")
                if part not in path_file.anchor
                else part
            )
            for part in path_file.parent.parts
        ]
    )

    try:
        sanitized_path = sanitize_filepath(
            sanitized_path, replacement_text="_", validate_after_sanitize=True, platform="auto"
        )
    except ValidationError as e:
        if adapt and str(e).startswith("[PV1101]"):
            sanitized_path = pathlib.Path.home()
        else:
            raise

    result = sanitized_path / sanitized_filename

    return path_file_uniquify(result) if uniquify else result


def path_file_uniquify(path_file: pathlib.Path) -> pathlib.Path:
    """Append a numeric suffix to make the path unique.

    Args:
        path_file (pathlib.Path): Input path.

    Returns:
        pathlib.Path: Path with suffix appended if needed.
    """
    unique_suffix = file_unique_suffix(path_file)

    if unique_suffix:
        file_suffix = unique_suffix + path_file.suffix
        # Check length using the full filename (stem + suffix + extension) to decide
        # whether to truncate the stem.  The else-branch must also include the
        # original extension so the output file keeps its type (e.g. .flac).
        path_file = (
            path_file.parent / (str(path_file.stem)[: -len(file_suffix)] + file_suffix)
            if len(str(path_file.parent / (path_file.stem + file_suffix))) > FILENAME_LENGTH_MAX
            else path_file.parent / (path_file.stem + file_suffix)
        )

    return path_file


def file_unique_suffix(path_file: pathlib.Path, separator: str = "_") -> str:
    """Return a unique numeric suffix for the path, or empty string if not needed.

    Args:
        path_file (pathlib.Path): Path to uniquify.
        separator (str): Separator before the numeric suffix.

    Returns:
        str: Suffix like '_01', or ''.
    """
    threshold_zfill = len(str(UNIQUIFY_THRESHOLD))
    count = 0
    path_file_tmp = deepcopy(path_file)
    unique_suffix = ""

    while check_file_exists(path_file_tmp) and count < UNIQUIFY_THRESHOLD:
        count += 1
        unique_suffix = separator + str(count).zfill(threshold_zfill)
        path_file_tmp = path_file.parent / (path_file.stem + unique_suffix + path_file.suffix)

    return unique_suffix


def check_file_exists(path_file: pathlib.Path, extension_ignore: bool = False) -> bool:
    """Check whether a file exists, optionally ignoring the extension.

    Args:
        path_file (pathlib.Path): Path to check.
        extension_ignore (bool): Check all audio extensions when True.

    Returns:
        bool: True if found.
    """
    if extension_ignore:
        stem = pathlib.Path(path_file).stem
        parent = pathlib.Path(path_file).parent
        path_files: list[str] = [str(parent / (stem + ext)) for ext in AudioExtensions]
    else:
        path_files = [str(path_file)]

    return any(os.path.isfile(f) for f in path_files)


def resource_path(relative_path: str) -> str:
    """Return an absolute path to a bundled resource (supports PyInstaller).

    Args:
        relative_path (str): Relative resource path.

    Returns:
        str: Absolute path.
    """
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def url_to_filename(url: str) -> str:
    """Derive a safe filename from a URL.

    Args:
        url (str): Segment URL.

    Returns:
        str: Filename component.

    Raises:
        ValueError: If the URL contains path traversal characters.
    """
    urlpath = urlsplit(url).path
    basename = posixpath.basename(unquote(urlpath))

    if os.path.basename(basename) != basename or unquote(posixpath.basename(urlpath)) != basename:
        raise ValueError

    return basename
