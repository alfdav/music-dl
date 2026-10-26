import dataclasses
import enum
import json
from dataclasses import dataclass, field
from typing import Any, Self, cast, get_args, get_origin

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
    origin = get_origin(field_type)
    if origin is list:
        if not isinstance(value, list):
            raise TypeError("expected a list")
        args = get_args(field_type)
        item_type = args[0] if args else Any
        if item_type is str:
            return [item for item in value if isinstance(item, str)]
        if item_type is Any:
            return list(value)
        return [item for item in value if isinstance(item, item_type)]
    if field_type is not Any and not isinstance(value, field_type):
        return field_type(value)
    return value


class _JsonDataclassMixin:
    @classmethod
    def from_json(cls, s: str) -> Self:
        raw = json.loads(s)
        if not isinstance(raw, dict):
            raise ValueError("config must be a JSON object")  # noqa: TRY004
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
    "download_delay": (
        "Pace Tidal API/auth stream-info calls to avoid rate limits. "
        "Media byte streams use full available bandwidth with no per-track sleep."
    ),
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
    "edition_advice_enabled": (
        "DJAI module: TypeSafe/Jev edition chips on Clean Up. "
        "Toggled on the DJAI Edition advice card, not in Settings. "
        "AI can make mistakes; verify before Clean Up. "
        "Never auto-deletes keep-both, unclear, or unscored extras."
    ),
    "edition_scorer_path": (
        "Optional path to the typesafe-music-edition sidecar. "
        "When empty, music-dl looks on PATH and well-known install locations."
    ),
    "playlist_sync_enabled": "Run playlist sync. Off by default; nothing starts it automatically.",
    "playlist_sync_dry_run": "Plan playlist sync and write the report, but queue nothing and append nothing.",
    "playlist_sync_poll_minutes": "Minutes between playlist sync cycles when a scheduler is configured.",
    "playlist_sync_max_per_cycle": "Maximum downloads started in one playlist sync cycle.",
    "playlist_sync_max_per_day": "Maximum playlist sync downloads per local day, across every playlist.",
    "playlist_sync_gap_sec_min": "Minimum seconds to wait between playlist sync downloads.",
    "playlist_sync_gap_sec_max": "Maximum seconds to wait between playlist sync downloads.",
    "playlist_sync_allowlist": (
        "Playlist names included in sync. Empty means every playlist the user created. "
        "Matching is case-insensitive. Set this only in local settings."
    ),
    "playlist_sync_plex_url": "Plex server URL for playlist sync. Empty leaves the Plex step off.",
    "playlist_sync_plex_section_id": "Plex music library section key. Empty leaves the Plex step off.",
    "playlist_sync_plex_local_prefix": (
        "Path prefix on this machine. Rewritten to the server prefix before a Plex lookup."
    ),
    "playlist_sync_plex_server_prefix": "Path prefix Plex sees for files under the local prefix.",
    "playlist_sync_plex_scan_timeout_sec": (
        "Seconds to wait for a scanned file to appear in Plex before the next cycle. Default: 600."
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
    quality_audio: Quality = cast(Quality, Quality.hi_res_lossless)  # noqa: RUF009
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
    edition_advice_enabled: bool = False
    edition_scorer_path: str = ""
    playlist_sync_enabled: bool = False
    playlist_sync_dry_run: bool = True
    playlist_sync_poll_minutes: int = 15
    playlist_sync_max_per_cycle: int = 5
    playlist_sync_max_per_day: int = 30
    playlist_sync_gap_sec_min: float = 30
    playlist_sync_gap_sec_max: float = 60
    playlist_sync_allowlist: list[str] = field(default_factory=list)
    playlist_sync_plex_url: str = ""
    playlist_sync_plex_section_id: str = ""
    playlist_sync_plex_local_prefix: str = ""
    playlist_sync_plex_server_prefix: str = ""
    playlist_sync_plex_scan_timeout_sec: int = 600


@dataclass
class Token(_JsonDataclassMixin):
    token_type: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expiry_time: float = 0.0
    account_quality: str | None = None