"""TIDAL API helpers — media instantiation, name builders, pagination."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from tidalapi import Album, Mix, Playlist, Session, Track, UserPlaylist, Video
from tidalapi.artist import Artist, Role
from tidalapi.media import MediaMetadataTags, Quality
from tidalapi.user import LoggedInUser

from tidal_dl.constants import FAVORITES, MediaType
from tidal_dl.helper.exceptions import MediaUnknown

if TYPE_CHECKING:
    from tidal_dl.helper.cache import TTLCache
    from tidal_dl.hifi_api import HiFiApiClient


def name_builder_artist(media: Track | Video | Album, delimiter: str = ", ") -> str:
    """Return a delimited string of artist names for the given media.

    Args:
        media (Track | Video | Album): Media object.
        delimiter (str): Delimiter between names. Defaults to ", ".

    Returns:
        str: Delimited artist names.
    """
    return delimiter.join(artist.name for artist in media.artists)


def name_builder_album_artist(
    media: Track | Album,
    first_only: bool = False,
    delimiter: str = ", ",
) -> str:
    """Return a delimited string of main album artist names.

    Args:
        media (Track | Album): Media object.
        first_only (bool): Only include the first main artist. Defaults to False.
        delimiter (str): Delimiter between names. Defaults to ", ".

    Returns:
        str: Delimited album artist names.
    """
    artists_tmp: list[str] = []
    artists: list[Artist] = media.album.artists if isinstance(media, Track) else media.artists

    for artist in artists:
        if Role.main in artist.roles:
            artists_tmp.append(artist.name)

            if first_only:
                break

    return delimiter.join(artists_tmp)


def name_builder_title(media: Track | Video | Mix | Playlist | Album) -> str:
    """Return the display title for a media object.

    Args:
        media: Any TIDAL media object.

    Returns:
        str: Display title.
    """
    return media.title if isinstance(media, Mix) else media.full_name if hasattr(media, "full_name") else media.name


def name_builder_item(media: Track | Video) -> str:
    """Return 'Artist(s) - Title' string for a track or video.

    Args:
        media (Track | Video): Media object.

    Returns:
        str: Formatted name string.
    """
    return f"{name_builder_artist(media)} - {name_builder_title(media)}"


def get_tidal_media_id(url_or_id_media: str) -> str:
    """Extract the media ID from a TIDAL URL or return the value as-is.

    Args:
        url_or_id_media (str): Full TIDAL URL or bare ID.

    Returns:
        str: Media ID.
    """
    id_dirty = url_or_id_media.rsplit("/", 1)[-1]
    return id_dirty.rsplit("?", 1)[0]


def get_tidal_media_type(url_media: str) -> MediaType | bool:
    """Determine the MediaType from a TIDAL URL.

    Args:
        url_media (str): Full TIDAL URL.

    Returns:
        MediaType | bool: Detected media type or False if unrecognised.
    """
    result: MediaType | bool = False
    url_split = url_media.split("/")[-2]

    if len(url_split) > 1:
        media_name = url_media.split("/")[-2]

        _map = {
            "track": MediaType.TRACK,
            "video": MediaType.VIDEO,
            "album": MediaType.ALBUM,
            "playlist": MediaType.PLAYLIST,
            "mix": MediaType.MIX,
            "artist": MediaType.ARTIST,
        }
        result = _map.get(media_name, False)

    return result


def url_ending_clean(url: str) -> str:
    """Strip trailing '/u' or '?u' from a TIDAL URL.

    Args:
        url (str): URL to clean.

    Returns:
        str: Cleaned URL.
    """
    return url[:-2] if url.endswith("/u") or url.endswith("?u") else url


def _parse_release_date(raw_date: str | None):
    if not raw_date:
        return None
    try:
        # API may return ISO datetime; keep only YYYY-MM-DD.
        return datetime.strptime(str(raw_date)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _cover_url(cover_id: str | None, size: int) -> str:
    if not cover_id:
        return ""
    return f"https://resources.tidal.com/images/{cover_id.replace('-', '/')}/{size}x{size}.jpg"

def _mark_hifi_resolved(media_obj):
    try:
        media_obj._resolved_via_hifi = True
    except Exception:
        pass
    return media_obj


def _hifi_artist_obj(raw_artist: dict | None):
    data = raw_artist or {}
    artist = MagicMock(spec=Artist)
    artist.id = data.get("id")
    artist.name = data.get("name", "")
    artist.roles = [Role.main] if str(data.get("type", "")).upper() == "MAIN" else []
    return artist


def _hifi_album_obj(raw_album: dict | None, tracks: list | None = None):
    data = raw_album or {}
    album = MagicMock(spec=Album)

    title = data.get("title") or data.get("name") or ""
    release_dt = _parse_release_date(data.get("releaseDate"))
    artists = [_hifi_artist_obj(a) for a in (data.get("artists") or ([] if not data.get("artist") else [data["artist"]]))]

    album.id = data.get("id")
    album.title = title
    album.name = title
    album.duration = data.get("duration", 0) or 0
    album.allow_streaming = bool(data.get("allowStreaming", True))
    album.explicit = bool(data.get("explicit", False))
    album.type = data.get("type", "ALBUM")
    album.num_tracks = data.get("numberOfTracks", 0) or (len(tracks) if tracks else 1)
    album.num_volumes = data.get("numberOfVolumes", 1) or 1
    album.upc = data.get("upc", "")
    album.release_date = release_dt
    album.available_release_date = release_dt
    album.year = release_dt.year if release_dt else 0
    album.copyright = data.get("copyright", "")
    album.artists = artists
    album.artist = artists[0] if artists else _hifi_artist_obj(data.get("artist"))
    album.media_metadata_tags = (data.get("mediaMetadata") or {}).get("tags", []) or []

    cover_id = data.get("cover")

    def _image(size: int = 1280):
        return _cover_url(cover_id, int(size))

    album.image = _image

    tracks = tracks or []

    def _paged_items(limit: int = 100, offset: int = 0):
        return tracks[offset : offset + limit]

    album.items = _paged_items
    album.tracks = _paged_items
    return _mark_hifi_resolved(album)


def _hifi_track_obj(raw_track: dict, parent_album: object | None = None):
    data = raw_track or {}
    track = MagicMock(spec=Track)

    title = data.get("title") or data.get("name") or ""
    artists = [_hifi_artist_obj(a) for a in (data.get("artists") or ([] if not data.get("artist") else [data["artist"]]))]

    track.id = data.get("id")
    track.title = title
    track.name = title
    track.full_name = title
    track.duration = data.get("duration", 0) or 0
    track.allow_streaming = bool(data.get("allowStreaming", True))
    track.stream_ready = bool(data.get("streamReady", True))
    track.track_num = data.get("trackNumber", 1) or 1
    track.volume_num = data.get("volumeNumber", 1) or 1
    track.version = data.get("version")
    track.popularity = data.get("popularity", 0) or 0
    track.copyright = data.get("copyright", "")
    track.bpm = data.get("bpm")
    track.key = data.get("key")
    track.key_scale = data.get("keyScale")
    track.share_url = data.get("url", "")
    track.isrc = data.get("isrc", "")
    track.explicit = bool(data.get("explicit", False))
    track.audio_modes = data.get("audioModes", []) or []
    track.media_metadata_tags = (data.get("mediaMetadata") or {}).get("tags", []) or []
    track.artist = artists[0] if artists else _hifi_artist_obj(data.get("artist"))
    track.artists = artists or ([track.artist] if track.artist else [])

    if parent_album is not None:
        track.album = parent_album
    else:
        track.album = _hifi_album_obj(data.get("album") or {})

    # When the album payload lacks artist data (common for /info/ responses),
    # inherit the track's artists so album_artist path templates resolve.
    if not track.album.artists and artists:
        track.album.artists = list(artists)
        track.album.artist = artists[0]

    class _LyricsEmpty:
        text = ""
        subtitles = ""

    track.lyrics = lambda: _LyricsEmpty()
    return _mark_hifi_resolved(track)


def _hifi_items_unwrap(items: list | None) -> list[dict]:
    result: list[dict] = []
    for item in items or []:
        if isinstance(item, dict) and isinstance(item.get("item"), dict):
            result.append(item["item"])
        elif isinstance(item, dict):
            result.append(item)
    return result


def _instantiate_media_hifi(
    hifi_client: "HiFiApiClient",
    media_type: MediaType,
    id_media: str,
) -> Track | Video | Album | Playlist | Mix | Artist:
    if media_type == MediaType.TRACK:
        payload = hifi_client.track_info(int(id_media))
        data = payload.get("data", payload)
        return _hifi_track_obj(data)

    if media_type == MediaType.ALBUM:
        payload = hifi_client.album(int(id_media))
        album_data = payload.get("data", payload)
        # Paginate: fetch all album items across pages.
        raw_tracks = _hifi_items_unwrap((album_data or {}).get("items"))
        total = (album_data or {}).get("numberOfTracks", 0) or 0
        offset = len(raw_tracks)
        while offset < total:
            page = hifi_client.album(int(id_media), limit=100, offset=offset)
            page_data = page.get("data", page)
            page_items = _hifi_items_unwrap((page_data or {}).get("items"))
            if not page_items:
                break
            raw_tracks.extend(page_items)
            offset += len(page_items)
        album_obj = _hifi_album_obj(album_data)
        tracks = [_hifi_track_obj(t, parent_album=album_obj) for t in raw_tracks]
        album_obj.items = lambda limit=100, offset=0: tracks[offset : offset + limit]
        album_obj.tracks = album_obj.items
        album_obj.num_tracks = len(tracks) or album_obj.num_tracks
        return album_obj

    if media_type == MediaType.PLAYLIST:
        payload = hifi_client.playlist(str(id_media))
        playlist_data = payload.get("playlist", payload)
        # Paginate: fetch all playlist items across pages.
        raw_tracks = _hifi_items_unwrap(payload.get("items"))
        total = (playlist_data or {}).get("numberOfTracks", 0) or 0
        total += (playlist_data or {}).get("numberOfVideos", 0) or 0
        offset = len(raw_tracks)
        while offset < total:
            page = hifi_client.playlist(str(id_media), limit=100, offset=offset)
            page_items = _hifi_items_unwrap(page.get("items"))
            if not page_items:
                break
            raw_tracks.extend(page_items)
            offset += len(page_items)
        tracks = [_hifi_track_obj(t) for t in raw_tracks]
        playlist = MagicMock(spec=Playlist)
        playlist.id = playlist_data.get("uuid", str(id_media))
        playlist.name = playlist_data.get("title", "")
        playlist.title = playlist.name
        playlist.duration = playlist_data.get("duration", 0) or 0
        playlist.num_tracks = playlist_data.get("numberOfTracks", len(tracks))
        playlist.num_videos = playlist_data.get("numberOfVideos", 0) or 0
        playlist.share_url = playlist_data.get("url", "")
        playlist.items = lambda limit=100, offset=0: tracks[offset : offset + limit]
        playlist.tracks = playlist.items
        return _mark_hifi_resolved(playlist)

    if media_type == MediaType.MIX:
        payload = hifi_client.mix(str(id_media))
        mix_data = payload.get("mix", payload)
        raw_tracks = _hifi_items_unwrap(payload.get("items"))
        tracks = [_hifi_track_obj(t) for t in raw_tracks]
        mix = MagicMock(spec=Mix)
        mix.id = mix_data.get("id", str(id_media))
        mix.title = mix_data.get("title", "")
        mix.name = mix.title
        mix.items = lambda: tracks
        return _mark_hifi_resolved(mix)

    raise MediaUnknown


def instantiate_media(
    session: Session,
    media_type: MediaType,
    id_media: str,
    cache: TTLCache | None = None,
    hifi_client: "HiFiApiClient" | None = None,
    prefer_hifi: bool = False,
    oauth_fallback: bool = True,
) -> Track | Video | Album | Playlist | Mix | Artist:
    """Create a TIDAL media object for the given type and ID.

    When *cache* is provided the result is looked up in the cache first.  On a
    cache miss the object is fetched from the TIDAL API and stored for reuse
    within the current session (avoids redundant HTTP calls when the same
    media ID is requested multiple times, e.g. all tracks of an album).

    Args:
        session (Session): Active TIDAL session.
        media_type (MediaType): Type of the media.
        id_media (str): Media ID.
        cache (TTLCache | None): Optional response cache. Defaults to None.
        hifi_client (HiFiApiClient | None): Hi-Fi metadata client.
        prefer_hifi (bool): Prefer Hi-Fi API for metadata resolution.
        oauth_fallback (bool): Fallback to OAuth metadata resolution when Hi-Fi fails.

    Returns:
        A TIDAL media object.

    Raises:
        MediaUnknown: If the media type is not recognised.
    """
    cache_key = f"{media_type}:{id_media}:hifi={int(bool(prefer_hifi and hifi_client is not None))}"

    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    def _instantiate_media_oauth() -> Track | Video | Album | Playlist | Mix | Artist:
        if media_type == MediaType.TRACK:
            return session.track(id_media, with_album=True)
        if media_type == MediaType.VIDEO:
            return session.video(id_media)
        if media_type == MediaType.ALBUM:
            return session.album(id_media)
        if media_type == MediaType.PLAYLIST:
            return session.playlist(id_media)
        if media_type == MediaType.MIX:
            return session.mix(id_media)
        if media_type == MediaType.ARTIST:
            return session.artist(id_media)
        raise MediaUnknown

    hifi_supported_types = {MediaType.TRACK, MediaType.ALBUM, MediaType.PLAYLIST, MediaType.MIX}
    if prefer_hifi and hifi_client is not None and media_type in hifi_supported_types:
        try:
            result = _instantiate_media_hifi(hifi_client, media_type, id_media)
        except Exception:
            if not oauth_fallback:
                raise
            result = _instantiate_media_oauth()
    else:
        result = _instantiate_media_oauth()

    if cache is not None:
        cache.set(cache_key, result)

    return result


def items_results_all(
    media_list: Mix | Playlist | Album | Artist,
    videos_include: bool = True,
) -> list[Track | Video | Album]:
    """Fetch all items in a collection, handling pagination.

    Args:
        media_list: A TIDAL collection object.
        videos_include (bool): Include videos when fetching playlists/albums.

    Returns:
        list: All media items.
    """
    result: list[Track | Video | Album] = []

    if isinstance(media_list, Mix):
        result = media_list.items()
    else:
        func_get_items_media: list[Callable] = []

        if isinstance(media_list, Playlist | Album):
            func_get_items_media.append(media_list.items if videos_include else media_list.tracks)
        else:
            func_get_items_media.append(media_list.get_albums)
            func_get_items_media.append(media_list.get_ep_singles)

        result = paginate_results(func_get_items_media)

    return result


def paginate_results(
    func_get_items_media: list[Callable],
) -> list[Track | Video | Album | Playlist | UserPlaylist]:
    """Paginate through all results from one or more list-fetching callables.

    Args:
        func_get_items_media (list[Callable]): Callables that accept limit/offset kwargs.

    Returns:
        list: All collected items.
    """
    result: list = []

    for func_media in func_get_items_media:
        limit = 50 if getattr(func_media, "__func__", None) == LoggedInUser.playlist_and_favorite_playlists else 100
        offset = 0
        done = False

        while not done:
            tmp_result = func_media(limit=limit, offset=offset)

            if tmp_result:
                result += tmp_result
                offset += limit
            else:
                done = True

    return result


def all_artist_album_ids(media_artist: Artist) -> list[int | None]:
    """Return all album IDs for an artist (albums + EPs/singles).

    Args:
        media_artist (Artist): TIDAL Artist object.

    Returns:
        list[int | None]: List of album IDs.
    """
    albums: list[Album] = paginate_results([media_artist.get_albums, media_artist.get_ep_singles])
    return [album.id for album in albums]


def quality_audio_highest(media: Track | Album) -> Quality:
    """Return the highest available audio quality for a track or album.

    Args:
        media (Track | Album): TIDAL media object.

    Returns:
        Quality: Highest available quality enum value.
    """
    if MediaMetadataTags.hi_res_lossless in media.media_metadata_tags:
        return Quality.hi_res_lossless
    elif MediaMetadataTags.lossless in media.media_metadata_tags:
        return Quality.high_lossless
    else:
        return media.audio_quality


def favorite_function_factory(tidal: object, favorite_item: str) -> Callable:
    """Return the tidalapi callable for fetching a favorites collection.

    Args:
        tidal: Tidal config object with a .session attribute.
        favorite_item (str): Key from FAVORITES constant dict.

    Returns:
        Callable: The function to call to fetch the favorites list.
    """
    function_name: str = FAVORITES[favorite_item]["function_name"]
    return getattr(tidal.session.user.favorites, function_name)
