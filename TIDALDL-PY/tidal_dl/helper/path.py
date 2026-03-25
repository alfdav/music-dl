"""File path formatting, sanitization, and template expansion."""

import math
import os
import pathlib
import posixpath
import re
import shutil
import sys
from copy import deepcopy
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from pathvalidate import sanitize_filename, sanitize_filepath
from pathvalidate.error import ValidationError
from tidalapi.album import Album
from tidalapi.media import AudioExtensions, Track, Video
from tidalapi.mix import Mix
from tidalapi.playlist import Playlist, UserPlaylist

from tidal_dl.constants import (
    APP_NAME,
    FILENAME_BYTES_MAX,
    FILENAME_LENGTH_MAX,
    FILENAME_SANITIZE_PLACEHOLDER,
    FORMAT_TEMPLATE_EXPLICIT,
    LEGACY_APP_NAME,
    UNIQUIFY_THRESHOLD,
    MediaType,
)
from tidal_dl.helper.tidal import name_builder_album_artist, name_builder_artist, name_builder_title

if TYPE_CHECKING:
    from tidal_dl.config import Settings


PathMedia = Track | Album | Playlist | UserPlaylist | Video | Mix


def _album_from_media(media: Track | Video) -> Album | None:
    album = getattr(media, "album", None)
    return album if isinstance(album, Album) else None


def _name_or_none(value: object) -> str | None:
    name = getattr(value, "name", None)
    return name if isinstance(name, str) and name else None


def _int_or_default(value: int | None, default: int) -> int:
    return value if isinstance(value, int) else default


def _string_id(value: object) -> str | None:
    return str(value) if value is not None else None


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
    base_dir = os.path.join(path_home(), path_config, APP_NAME)
    legacy_dir = os.path.join(path_home(), path_config, LEGACY_APP_NAME)

    if base_dir != legacy_dir and not os.path.exists(base_dir) and os.path.exists(legacy_dir):
        os.makedirs(os.path.dirname(base_dir), exist_ok=True)
        try:
            shutil.move(legacy_dir, base_dir)
        except OSError:
            # Keep the app usable even if the legacy config cannot be moved.
            os.makedirs(base_dir, exist_ok=True)

    return base_dir


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
                sanitize_filename(result_fmt) if result_fmt != FORMAT_TEMPLATE_EXPLICIT else FORMAT_TEMPLATE_EXPLICIT
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
    media: PathMedia,
    delimiter_artist: str = ", ",
    delimiter_album_artist: str = ", ",
    *_args,
    use_primary_album_artist: bool = False,
    **kwargs,
) -> str | None:
    if name == "artist_name" and isinstance(media, Track | Video):
        album = _album_from_media(media)
        if use_primary_album_artist and album and album.artists:
            primary_name = _name_or_none(album.artists[0])
            if primary_name is not None:
                return primary_name
        if hasattr(media, "artists"):
            return name_builder_artist(media, delimiter=delimiter_artist)
        artist_name = _name_or_none(getattr(media, "artist", None))
        if artist_name is not None:
            return artist_name
    elif name == "album_artist":
        if isinstance(media, Track | Album):
            return name_builder_album_artist(media, first_only=True)
    elif name == "album_artists":
        if isinstance(media, Track | Album):
            return name_builder_album_artist(media, delimiter=delimiter_album_artist)
    return None


