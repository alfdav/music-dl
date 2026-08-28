import dataclasses
import enum
import json
from dataclasses import dataclass
from typing import Any, Self, cast

from tidalapi.media import Quality

from tidal_dl.constants import (
    CoverDimensions,
    DownloadSource,
    InitialKey,
    MetadataTargetUPC,
    QualityVideo,
)

LEGACY_DEFAULT_FORMAT_PLAYLIST = "- Playlists/{playlist_name}/{list_pos}. {artist_name} - {track_title}"
DEFAULT_FORMAT_PLAYLIST = "Playlists/{playlist_name}/{list_pos}. {artist_name} - {track_title}"


def _encode_field(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _coerce_field(field_type: type, value: Any, current: Any) -> Any:
    if isinstance(current, enum.Enum):
        return type(current)(value)
    if isinstance(current, bool) and isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "y")
    if isinstance(current, int) and not isinstance(value, bool):
        return int(value)
    if isinstance(current, float) and not isinstance(value, bool):
        return float(value)
    if field_type is not Any and not isinstance(value, field_type):
        return field_type(value)
    return value


class _JsonDataclassMixin:
    @classmethod
    def from_json(cls, s: str) -> Self:
        raw = json.loads(s)
        if not isinstance(raw, dict):
            raise ValueError("config must be a JSON object")
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Self:
        instance = cls()
        fields = {f.name: f for f in dataclasses.fields(cls)}
        for key, value in raw.items():
            if key not in fields:
                continue
            current = getattr(instance, key)
            try:
                setattr(instance, key, _coerce_field(fields[key].type, value, current))
            except (ValueError, TypeError, KeyError):
                continue
        return instance

    def to_dict(self) -> dict[str, Any]:
        return {f.name: _encode_field(getattr(self, f.name)) for f in dataclasses.fields(self)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


SETTINGS_HELP: dict[str, str] = {
    "skip_existing": "Skip download if file already exists.",
    "lyrics_embed": "On download, embed lyrics in the audio file when Tidal has them. The lyrics panel can Save lyrics to a sidecar for one local file without turning this on.",
    "use_primary_album_artist": "Use only the primary album artist for folder paths instead of track artists.",
    "lyrics_file": "On download, write a sidecar *.lrc when Tidal has lyrics. The lyrics panel Save lyrics control writes that sidecar for the current local file without enabling this for every download.",
    "video_download": "Allow download of videos.",
    "download_delay": "Activate randomized download delay to mimic human behaviour.",
    "download_base_path": "Where to store the downloaded media.",
    "quality_audio": (
        'Desired audio download quality: "LOW" (96kbps), "HIGH" (320kbps), '
        '"LOSSLESS" (16 Bit, 44,1 kHz), "HI_RES_LOSSLESS" (up to 24 Bit, 192 kHz). '
        "Default: HI_RES_LOSSLESS. TIDAL auto-degrades based on your subscription tier."
    ),
    "quality_video": 'Desired video download quality: "360", "480", "720", "1080"',
    "download_source": (
        "Preferred download source: 'oauth' (your personal TIDAL session) or 'hifi_api' (custom Hi-Fi API instances)."
    ),
    "download_source_fallback": (
        "If enabled, automatically fallback to the next source when the preferred source is unavailable."
    ),
    "hifi_api_instances": (
        "Comma-separated custom Hi-Fi API instances. Empty means auto-discover from live uptime trackers (`streaming`, or `api` when streaming is empty)."
    ),
    "download_dolby_atmos": "Download Dolby Atmos audio streams if available.",
    "format_album": "Where to download albums and how to name the items.",
    "format_playlist": "Where to download playlists and how to name the items.",
    "format_mix": "Where to download mixes and how to name the items.",
    "format_track": "Where to download tracks and how to name the items.",
    "format_video": "Where to download videos and how to name the items.",
    "video_convert_mp4": (
        "Videos are downloaded as MPEG Transport Stream (TS) files. "
        "With this option each video will be converted to MP4. FFmpeg must be installed."
    ),
    "path_binary_ffmpeg": (
        "Path to FFmpeg binary file (executable). Only necessary if FFmpeg is not set in $PATH. "
        "Mandatory for Windows: The directory of ffmpeg.exe must be set in %PATH%."
    ),
    "metadata_cover_dimension": (
        "The square dimensions of the cover image embedded into the track. "
        "Possible values: 80, 160, 320, 640, 1280, origin."
    ),
    "metadata_cover_embed": "Embed album cover into file.",
    "mark_explicit": "Mark explicit tracks with '[E]' in track title (only applies to metadata).",
    "cover_album_file": "Save cover to 'cover.jpg', if an album is downloaded.",
    "extract_flac": "Extract FLAC audio tracks from MP4 containers and save them as *.flac (uses FFmpeg).",
    "downloads_simultaneous_per_track_max": "Maximum number of simultaneous chunk downloads per track.",
    "download_delay_sec_min": "Lower boundary for the calculation of the download delay in seconds.",
    "download_delay_sec_max": "Upper boundary for the calculation of the download delay in seconds.",
    "album_track_num_pad_min": (
        "Minimum length of the album track count, will be padded with zeroes (0). To disable padding set this to 1."
    ),
    "downloads_concurrent_max": "Maximum concurrent number of downloads (threads).",
    "symlink_to_track": (
        "If enabled the tracks of albums, playlists and mixes will be downloaded to the track directory "
        "but symlinked accordingly."
    ),
    "playlist_create": "Creates a UTF-8 '.m3u8' playlist file for downloaded albums and mixes.",
    "metadata_replay_gain": "Replay gain information will be written to metadata.",
    "metadata_write_url": "URL of the media file will be written to metadata.",
    "metadata_delimiter_artist": "Metadata tag delimiter for multiple artists. Default: ', '",
    "metadata_delimiter_album_artist": "Metadata tag delimiter for multiple album artists. Default: ', '",
    "filename_delimiter_artist": "Filename delimiter for multiple artists. Default: ', '",
    "filename_delimiter_album_artist": "Filename delimiter for multiple album artists. Default: ', '",
    "metadata_target_upc": (
        "Select the target metadata tag ('UPC', 'BARCODE', 'EAN') where to write the UPC information to. "
        "Default: 'UPC'."
    ),
    "api_rate_limit_batch_size": "Number of albums to process before applying rate limit delay.",
    "api_rate_limit_delay_sec": "Delay in seconds between batches to avoid API rate limiting.",
    "initial_key_format": "Format for Initial Key metadata tag: 'alphanumeric' (default) or 'classic'.",
    "skip_duplicate_isrc": (
        "Skip download if a track with the same ISRC was already downloaded to any path. "
        "Uses library.db ISRC lookups."
    ),
    "duplicate_action": (
        "What to do when a duplicate ISRC is detected during a pre-flight scan. "
        "Options: 'ask' (prompt each run), 'copy' (copy from source), "
        "'redownload' (fetch again from TIDAL), 'skip' (skip silently)."
    ),
    "api_cache_enabled": (
        "Cache TIDAL API responses in-memory during a session to reduce redundant HTTP calls. "
        "Especially effective when downloading albums (avoids re-fetching the same album object per track)."
    ),
    "api_cache_ttl_sec": (
        "Time-to-live in seconds for each cached API response. "
        "Entries older than this value are discarded and re-fetched. Default: 300 (5 minutes)."
    ),
    "scan_paths": (
        "Comma-separated list of directories to scan for existing music files (ISRC seeding). "
        "Managed via 'music-dl scan add/remove/show'. "
        "When only one path is configured, 'music-dl scan' uses it automatically."
    ),
    "upgrade_target_quality": (
        'Preferred cap for upgrade jobs: "HI_RES" or "HI_RES_LOSSLESS". '
        "Jobs request Tidal's available tier when it is below this cap."
    ),
}


@dataclass
class Settings(_JsonDataclassMixin):
    skip_existing: bool = True
    lyrics_embed: bool = False
    lyrics_file: bool = False
    use_primary_album_artist: bool = False
    video_download: bool = True
    download_delay: bool = True
    download_base_path: str = "~/download"
    quality_audio: Quality = cast(Quality, Quality.hi_res_lossless)
    quality_video: QualityVideo = QualityVideo.P1080
    download_source: DownloadSource = DownloadSource.OAUTH
    download_source_fallback: bool = True
    hifi_api_instances: str = ""
    download_dolby_atmos: bool = False
    format_album: str = "{album_artist}/{album_title}/{track_volume_num_optional_CD}/{track_title}"
    format_playlist: str = DEFAULT_FORMAT_PLAYLIST
    format_mix: str = "Mix/{mix_name}/{artist_name} - {track_title}"
    format_track: str = "{album_artist}/{album_title}/{track_title}"
    format_video: str = "Videos/{artist_name}/{track_title}"
    video_convert_mp4: bool = True
    path_binary_ffmpeg: str = ""
    metadata_cover_dimension: CoverDimensions = CoverDimensions.Px1280
    metadata_cover_embed: bool = True
    mark_explicit: bool = False
    cover_album_file: bool = True
    extract_flac: bool = True
    downloads_simultaneous_per_track_max: int = 20
    download_delay_sec_min: float = 3.0
    download_delay_sec_max: float = 5.0
    album_track_num_pad_min: int = 1
    downloads_concurrent_max: int = 3
    symlink_to_track: bool = False
    playlist_create: bool = False
    metadata_replay_gain: bool = False
    metadata_write_url: bool = True
    metadata_delimiter_artist: str = ", "
    metadata_delimiter_album_artist: str = ", "
    filename_delimiter_artist: str = ", "
    filename_delimiter_album_artist: str = ", "
    metadata_target_upc: MetadataTargetUPC = MetadataTargetUPC.UPC
    api_rate_limit_batch_size: int = 20
    api_rate_limit_delay_sec: float = 3.0
    initial_key_format: InitialKey = InitialKey.ALPHANUMERIC
    skip_duplicate_isrc: bool = True
    duplicate_action: str = "copy"
    api_cache_enabled: bool = True
    api_cache_ttl_sec: int = 300
    scan_paths: str = ""
    upgrade_target_quality: str = "HI_RES_LOSSLESS"


@dataclass
class Token(_JsonDataclassMixin):
    token_type: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expiry_time: float = 0.0
    account_quality: str | None = None