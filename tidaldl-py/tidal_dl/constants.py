"""Shared constants and enums for music-dl."""

import base64
from enum import StrEnum

from tidalapi.media import Quality

APP_NAME: str = "music-dl"
LEGACY_APP_NAME: str = "tidal-dl"

CTX_TIDAL: str = "tidal"
REQUESTS_TIMEOUT_SEC: int = 45
# Boot / source-restore network cap. Tauri polls health for 30s; a 45s Hi-Fi,
# gist, or quality-probe hang used to pin the spinner. 2s is enough for a live
# host and fails fast on a dead network. Download transfers keep REQUESTS_TIMEOUT_SEC.
SOURCE_RESOLVE_TIMEOUT_SEC: float = 2.0
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

# Tier rank for upgrade comparison — maps quality strings to numeric tiers.
# Used by the upgrade system to determine if a Tidal quality is higher than local.
# Dolby Atmos excluded: it's lossy spatial audio, not a fidelity upgrade.
TIER_RANK: dict[str, int] = {
    "LOW": 0,
    "HIGH": 1,
    "LOSSLESS": 2,
    "HI_RES": 3,
    "HI_RES_LOSSLESS": 4,
    # Local file quality strings
    "MP3": 1,
    "AAC": 1,
    "OGG": 1,
    "M4A": 1,
    "FLAC": 2,
    "WAV": 2,
}

# Reverse map: Tidal quality string -> tidalapi.media.Quality enum.
# Used by upgrade system to convert cached probe results to dl.item() args.
# NOTE: tidalapi has no Quality.hi_res member. HI_RES maps to hi_res_lossless
# because Tidal serves the best available quality for the account tier at download time.
QUALITY_STRING_TO_ENUM: dict[str, Quality] = {
    "LOW": Quality.low_96k,
    "HIGH": Quality.low_320k,
    "LOSSLESS": Quality.high_lossless,
    "HI_RES": Quality.hi_res_lossless,
    "HI_RES_LOSSLESS": Quality.hi_res_lossless,
}

# Well-known track ID used to probe the account's maximum quality.
# Fleetwood Mac – "Dreams" is widely available and tagged HI_RES_LOSSLESS.
QUALITY_PROBE_TRACK_ID: str = "59727857"

# First-install Tidal Web OAuth often cannot fetch HI_RES_LOSSLESS even when the
# account plan includes it. Tell the user once, then download LOSSLESS instead.
SESSION_HIRES_FALLBACK_NOTICE: str = (
    "This login can't get Hi-Res streams, so downloading Lossless instead. "
    "A different Tidal login client (PKCE / Android-type) can unlock Hi-Res; "
    "the Tidal Web client used at first install cannot. "
    "Do not reset your token unless you choose to sign in again."
)
_HIRES_SESSION_MAX: frozenset[str] = frozenset({"HI_RES", "HI_RES_LOSSLESS"})


def session_can_deliver_hires(session_max: Quality | str | None) -> bool | None:
    """True/False when the login's observed max is known; None before a probe."""
    if session_max is None or session_max == "":
        return None
    name = quality_name(session_max).upper()
    if name in _HIRES_SESSION_MAX:
        return True
    if name in QUALITY_RANK or name in TIER_RANK:
        return False
    return None


def remember_session_hires_fallback(tidal: object) -> bool:
    """Record the per-session Hi-Res fallback notice. True on the first call."""
    if getattr(tidal, "_hires_fallback_notice_emitted", False):
        return False
    tidal.session_quality_notice = SESSION_HIRES_FALLBACK_NOTICE
    tidal._hires_fallback_notice_emitted = True
    return True


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

# Maps tidalapi.Quality enum → Hi-Fi API quality string parameter.
HIFI_QUALITY_MAP: dict[str, str] = {
    quality_name(Quality.hi_res_lossless): "HI_RES_LOSSLESS",
    "HI_RES": "HI_RES",
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