def _format_titles(
    name: str,
    media: PathMedia,
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
            album = _album_from_media(media)
            return album.name if album is not None else None
    return None


def _format_names(
    name: str,
    media: PathMedia,
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
    media: PathMedia,
    album_track_num_pad_min: int,
    list_pos: int,
    list_total: int,
    *_args,
    **kwargs,
) -> str | None:
    if name == "album_track_num" and isinstance(media, Track | Video):
        album = _album_from_media(media)
        return calculate_number_padding(
            album_track_num_pad_min,
            _int_or_default(media.track_num, 0),
            _int_or_default(album.num_tracks if album else None, 1),
        )
    elif name == "album_num_tracks" and isinstance(media, Track | Video):
        album = _album_from_media(media)
        return str(_int_or_default(album.num_tracks if album else None, 1))
    elif name == "list_pos" and isinstance(media, Track | Video):
        return calculate_number_padding(album_track_num_pad_min, list_pos, list_total)
    return None


def _format_ids(
    name: str,
    media: PathMedia,
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
            album = _album_from_media(media)
            return _string_id(album.id) if album is not None else None
    elif name == "isrc" and isinstance(media, Track):
        return media.isrc
    elif name == "album_artist_id" and isinstance(media, Album):
        artist = getattr(media, "artist", None)
        return _string_id(getattr(artist, "id", None))
    elif name == "track_artist_id" and isinstance(media, Track):
        album = _album_from_media(media)
        artist = getattr(album, "artist", None) if album is not None else None
        return _string_id(getattr(artist, "id", None))
    return None


def _format_durations(
    name: str,
    media: PathMedia,
    *_args,
    **kwargs,
) -> str | None:
    if name == "track_duration_seconds" and isinstance(media, Track | Video):
        return str(media.duration)
    elif name == "track_duration_minutes" and isinstance(media, Track | Video):
        m, s = divmod(_int_or_default(media.duration, 0), 60)
        return f"{m:01d}:{s:02d}"
    elif name == "album_duration_seconds" and isinstance(media, Album):
        return str(media.duration)
    elif name == "album_duration_minutes" and isinstance(media, Album):
        m, s = divmod(_int_or_default(media.duration, 0), 60)
        return f"{m:01d}:{s:02d}"
    return None


def _format_dates(
    name: str,
    media: PathMedia,
    *_args,
    **kwargs,
) -> str | None:
    if name == "album_year":
        if isinstance(media, Album):
            return str(media.year)
        elif isinstance(media, Track):
            album = _album_from_media(media)
            year = getattr(album, "year", None) if album is not None else None
            return str(year) if year is not None else None
    elif name == "album_date":
        if isinstance(media, Album):
            return media.release_date.strftime("%Y-%m-%d") if media.release_date else None
        elif isinstance(media, Track):
            album = _album_from_media(media)
            release_date = getattr(album, "release_date", None) if album is not None else None
            return release_date.strftime("%Y-%m-%d") if release_date is not None else None
    return None


def _format_metadata(
    name: str,
    media: PathMedia,
    *_args,
    **kwargs,
) -> str | None:
    if name == "video_quality" and isinstance(media, Video):
        return media.video_quality
    elif name == "track_quality" and isinstance(media, Track):
        return ", ".join(tag for tag in (media.media_metadata_tags or []) if tag is not None)
    elif (name == "track_explicit" and isinstance(media, Track | Video)) or (
        name == "album_explicit" and isinstance(media, Album)
    ):
        return FORMAT_TEMPLATE_EXPLICIT if media.explicit else ""
    elif name == "media_type":
        if isinstance(media, Album):
            return media.type
        elif isinstance(media, Track):
            album = _album_from_media(media)
            return getattr(album, "type", None) if album is not None else None
    return None


def _format_volumes(
    name: str,
    media: PathMedia,
    *_args,
    **kwargs,
) -> str | None:
    if name == "album_num_volumes" and isinstance(media, Album):
        return str(media.num_volumes)
    elif name == "track_volume_num" and isinstance(media, Track | Video):
        return str(media.volume_num)
    elif name == "track_volume_num_optional" and isinstance(media, Track | Video):
        album = _album_from_media(media)
        num_volumes = _int_or_default(album.num_volumes if album else None, 1)
        return "" if num_volumes == 1 else str(media.volume_num)
    elif name == "track_volume_num_optional_CD" and isinstance(media, Track | Video):
        album = _album_from_media(media)
        num_volumes = _int_or_default(album.num_volumes if album else None, 1)
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
    media: PathMedia | MediaType,
    settings: "Settings",
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
    # Smart truncation: cap filename to FILENAME_BYTES_MAX (POSIX NAME_MAX)
    # using byte length for UTF-8 safety on SMB/NAS. Multi-byte characters
    # (accents, emojis, CJK) can exceed the byte limit even when char count
    # is under 255. Truncation is byte-aware to avoid splitting multi-byte chars.
    raw_name = path_file.name

    def _truncate_to_bytes(s: str, max_bytes: int) -> str:
        """Truncate string to fit within max_bytes of UTF-8 without splitting chars."""
        encoded = s.encode("utf-8")
        if len(encoded) <= max_bytes:
            return s
        truncated = encoded[:max_bytes]
        # Decode with error handling to avoid splitting a multi-byte character
        return truncated.decode("utf-8", errors="ignore")

    if len(raw_name.encode("utf-8")) > FILENAME_BYTES_MAX:
        ext = path_file.suffix
        ext_bytes = len(ext.encode("utf-8"))
        stem = raw_name[: -len(ext)] if ext else raw_name
        parts = stem.rsplit(" - ", 1)
        if len(parts) == 2:
            prefix, title = parts
            sep_bytes = len(" - ".encode("utf-8"))
            title_bytes = len(title.encode("utf-8"))
            max_prefix_bytes = FILENAME_BYTES_MAX - ext_bytes - sep_bytes - title_bytes
            if max_prefix_bytes > 10:
                prefix = _truncate_to_bytes(prefix, max_prefix_bytes - 3).rstrip(", ") + "..."
                raw_name = prefix + " - " + title + ext
            else:
                stem = _truncate_to_bytes(stem, FILENAME_BYTES_MAX - ext_bytes)
                raw_name = stem + ext
        else:
            stem = _truncate_to_bytes(stem, FILENAME_BYTES_MAX - ext_bytes)
            raw_name = stem + ext

    sanitized_filename = sanitize_filename(
        raw_name, replacement_text="_", validate_after_sanitize=True, platform="auto"
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
        path_files: list[pathlib.Path] = [parent / (stem + ext) for ext in AudioExtensions]
    else:
        path_files = [path_file]

    return any(win_long_path(p).is_file() for p in path_files)


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


def win_long_path(path: pathlib.Path) -> pathlib.Path:
    """On Windows, return the ``\\\\?\\`` extended-length form to bypass MAX_PATH.

    This allows file operations on paths longer than 260 characters.
    On non-Windows platforms (or paths already prefixed), returns the path unchanged.
    """
    if sys.platform != "win32":
        return path
    s = str(path)
    if s.startswith("\\\\?\\"):
        return path
    # Use absolute() instead of resolve() — resolve() can fail on mapped
    # network drives (e.g. M:) by trying to convert to UNC paths.
    # Replace forward slashes for the \\?\ prefix which requires backslashes.
    abs_path = str(path.absolute()).replace("/", "\\")
    return pathlib.Path("\\\\?\\" + abs_path)
