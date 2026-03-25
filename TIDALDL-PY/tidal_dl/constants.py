"""Shared constants and enums for music-dl."""

import base64
from enum import StrEnum

from tidalapi.media import Quality

APP_NAME: str = "music-dl"
LEGACY_APP_NAME: str = "tidal-dl"

CTX_TIDAL: str = "tidal"
REQUESTS_TIMEOUT_SEC: int = 45
EXTENSION_LYRICS: str = ".lrc"
UNIQUIFY_THRESHOLD: int = 99
FILENAME_SANITIZE_PLACEHOLDER: str = "_"
COVER_NAME: str = "cover.jpg"
BLOCK_SIZE: int = 4096
BLOCKS: int = 1024
CHUNK_SIZE: int = BLOCK_SIZE * BLOCKS
PLAYLIST_EXTENSION: str = ".m3u8"
PLAYLIST_PREFIX: str = ""
FILENAME_LENGTH_MAX: int = 255
FILENAME_BYTES_MAX: int = 255  # POSIX NAME_MAX — byte limit for UTF-8 filenames
FORMAT_TEMPLATE_EXPLICIT: str = " (Explicit)"
METADATA_EXPLICIT: str = " 🅴"

# Dolby Atmos API credentials (obfuscated)
_ATMOS_ID_B64 = "N203QX" + "AwSkM5aj" + "FjT00zbg=="
_ATMOS_SECRET_B64 = "dlJBZEEx" + "MDh0bHZrSnB" + "Uc0daUzhyR1" + "o3eFRsYkow" + "cWFaMks5c2F" + "FenNnWT0="

ATMOS_CLIENT_ID = base64.b64decode(_ATMOS_ID_B64).decode("utf-8")
ATMOS_CLIENT_SECRET = base64.b64decode(_ATMOS_SECRET_B64).decode("utf-8")
ATMOS_REQUEST_QUALITY = Quality.low_320k


def quality_name(value: Quality | str) -> str:
    """Return a stable string key for quality values from runtime or stubs."""
    return value.value if isinstance(value, Quality) else str(value)


# Ordered from lowest to highest fidelity for comparison.
QUALITY_RANK: dict[str, int] = {
    quality_name(Quality.low_96k): 0,
    quality_name(Quality.low_320k): 1,
    quality_name(Quality.high_lossless): 2,
    quality_name(Quality.hi_res_lossless): 3,
}

# Well-known track ID used to probe the account's maximum quality.
# Fleetwood Mac – "Dreams" is widely available and tagged HI_RES_LOSSLESS.
QUALITY_PROBE_TRACK_ID: str = "59727857"


class QualityVideo(StrEnum):
    P360 = "360"
    P480 = "480"
    P720 = "720"
    P1080 = "1080"


class DownloadSource(StrEnum):
    HIFI_API = "hifi_api"
    OAUTH = "oauth"


HIFI_UPTIME_TRACKER_URLS: list[str] = [
    "https://tidal-uptime.jiffy-puffs-1j.workers.dev/",
    "https://tidal-uptime.props-76styles.workers.dev/",
]

HIFI_API_FALLBACK_INSTANCES: list[str] = [
    "https://api.monochrome.tf",
    "https://arran.monochrome.tf",
    "https://triton.squid.wtf",
]

# Maps tidalapi.Quality enum → Hi-Fi API quality string parameter.
HIFI_QUALITY_MAP: dict[str, str] = {
    quality_name(Quality.hi_res_lossless): "HI_RES_LOSSLESS",
    quality_name(Quality.high_lossless): "LOSSLESS",
    quality_name(Quality.low_320k): "HIGH",
    quality_name(Quality.low_96k): "LOW",
}


class MediaType(StrEnum):
    TRACK = "track"
    VIDEO = "video"
    PLAYLIST = "playlist"
    ALBUM = "album"
    MIX = "mix"
    ARTIST = "artist"


class CoverDimensions(StrEnum):
    Px80 = "80"
    Px160 = "160"
    Px320 = "320"
    Px640 = "640"
    Px1280 = "1280"
    PxORIGIN = "origin"


class AudioExtensionsValid(StrEnum):
    FLAC = ".flac"
    M4A = ".m4a"
    MP4 = ".mp4"
    MP3 = ".mp3"
    OGG = ".ogg"
    ALAC = ".alac"


class MetadataTargetUPC(StrEnum):
    UPC = "UPC"
    BARCODE = "BARCODE"
    EAN = "EAN"


METADATA_LOOKUP_UPC: dict[str, dict[str, str]] = {
    "UPC": {"MP3": "UPC", "MP4": "UPC", "FLAC": "UPC"},
    "BARCODE": {"MP3": "BARCODE", "MP4": "BARCODE", "FLAC": "BARCODE"},
    "EAN": {"MP3": "EAN", "MP4": "EAN", "FLAC": "EAN"},
}


class InitialKey(StrEnum):
    ALPHANUMERIC = "alphanumeric"
    CLASSIC = "classic"


FAVORITES: dict[str, dict[str, str]] = {
    "fav_videos": {"name": "Videos", "function_name": "videos"},
    "fav_tracks": {"name": "Tracks", "function_name": "tracks_paginated"},
    "fav_mixes": {"name": "Mixes & Radio", "function_name": "mixes"},
    "fav_artists": {"name": "Artists", "function_name": "artists_paginated"},
    "fav_albums": {"name": "Albums", "function_name": "albums_paginated"},
}
