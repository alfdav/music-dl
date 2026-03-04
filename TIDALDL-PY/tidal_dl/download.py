"""
download.py

Implements the Download class and helpers for downloading media from TIDAL,
including segment merging, file moving, metadata writing, and playlist creation.

Classes:
    RequestsClient: Simple HTTP client for downloading text content.
    Download: Main class for managing downloads, segment merging, file operations, and metadata.
"""

import os
import pathlib
import random
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent import futures
from threading import Event
from threading import Lock
from uuid import uuid4

import m3u8
import requests
from ffmpeg import FFmpeg
from pathvalidate import sanitize_filename
from requests.adapters import HTTPAdapter, Retry
from requests.exceptions import HTTPError
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, TaskID
from rich.table import Table
from tidalapi import Album, Mix, Playlist, Session, Track, UserPlaylist, Video
from tidalapi.exceptions import TooManyRequests
from tidalapi.media import (
    AudioExtensions,
    AudioMode,
    Codec,
    Quality,
    Stream,
    StreamManifest,
    VideoExtensions,
)

from tidal_dl.config import Settings, Tidal
from tidal_dl.helper.cache import TTLCache
from tidal_dl.constants import (
    CHUNK_SIZE,
    COVER_NAME,
    EXTENSION_LYRICS,
    METADATA_EXPLICIT,
    METADATA_LOOKUP_UPC,
    PLAYLIST_EXTENSION,
    PLAYLIST_PREFIX,
    QUALITY_RANK,
    REQUESTS_TIMEOUT_SEC,
    AudioExtensionsValid,
    CoverDimensions,
    DownloadSource,
    HIFI_QUALITY_MAP,
    MediaType,
    MetadataTargetUPC,
    QualityVideo,
)
from tidal_dl.helper.camelot import format_initial_key
from tidal_dl.helper.decryption import decrypt_file, decrypt_security_token
from tidal_dl.helper.exceptions import MediaMissing
from tidal_dl.helper.checkpoint import DownloadCheckpoint, STATUS_DOWNLOADED, STATUS_FAILED, STATUS_PENDING
from tidal_dl.helper.isrc_index import IsrcIndex
from tidal_dl.helper.path import (
    check_file_exists,
    format_path_media,
    path_config_base,
    path_file_sanitize,
    url_to_filename,
)
from tidal_dl.helper.tidal import (
    instantiate_media,
    items_results_all,
    name_builder_album_artist,
    name_builder_artist,
    name_builder_item,
    name_builder_title,
)
from tidal_dl.metadata import Metadata
from tidal_dl.model.downloader import (
    DownloadOutcome,
    DownloadSegmentResult,
    DownloadSummary,
    HiFiStreamManifest,
    TrackStreamInfo,
)


# TODO: Set appropriate client string and use it for video download.
# https://github.com/globocom/m3u8#using-different-http-clients
class RequestsClient:
    """HTTP client for downloading text content from a URI."""

    def download(
        self, uri: str, timeout: int = REQUESTS_TIMEOUT_SEC, headers: dict | None = None, verify_ssl: bool = True
    ) -> tuple[str, str]:
        """Download the content of a URI as text.

        Args:
            uri (str): The URI to download.
            timeout (int, optional): Timeout in seconds. Defaults to REQUESTS_TIMEOUT_SEC.
            headers (dict | None, optional): HTTP headers. Defaults to None.
            verify_ssl (bool, optional): Whether to verify SSL. Defaults to True.

        Returns:
            tuple[str, str]: Tuple of (text content, final URL).
        """
        if not headers:
            headers = {}

        o = requests.get(uri, timeout=timeout, headers=headers)
        o.raise_for_status()

        return o.text, o.url


# TODO: Use pathlib.Path everywhere
class Download:
    """Main class for managing downloads, segment merging, file operations, and metadata for TIDAL media."""

    settings: Settings
    tidal: "Tidal"
    session: Session
    skip_existing: bool = False
    fn_logger: Callable
    progress: Progress
    progress_overall: Progress
    event_abort: Event
    event_run: Event
    _api_cache: TTLCache | None

    def __init__(
        self,
        tidal_obj: Tidal,  # Required for Atmos session context manager
        path_base: str,
        fn_logger: Callable,
        skip_existing: bool = False,
        progress: Progress | None = None,
        progress_overall: Progress | None = None,
        event_abort: Event | None = None,
        event_run: Event | None = None,
    ) -> None:
        """Initialize the Download object and its dependencies.

        Args:
            tidal_obj (Tidal): TIDAL configuration object. Required for:
                - session: Main TIDAL API session
                - switch_to_atmos_session(): Dolby Atmos credential switching
                - restore_normal_session(): Restore original session credentials
            path_base (str): Base path for downloads.
            fn_logger (Callable): Logger function or object.
            skip_existing (bool, optional): Whether to skip existing files. Defaults to False.
            progress (Progress | None, optional): Rich progress bar. Defaults to None.
            progress_overall (Progress | None, optional): Overall progress bar. Defaults to None.
            event_abort (Event | None, optional): Abort event. Defaults to None.
            event_run (Event | None, optional): Run event. Defaults to None.
        """
        self.settings = Settings()
        self.tidal = tidal_obj
        self.session = tidal_obj.session
        self.skip_existing = skip_existing
        self.fn_logger = fn_logger
        self.progress = progress
        self.progress_overall = progress_overall
        self.path_base = path_base
        self.event_abort = event_abort
        self.event_run = event_run
        self._checkpoint: DownloadCheckpoint | None = None
        self._rate_limit_hits: int = 0
        self._successful_since_limit: int = 0
        self._rate_limit_lock: Lock = Lock()
        self._adaptive_delay_sec_min = self.settings.data.download_delay_sec_min
        self._adaptive_delay_sec_max = self.settings.data.download_delay_sec_max

        # Use the session-level TTLCache if caching is enabled in settings.
        if self.settings.data.api_cache_enabled and hasattr(tidal_obj, "api_cache"):
            self._api_cache = tidal_obj.api_cache
        else:
            self._api_cache = None

        # Persistent ISRC index for cross-context duplicate detection
        _index_path = pathlib.Path(path_config_base()) / "isrc_index.json"
        self._isrc_index: IsrcIndex = IsrcIndex(_index_path)
        self._isrc_index.load()
        self._cleanup_stale_temp_dirs()

        if not self.settings.data.path_binary_ffmpeg and (
            self.settings.data.video_convert_mp4 or self.settings.data.extract_flac
        ):
            discovered = shutil.which("ffmpeg")

            if discovered:
                self.settings.data.path_binary_ffmpeg = discovered
                self.fn_logger.info(f"FFmpeg auto-discovered at: {discovered}")
            else:
                self.settings.data.video_convert_mp4 = False
                self.settings.data.extract_flac = False

                self.fn_logger.error(
                    "FFmpeg was not found. Videos can be downloaded but will not be converted to MP4. "
                    "FLAC cannot be extracted from MP4 containers. "
                    "Install FFmpeg and ensure it is in your PATH, or set `path_binary_ffmpeg` in the config."
                )

    def _cleanup_stale_temp_dirs(self) -> None:
        """Delete UUID-named temp dirs older than 1 hour, left from interrupted downloads."""
        import uuid

        tmp_dir = pathlib.Path(tempfile.gettempdir())
        cutoff = time.time() - 3600
        cleaned = 0

        for entry in tmp_dir.iterdir():
            if not entry.is_dir():
                continue
            try:
                uuid.UUID(entry.name)
            except ValueError:
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    cleaned += 1
            except OSError:
                pass

        if cleaned:
            self.fn_logger.info(f"Cleaned up {cleaned} stale temp dir(s) from previous sessions.")

    def _on_rate_limit_hit(self) -> None:
        """Double the adaptive download delay on a 429 response, capped at 30 s."""
        max_delay = 30.0
        with self._rate_limit_lock:
            self._rate_limit_hits += 1
            self._successful_since_limit = 0
            self._adaptive_delay_sec_min = min(self._adaptive_delay_sec_min * 2, max_delay)
            self._adaptive_delay_sec_max = min(self._adaptive_delay_sec_max * 2, max_delay)
        self.fn_logger.warning(
            f"Rate limit hit #{self._rate_limit_hits}. "
            f"Adaptive delay now [{self._adaptive_delay_sec_min:.1f}s–{self._adaptive_delay_sec_max:.1f}s]."
        )

    def _on_successful_track(self) -> None:
        """Track successful downloads; halve adaptive delay after 50 consecutive successes."""
        with self._rate_limit_lock:
            self._successful_since_limit += 1
            if self._rate_limit_hits > 0 and self._successful_since_limit >= 50:
                self._successful_since_limit = 0
                baseline_min = self.settings.data.download_delay_sec_min
                baseline_max = self.settings.data.download_delay_sec_max
                self._adaptive_delay_sec_min = max(self._adaptive_delay_sec_min / 2, baseline_min)
                self._adaptive_delay_sec_max = max(self._adaptive_delay_sec_max / 2, baseline_max)
                self.fn_logger.debug(
                    f"50 successful tracks. Delay halved to "
                    f"[{self._adaptive_delay_sec_min:.1f}s–{self._adaptive_delay_sec_max:.1f}s]."
                )

    def _get_track_stream_info_hifi(self, media: Track) -> TrackStreamInfo:
        """Fetch stream info via the Hi-Fi API client and wrap it in a HiFiStreamManifest.

        Args:
            media (Track): The track to fetch.

        Returns:
            TrackStreamInfo: Stream info with a HiFiStreamManifest as the manifest.

        Raises:
            Exception: Propagates any exception from the Hi-Fi client so the caller
                       can decide whether to fall back to OAuth.
        """
        quality_str = HIFI_QUALITY_MAP.get(self.session.audio_quality, "LOSSLESS")
        result = self.tidal.hifi_client.track_stream(media.id, quality_str)
        manifest = HiFiStreamManifest(
            urls=result.urls,
            file_extension=result.file_extension,
            codecs=result.codecs,
            is_encrypted=result.encryption_type not in ("NONE", ""),
            encryption_key=None,
        )
        return TrackStreamInfo(
            stream_manifest=manifest,
            file_extension=result.file_extension,
            requires_flac_extraction=False,
            media_stream=None,
        )

    def _get_media_urls(
        self,
        media: Track | Video,
        stream_manifest: StreamManifest | None = None,
    ) -> list[str]:
        """Extract URLs for the given media item.

        Args:
            media (Track | Video): The media item to download.
            stream_manifest (StreamManifest | None, optional): Stream manifest for tracks. Defaults to None.

        Returns:
            list[str]: List of URLs for the media segments.
        """
        # Get urls for media.
        if isinstance(media, Track):
            return stream_manifest.get_urls()
        elif isinstance(media, Video):
            quality_video = self.settings.data.quality_video
            m3u8_variant: m3u8.M3U8 = m3u8.load(media.get_url())
            # Find the desired video resolution or the next best one.
            m3u8_playlist, _ = self._extract_video_stream(m3u8_variant, int(quality_video))

            return m3u8_playlist.files
        else:
            return []

    def _setup_progress(
        self,
        media_name: str,
        urls: list[str],
        progress_to_stdout: bool,
    ) -> tuple[TaskID, int | float | None, int | None]:
        """Set up the progress bar/task and compute progress total and block size.

        Args:
            media_name (str): Name of the media item.
            urls (list[str]): List of segment URLs.
            progress_to_stdout (bool): Whether to show progress in stdout.

        Returns:
            tuple[TaskID, int | float | None, int | None]: (TaskID, progress_total, block_size)
        """
        urls_count: int = len(urls)
        progress_total: int | float | None = None
        block_size: int | None = None

        # Compute total iterations for progress
        if urls_count > 1:
            progress_total: int = urls_count
            block_size: int | None = None
        elif urls_count == 1:
            r = None
            try:
                # Get file size and compute progress steps
                r = requests.head(urls[0], timeout=REQUESTS_TIMEOUT_SEC)
                r.raise_for_status()

                total_size_in_bytes: int = int(r.headers.get("content-length", 0))
                block_size = 1048576
                progress_total = total_size_in_bytes / block_size
            finally:
                if r:
                    r.close()
        else:
            raise ValueError

        # Create progress Task
        p_task: TaskID = self.progress.add_task(
            f"[blue]Item '{media_name[:30]}'",
            total=progress_total,
            visible=progress_to_stdout,
        )
        return p_task, progress_total, block_size

    def _download_segments(
        self,
        urls: list[str],
        path_base: pathlib.Path,
        block_size: int | None,
        p_task: TaskID,
        progress_to_stdout: bool,
        event_stop: Event | None = None,
    ) -> tuple[bool, list[DownloadSegmentResult]]:
        """Download all segments with progress reporting and abort handling.

        Args:
            urls (list[str]): List of segment URLs.
            path_base (pathlib.Path): Base path for segment files.
            block_size (int | None): Block size for streaming.
            p_task (TaskID): Progress bar task ID.
            progress_to_stdout (bool): Whether to show progress in stdout.
            event_stop (Event | None, optional): Event to stop the download. Defaults to None.

        Returns:
            tuple[bool, list[DownloadSegmentResult]]: (result_segments, list of segment results)
        """
        result_segments: bool = True
        dl_segment_results: list[DownloadSegmentResult] = []

        # Download segments until progress is finished.
        while not self.progress.tasks[p_task].finished:
            with futures.ThreadPoolExecutor(
                max_workers=self.settings.data.downloads_simultaneous_per_track_max
            ) as executor:
                # Dispatch all download tasks to worker threads
                l_futures: list[futures.Future] = [
                    executor.submit(self._download_segment, url, path_base, block_size, p_task, progress_to_stdout)
                    for url in urls
                ]

                # Report results as they become available
                for future in futures.as_completed(l_futures):
                    # Retrieve result
                    result_dl_segment: DownloadSegmentResult = future.result()

                    dl_segment_results.append(result_dl_segment)

                    # Check for a link that was skipped
                    if not result_dl_segment.result and (result_dl_segment.url is not urls[-1]):
                        # Sometimes it happens, if a track is very short (< 8 seconds or so), that the last URL
                        # in `urls` is invalid (HTTP Error 500) and not necessary. File won't be corrupt.
                        # If this is NOT the case, but any other URL has resulted in an error,
                        # mark the whole thing as corrupt.
                        result_segments = False

                        self.fn_logger.error("Something went wrong while downloading. File is corrupt!")

                    # If app is terminated (CTRL+C) or item stopped
                    if self.event_abort.is_set() or (event_stop and event_stop.is_set()):
                        # Cancel all not yet started tasks
                        for f in l_futures:
                            f.cancel()

                        return False, dl_segment_results

        return result_segments, dl_segment_results

    def _download_postprocess(
        self,
        result_segments: bool,
        path_file: pathlib.Path,
        dl_segment_results: list[DownloadSegmentResult],
        media: Track | Video,
        stream_manifest: StreamManifest | None = None,
    ) -> tuple[bool, pathlib.Path]:
        """Merge segments, decrypt if needed, and return the final file path.

        Args:
            result_segments (bool): Whether all segments downloaded successfully.
            path_file (pathlib.Path): Path to the output file.
            dl_segment_results (list[DownloadSegmentResult]): List of segment download results.
            media (Track | Video): The media item.
            stream_manifest (StreamManifest | None, optional): Stream manifest for tracks. Defaults to None.

        Returns:
            tuple[bool, pathlib.Path]: (Success, path to downloaded or decrypted file)
        """
        tmp_path_file_decrypted: pathlib.Path = path_file
        result_merge: bool = False

        # Only if no error happened while downloading.
        if result_segments:
            # Bring list into right order, so segments can be easily merged.
            dl_segment_results.sort(key=lambda x: x.id_segment)

            result_merge = self._segments_merge(path_file, dl_segment_results)

            if not result_merge:
                self.fn_logger.error(f"Something went wrong while writing to {media.name}. File is corrupt!")
            elif isinstance(media, Track) and stream_manifest.is_encrypted:
                key, nonce = decrypt_security_token(stream_manifest.encryption_key)
                tmp_path_file_decrypted = path_file.with_suffix(".decrypted")

                decrypt_file(path_file, tmp_path_file_decrypted, key, nonce)

        return result_merge, tmp_path_file_decrypted

    def _download(
        self,
        media: Track | Video,
        path_file: pathlib.Path,
        stream_manifest: StreamManifest | None = None,
        event_stop: Event | None = None,
    ) -> tuple[bool, pathlib.Path]:
        """Download a media item (track or video), handling segments and merging.

        Args:
            media (Track | Video): The media item to download.
            path_file (pathlib.Path): Path to the output file.
            stream_manifest (StreamManifest | None, optional): Stream manifest for tracks. Defaults to None.
            event_stop (Event | None, optional): Event to stop the download. Defaults to None.

        Returns:
            tuple[bool, pathlib.Path]: (Success, path to downloaded or decrypted file)
        """
        media_name: str = name_builder_item(media)

        try:
            urls: list[str] = self._get_media_urls(media, stream_manifest)
        except Exception:
            return False, path_file

        # Always output progress to stdout (no GUI)
        progress_to_stdout: bool = True

        try:
            p_task, progress_total, block_size = self._setup_progress(media_name, urls, progress_to_stdout)
        except Exception:
            return False, path_file

        result_segments, dl_segment_results = self._download_segments(
            urls, path_file.parent, block_size, p_task, progress_to_stdout, event_stop
        )

        result_merge, tmp_path_file_decrypted = self._download_postprocess(
            result_segments, path_file, dl_segment_results, media, stream_manifest
        )

        return result_merge, tmp_path_file_decrypted

    def _segments_merge(self, path_file: pathlib.Path, dl_segment_results: list[DownloadSegmentResult]) -> bool:
        """Merge downloaded segments into a single file and clean up segment files.

        Args:
            path_file (pathlib.Path): Path to the output file.
            dl_segment_results (list[DownloadSegmentResult]): List of segment download results.

        Returns:
            bool: True if merge succeeded, False otherwise.
        """
        result: bool = True

        # Copy the content of all segments into one file.
        try:
            with path_file.open("wb") as f_target:
                for dl_segment_result in dl_segment_results:
                    with dl_segment_result.path_segment.open("rb") as f_segment:
                        # Read and write chunks, which gives better HDD write performance
                        while segment := f_segment.read(CHUNK_SIZE):
                            f_target.write(segment)

                    # Delete segment from HDD
                    dl_segment_result.path_segment.unlink()

        except Exception:
            if dl_segment_result is not dl_segment_results[-1]:
                result = False

        return result

    def _download_segment(
        self, url: str, path_base: pathlib.Path, block_size: int | None, p_task: TaskID, progress_to_stdout: bool
    ) -> DownloadSegmentResult:
        """Download a single segment of a media file.

        Args:
            url (str): URL of the segment.
            path_base (pathlib.Path): Base path for segment file.
            block_size (int | None): Block size for streaming.
            p_task (TaskID): Progress bar task ID.
            progress_to_stdout (bool): Whether to show progress in stdout.

        Returns:
            DownloadSegmentResult: Result of the segment download.
        """
        result: bool = False
        path_segment: pathlib.Path = path_base / url_to_filename(url)
        # Calculate the segment ID based on the file name within the URL.
        filename_stem: str = str(path_segment.stem).split("_")[-1]
        # CAUTION: This is a workaround, so BTS (LOW quality) track will work. They usually have only ONE link.
        id_segment: int = int(filename_stem) if filename_stem.isdecimal() else 0
        error: HTTPError | None = None

        # If app is terminated (CTRL+C)
        if self.event_abort.is_set():
            return DownloadSegmentResult(
                result=False, url=url, path_segment=path_segment, id_segment=id_segment, error=error
            )

        if not self.event_run.is_set():
            self.event_run.wait()

        # Retry download on failed segments, with an exponential delay between retries
        with requests.Session() as s:
            retries = Retry(total=5, backoff_factor=1)

            s.mount("https://", HTTPAdapter(max_retries=retries))

            try:
                # Create the request object with stream=True, so the content won't be loaded into memory at once.
                r = s.get(url, stream=True, timeout=REQUESTS_TIMEOUT_SEC)

                r.raise_for_status()

                # Write the content to disk. If `chunk_size` is set to `None` the whole file will be written at once.
                expected_size: int = int(r.headers.get("content-length", 0))
                with path_segment.open("wb") as f:
                    for data in r.iter_content(chunk_size=block_size):
                        f.write(data)
                        # Advance progress bar.
                        self.progress.advance(p_task)

                # Integrity check: compare actual bytes written to Content-Length.
                if expected_size > 0 and path_segment.is_file():
                    actual_size = path_segment.stat().st_size
                    if actual_size != expected_size:
                        path_segment.unlink(missing_ok=True)
                        self.fn_logger.warning(
                            f"Integrity check failed for '{path_segment.name}': "
                            f"expected {expected_size} B, got {actual_size} B. Segment discarded."
                        )
                        result = False
                    else:
                        result = True
                else:
                    result = True
            except Exception:
                self.progress.advance(p_task)

        return DownloadSegmentResult(
            result=result, url=url, path_segment=path_segment, id_segment=id_segment, error=error
        )

    def extension_guess(
        self, quality_audio: Quality, metadata_tags: list[str], is_video: bool
    ) -> AudioExtensions | VideoExtensions:
        """Guess the file extension for a media item based on quality and type.

        Args:
            quality_audio (Quality): Audio quality.
            metadata_tags (list[str]): Metadata tags for the media.
            is_video (bool): Whether the media is a video.

        Returns:
            AudioExtensions | VideoExtensions: Guessed file extension.
        """
        result: AudioExtensions | VideoExtensions

        if is_video:
            result = AudioExtensions.MP4 if self.settings.data.video_convert_mp4 else VideoExtensions.TS
        else:
            result = (
                AudioExtensions.FLAC
                if len(metadata_tags) > 0  # If there are no metadata tags only lossy quality is available
                and (
                    (
                        self.settings.data.extract_flac
                        and quality_audio in (Quality.hi_res_lossless, Quality.high_lossless)
                    )
                    or (
                        "HIRES_LOSSLESS" not in metadata_tags
                        and quality_audio not in (Quality.low_96k, Quality.low_320k)
                    )
                    or quality_audio == Quality.high_lossless
                )
                else AudioExtensions.M4A
            )

        return result

    def item(
        self,
        file_template: str,
        media_id: str | None = None,
        media_type: MediaType | None = None,
        media: Track | Video | None = None,
        video_download: bool = True,
        download_delay: bool = False,
        quality_audio: Quality | None = None,
        quality_video: QualityVideo | None = None,
        is_parent_album: bool = False,
        list_position: int = 0,
        list_total: int = 0,
        event_stop: Event | None = None,
        duplicate_action_override: str | None = None,
    ) -> tuple[DownloadOutcome, pathlib.Path | str]:
        """Download a single media item, handling file naming, skipping, and post-processing.

        Args:
            file_template (str): Template for file naming.
            media_id (str | None, optional): Media ID. Defaults to None.
            media_type (MediaType | None, optional): Media type. Defaults to None.
            media (Track | Video | None, optional): Media item. Defaults to None.
            video_download (bool, optional): Whether to allow video downloads. Defaults to True.
            download_delay (bool, optional): Whether to delay between downloads. Defaults to False.
            quality_audio (Quality | None, optional): Audio quality. Defaults to None.
            quality_video (QualityVideo | None, optional): Video quality. Defaults to None.
            is_parent_album (bool, optional): Whether this is a parent album. Defaults to False.
            list_position (int, optional): Position in list. Defaults to 0.
            list_total (int, optional): Total items in list. Defaults to 0.
            event_stop (Event | None, optional): Event to stop the download. Defaults to None.

        Returns:
            tuple[DownloadOutcome, pathlib.Path | str]: (Outcome, path to file)
        """
        # Check for stop signal before doing anything
        if self.event_abort.is_set() or (event_stop and event_stop.is_set()):
            return DownloadOutcome.FAILED, ""

        # Step 1: Validate and prepare media
        validated_media = self._validate_and_prepare_media(media, media_id, media_type, video_download)
        if validated_media is None or not isinstance(validated_media, Track | Video):
            return DownloadOutcome.FAILED, ""

        media = validated_media

        # Check for stop signal
        if self.event_abort.is_set() or (event_stop and event_stop.is_set()):
            return DownloadOutcome.FAILED, ""

        # Step 2: Create file paths and determine skip logic
        bypass_isrc = duplicate_action_override == "redownload"
        path_media_dst, file_extension_dummy, skip_file, skip_download = self._prepare_file_paths_and_skip_logic(
            media, file_template, quality_audio, list_position, list_total, bypass_isrc=bypass_isrc
        )

        # Handle copy override: copy source file directly to destination.
        if duplicate_action_override == "copy" and isinstance(media, Track):
            isrc = getattr(media, "isrc", None)
            src_path_str = self._isrc_index.get_path(isrc) if isrc else None
            if src_path_str and pathlib.Path(src_path_str).is_file():
                src_ext = pathlib.Path(src_path_str).suffix
                path_copy_dst = path_media_dst.with_suffix(src_ext)
                path_copy_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path_str, path_copy_dst)
                self.fn_logger.info(
                    f"Copied '{name_builder_item(media)}' from '{src_path_str}'."
                )
                return DownloadOutcome.COPIED, path_copy_dst
            else:
                # Source gone — fall through to normal download
                self.fn_logger.warning(
                    f"Copy source missing for '{name_builder_item(media)}'; re-downloading."
                )
                bypass_isrc = True
                path_media_dst, file_extension_dummy, skip_file, skip_download = (
                    self._prepare_file_paths_and_skip_logic(
                        media, file_template, quality_audio, list_position, list_total, bypass_isrc=True
                    )
                )

        if skip_file:
            self.fn_logger.debug(f"Download skipped, since file exists: '{path_media_dst}'")

            return DownloadOutcome.SKIPPED, path_media_dst

        # Step 3: Handle quality settings
        quality_audio_old, quality_video_old = self._adjust_quality_settings(quality_audio, quality_video)

        # Step 4: Download and process media
        download_success = self._download_and_process_media(
            media,
            path_media_dst,
            skip_download,
            is_parent_album,
            file_extension_dummy,
            event_stop,
        )

        # Step 5: Post-processing
        self._perform_post_processing(
            media,
            path_media_dst,
            quality_audio,
            quality_video,
            quality_audio_old,
            quality_video_old,
            download_delay,
            skip_file,
            event_stop,
        )

        outcome = DownloadOutcome.DOWNLOADED if download_success else DownloadOutcome.FAILED

        # Record the ISRC after a successful download so future duplicate checks work.
        if outcome == DownloadOutcome.DOWNLOADED and isinstance(media, Track):
            isrc = getattr(media, "isrc", None)
            if isrc and self.settings.data.skip_duplicate_isrc:
                self._isrc_index.add(isrc, path_media_dst)
                self._isrc_index.maybe_flush(every_n=25)
            self._on_successful_track()

        return outcome, path_media_dst

    def _validate_and_prepare_media(
        self,
        media: Track | Video | Album | Playlist | UserPlaylist | Mix | None,
        media_id: str | None,
        media_type: MediaType | None,
        video_download: bool = True,
    ) -> Track | Video | Album | Playlist | UserPlaylist | Mix | None:
        """Validate and prepare media instance for download.

        Args:
            media (Track | Video | Album | Playlist | UserPlaylist | Mix | None): Media instance.
            media_id (str | None): Media ID if creating new instance.
            media_type (MediaType | None): Media type if creating new instance.
            video_download (bool, optional): Whether video downloads are allowed. Defaults to True.

        Returns:
            Track | Video | Album | Playlist | UserPlaylist | Mix | None: Prepared media instance or None if invalid.
        """
        try:
            if media_id and media_type:
                # If no media instance is provided, we need to create the media instance.
                # Throws `tidalapi.exceptions.ObjectNotFound` if item is not available anymore.
                media = instantiate_media(self.session, media_type, media_id, cache=self._api_cache)
            elif isinstance(media, Track | Video):
                # Check if media is available not deactivated / removed from TIDAL.
                if not media.allow_streaming:
                    self.fn_logger.info(
                        f"This item is not available for listening anymore on TIDAL. Skipping: {name_builder_item(media)}"
                    )
                    return None
                elif isinstance(media, Track):
                    # Re-create media instance with full album information
                    media = self.session.track(str(media.id), with_album=True)
            elif isinstance(media, Album):
                # Check if media is available not deactivated / removed from TIDAL.
                if not media.allow_streaming:
                    self.fn_logger.info(
                        f"This item is not available for listening anymore on TIDAL. Skipping: {name_builder_title(media)}"
                    )
                    return None
            elif not media:
                self._raise_media_missing()
        except (MediaMissing, Exception):
            return None

        # If video download is not allowed and this is a video, return None
        if not video_download and isinstance(media, Video):
            self.fn_logger.info(
                f"Video downloads are deactivated (see settings). Skipping video: {name_builder_item(media)}"
            )
            return None

        return media

    def _raise_media_missing(self) -> None:
        """Raise MediaMissing exception.

        Helper method to abstract raise statement as per TRY301.
        """
        raise MediaMissing

    def _prepare_file_paths_and_skip_logic(
        self,
        media: Track | Video,
        file_template: str,
        quality_audio: Quality | None,
        list_position: int,
        list_total: int,
        bypass_isrc: bool = False,
    ) -> tuple[pathlib.Path, str, bool, bool]:
        """Prepare file paths and determine skip logic.

        Args:
            media (Track | Video): Media item.
            file_template (str): Template for file naming.
            quality_audio (Quality | None): Audio quality setting.
            list_position (int): Position in list.
            list_total (int): Total items in list.

        Returns:
            tuple[pathlib.Path, str, bool, bool]: (path_media_dst, file_extension_dummy, skip_file, skip_download)
        """
        # Create file name and path
        metadata_tags = [] if isinstance(media, Video) else (media.media_metadata_tags or [])
        quality_for_extension = quality_audio if quality_audio is not None else Quality.high_lossless

        file_extension_dummy: str = self.extension_guess(
            quality_for_extension,
            metadata_tags=metadata_tags,
            is_video=isinstance(media, Video),
        )

        file_name_relative: str = format_path_media(
            file_template,
            media,
            self.settings.data.album_track_num_pad_min,
            list_position,
            list_total,
            delimiter_artist=self.settings.data.filename_delimiter_artist,
            delimiter_album_artist=self.settings.data.filename_delimiter_album_artist,
            use_primary_album_artist=self.settings.data.use_primary_album_artist,
        )

        path_media_dst: pathlib.Path = (
            pathlib.Path(self.path_base).expanduser() / (file_name_relative + file_extension_dummy)
        ).absolute()

        # Sanitize final path_file to fit into OS boundaries.
        # uniquify=True guards against same-titled tracks on the same album/playlist
        # when no numeric prefix is present in the filename template.
        path_media_dst = pathlib.Path(path_file_sanitize(path_media_dst, adapt=True, uniquify=True))

        # Compute if and how downloads need to be skipped.
        skip_download: bool = False

        if self.skip_existing:
            skip_file: bool = check_file_exists(path_media_dst, extension_ignore=False)

            if self.settings.data.symlink_to_track and not isinstance(media, Video):
                # Compute symlink tracks path, sanitize and check if file exists
                file_name_track_dir_relative: str = format_path_media(
                    self.settings.data.format_track,
                    media,
                    delimiter_artist=self.settings.data.filename_delimiter_artist,
                    delimiter_album_artist=self.settings.data.filename_delimiter_album_artist,
                    use_primary_album_artist=self.settings.data.use_primary_album_artist,
                )
                path_media_track_dir: pathlib.Path = (
                    pathlib.Path(self.path_base).expanduser() / (file_name_track_dir_relative + file_extension_dummy)
                ).absolute()
                path_media_track_dir = pathlib.Path(path_file_sanitize(path_media_track_dir, adapt=True))
                file_exists_track_dir: bool = check_file_exists(path_media_track_dir, extension_ignore=False)
                file_exists_playlist_dir: bool = (
                    not file_exists_track_dir and skip_file and not path_media_dst.is_symlink()
                )
                skip_download = file_exists_playlist_dir or file_exists_track_dir

                # If file exists in playlist dir but not in track dir, we don't skip the file itself
                if skip_file and file_exists_playlist_dir:
                    skip_file = False
        else:
            skip_file: bool = False

        # ISRC-based cross-context dedup: skip if the same recording was already
        # downloaded to *any* path (independent of skip_existing path check).
        # bypass_isrc=True is set for redownload overrides decided in pre-flight.
        if (
            not bypass_isrc
            and not skip_file
            and self.settings.data.skip_duplicate_isrc
            and isinstance(media, Track)
            and getattr(media, "isrc", None)
            and self._isrc_index.contains(media.isrc)
        ):
            skip_file = True

        return path_media_dst, file_extension_dummy, skip_file, skip_download

    def _adjust_quality_settings(
        self, quality_audio: Quality | None, quality_video: QualityVideo | None
    ) -> tuple[Quality | None, QualityVideo | None]:
        """Adjust quality settings and return previous values.

        Args:
            quality_audio (Quality | None): Audio quality setting.
            quality_video (QualityVideo | None): Video quality setting.

        Returns:
            tuple[Quality | None, QualityVideo | None]: Previous quality settings.
        """
        quality_audio_old: Quality | None = None
        quality_video_old: QualityVideo | None = None

        if quality_audio:
            quality_audio_old = self.adjust_quality_audio(quality_audio)

        if quality_video:
            quality_video_old = self.adjust_quality_video(quality_video)

        return quality_audio_old, quality_video_old

    def _download_and_process_media(
        self,
        media: Track | Video,
        path_media_dst: pathlib.Path,
        skip_download: bool,
        is_parent_album: bool,
        file_extension_dummy: str,
        event_stop: Event | None = None,
    ) -> bool:
        """Download and process media file.

        Args:
            media (Track | Video): Media item.
            path_media_dst (pathlib.Path): Destination file path.
            skip_download (bool): Whether to skip download.
            is_parent_album (bool): Whether this is a parent album.
            file_extension_dummy (str): Dummy file extension.
            event_stop (Event | None, optional): Event to stop the download. Defaults to None.

        Returns:
            bool: Whether download was successful.
        """
        if skip_download:
            return True

        # Get stream information and final file extension
        stream_manifest, file_extension, do_flac_extract, media_stream = self._get_stream_info(media)

        if stream_manifest is None and isinstance(media, Track):
            return False

        # Update path if extension changed
        if path_media_dst.suffix != file_extension:
            path_media_dst = path_media_dst.with_suffix(file_extension)
            path_media_dst = pathlib.Path(path_file_sanitize(path_media_dst, adapt=True))

        os.makedirs(path_media_dst.parent, exist_ok=True)

        # Perform actual download
        return self._perform_actual_download(
            media,
            path_media_dst,
            stream_manifest,
            do_flac_extract,
            is_parent_album,
            media_stream,
            event_stop,
        )

    def _get_stream_info(self, media: Track | Video) -> tuple[StreamManifest | None, str, bool, Stream | None]:
        """Get stream information for media, routing through Hi-Fi API or OAuth path.

        For the Hi-Fi API source the stream lock is intentionally skipped because
        Hi-Fi requests are stateless and do not mutate the tidalapi session.  The
        OAuth path retains the broad lock to prevent the Atmos/Normal credential
        race condition described in the original comments below.

        Args:
            media (Track | Video): Media item.

        Returns:
            tuple[StreamManifest | None, str, bool, Stream | None]: Stream info.
        """
        # ------------------------------------------------------------------
        # Hi-Fi API path (Track only) — stateless, no session lock required
        # ------------------------------------------------------------------
        if (
            isinstance(media, Track)
            and self.tidal.active_source == DownloadSource.HIFI_API
            and self.tidal.hifi_client is not None
        ):
            try:
                track_info = self._get_track_stream_info_hifi(media)
                if track_info.stream_manifest is not None:
                    return (
                        track_info.stream_manifest,
                        track_info.file_extension,
                        track_info.requires_flac_extraction,
                        track_info.media_stream,
                    )
            except TooManyRequests:
                self._on_rate_limit_hit()
                self.fn_logger.exception(
                    f"Too many requests (Hi-Fi API). Skipping '{name_builder_item(media)}'.  "
                    f"Consider activating download delay."
                )
                return None, "", False, None
            except Exception:
                allow_fallback = getattr(self.settings.data, "download_source_fallback", True)
                if not allow_fallback:
                    self.fn_logger.exception(
                        f"Hi-Fi API failed for '{name_builder_item(media)}'. Fallback is disabled."
                    )
                    return None, "", False, None
                self.fn_logger.warning(
                    f"Hi-Fi API failed for '{name_builder_item(media)}'. Falling back to OAuth."
                )
                # Fall through to OAuth path below

        # ------------------------------------------------------------------
        # OAuth path — CRITICAL: broad lock serializes session credential changes
        #
        # THE PROBLEM: The shared tidalapi session must switch credentials to
        # serve Atmos vs Hi-Res/Normal streams.  Without this lock a thread
        # could overwrite the credentials mid-flight in another thread.
        #
        # THE TRADEOFF: This creates a "tollbooth" bottleneck on stream-info
        # fetching; actual segment downloads still run in parallel.
        #
        # DO NOT "OPTIMIZE" THIS by making the lock more granular.
        # Correctness > Performance.
        # ------------------------------------------------------------------
        with self.tidal.stream_lock:
            # Proactively refresh a near-expiry OAuth token before the API call.
            self.tidal._ensure_token_fresh()

            try:
                if isinstance(media, Track):
                    track_info = self._get_track_stream_info(media)

                    if track_info.stream_manifest is None:
                        return None, "", False, None

                    return (
                        track_info.stream_manifest,
                        track_info.file_extension,
                        track_info.requires_flac_extraction,
                        track_info.media_stream,
                    )

                elif isinstance(media, Video):
                    # Videos always require the normal session
                    if not self.tidal.restore_normal_session():
                        self.fn_logger.error(f"Failed to restore normal session for video: {media.id}")
                        return None, "", False, None

                    file_extension = AudioExtensions.MP4 if self.settings.data.video_convert_mp4 else VideoExtensions.TS
                    return None, file_extension, False, None

                else:
                    self.fn_logger.error(f"Unknown media type for stream info: {type(media)}")
                    return None, "", False, None

            except TooManyRequests:
                self._on_rate_limit_hit()
                self.fn_logger.exception(
                    f"Too many requests against TIDAL backend. Skipping '{name_builder_item(media)}'. "
                    f"Consider activating delay between downloads."
                )
                return None, "", False, None

            except Exception:
                self.fn_logger.exception(f"Something went wrong. Skipping '{name_builder_item(media)}'.")
                return None, "", False, None

    def _get_track_stream_info(self, media: Track) -> TrackStreamInfo:
        """Get stream info for a Track, handling Atmos/Normal session switching.

        Args:
            media: The track to get stream information for.

        Returns:
            TrackStreamInfo: Container with stream manifest, file extension,
                            FLAC extraction flag, and media stream object.
                            Returns TrackStreamInfo with None/empty values if fails.
        """
        want_atmos = (
            self.settings.data.download_dolby_atmos
            and hasattr(media, "audio_modes")
            and AudioMode.dolby_atmos.value in media.audio_modes
        )

        if want_atmos:
            if not self.tidal.switch_to_atmos_session():
                self.fn_logger.error(f"Failed to switch to Atmos session for track: {media.id}")
                return TrackStreamInfo(None, "", False, None)
        else:
            if not self.tidal.restore_normal_session():
                self.fn_logger.error(f"Failed to restore normal session for track: {media.id}")
                return TrackStreamInfo(None, "", False, None)

        media_stream = self.session.track(media.id).get_stream() if want_atmos else media.get_stream()

        # Log when the delivered quality differs from the requested quality.
        requested_quality = self.session.audio_quality
        delivered_quality = media_stream.audio_quality
        req_rank = QUALITY_RANK.get(requested_quality, -1)
        del_rank = QUALITY_RANK.get(delivered_quality, -1)

        if del_rank < req_rank:
            self.fn_logger.warning(
                f"Quality mismatch for '{name_builder_item(media)}': "
                f"requested {requested_quality.value} but received {delivered_quality.value}."
            )

        stream_manifest = media_stream.get_stream_manifest()
        file_extension = stream_manifest.file_extension
        requires_flac_extraction = False

        if self.settings.data.extract_flac and (
            stream_manifest.codecs.upper() == Codec.FLAC and file_extension != AudioExtensions.FLAC
        ):
            file_extension = AudioExtensions.FLAC
            requires_flac_extraction = True

        return TrackStreamInfo(
            stream_manifest=stream_manifest,
            file_extension=file_extension,
            requires_flac_extraction=requires_flac_extraction,
            media_stream=media_stream,
        )

    def _perform_actual_download(
        self,
        media: Track | Video,
        path_media_dst: pathlib.Path,
        stream_manifest: StreamManifest | None,
        do_flac_extract: bool,
        is_parent_album: bool,
        media_stream: Stream | None,
        event_stop: Event | None = None,
    ) -> bool:
        """Perform the actual download and processing.

        Args:
            media (Track | Video): Media item.
            path_media_dst (pathlib.Path): Destination file path.
            stream_manifest (StreamManifest | None): Stream manifest.
            do_flac_extract (bool): Whether to extract FLAC.
            is_parent_album (bool): Whether this is a parent album.
            media_stream (Stream | None): Media stream.
            event_stop (Event | None, optional): Event to stop the download. Defaults to None.

        Returns:
            bool: Whether download was successful.
        """
        # Create a temp directory and file.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_path_dir:
            tmp_path_file: pathlib.Path = pathlib.Path(tmp_path_dir) / str(uuid4())
            tmp_path_file.touch()

            # Download media.
            result_download, tmp_path_file = self._download(
                media=media,
                stream_manifest=stream_manifest,
                path_file=tmp_path_file,
                event_stop=event_stop,
            )

            if not result_download:
                return False

            # Convert video from TS to MP4
            if isinstance(media, Video) and self.settings.data.video_convert_mp4:
                tmp_path_file = self._video_convert(tmp_path_file)

            # Extract FLAC from MP4 container using ffmpeg
            if isinstance(media, Track) and self.settings.data.extract_flac and do_flac_extract:
                tmp_path_file = self._extract_flac(tmp_path_file)

            # Handle metadata, lyrics, and cover
            self._handle_metadata_and_extras(media, tmp_path_file, path_media_dst, is_parent_album, media_stream)

            self.fn_logger.info(f"Downloaded item '{name_builder_item(media)}'.")

            # Move final file to the configured destination directory.
            shutil.move(tmp_path_file, path_media_dst)

            return True

    def _handle_metadata_and_extras(
        self,
        media: Track | Video,
        tmp_path_file: pathlib.Path,
        path_media_dst: pathlib.Path,
        is_parent_album: bool,
        media_stream: Stream | None,
    ) -> None:
        """Handle metadata, lyrics, and cover processing.

        Args:
            media (Track | Video): Media item.
            tmp_path_file (pathlib.Path): Temporary file path.
            path_media_dst (pathlib.Path): Destination file path.
            is_parent_album (bool): Whether this is a parent album.
            media_stream (Stream | None): Media stream.
        """
        if isinstance(media, Video):
            return

        tmp_path_lyrics: pathlib.Path | None = None
        tmp_path_cover: pathlib.Path | None = None

        # Write metadata to file.
        if media_stream:
            result_metadata, tmp_path_lyrics, tmp_path_cover = self.metadata_write(
                media, tmp_path_file, is_parent_album, media_stream
            )

        # Move lyrics file
        if self.settings.data.lyrics_file and tmp_path_lyrics:
            self._move_lyrics(tmp_path_lyrics, path_media_dst)

        # Move cover file
        if self.settings.data.cover_album_file and tmp_path_cover:
            self._move_cover(tmp_path_cover, path_media_dst)

    def _perform_post_processing(
        self,
        media: Track | Video,
        path_media_dst: pathlib.Path,
        quality_audio: Quality | None,
        quality_video: QualityVideo | None,
        quality_audio_old: Quality | None,
        quality_video_old: QualityVideo | None,
        download_delay: bool,
        skip_file: bool,
        event_stop: Event | None = None,
    ) -> None:
        """Perform post-processing tasks.

        Args:
            media (Track | Video): Media item.
            path_media_dst (pathlib.Path): Destination file path.
            quality_audio (Quality | None): Audio quality setting.
            quality_video (QualityVideo | None): Video quality setting.
            quality_audio_old (Quality | None): Previous audio quality.
            quality_video_old (QualityVideo | None): Previous video quality.
            download_delay (bool): Whether to apply download delay.
            skip_file (bool): Whether file was skipped.
            event_stop (Event | None, optional): Event to stop the download. Defaults to None.
        """
        # If files needs to be symlinked, do postprocessing here.
        if self.settings.data.symlink_to_track and not isinstance(media, Video):
            # Determine file extension for symlink
            file_extension = path_media_dst.suffix
            self.media_move_and_symlink(media, path_media_dst, file_extension)

        # Reset quality settings
        if quality_audio_old is not None:
            self.adjust_quality_audio(quality_audio_old)

        if quality_video_old is not None:
            self.adjust_quality_video(quality_video_old)

        # Apply download delay if needed
        if download_delay and not skip_file:
            time_sleep: float = round(
                random.SystemRandom().uniform(
                    self._adaptive_delay_sec_min, self._adaptive_delay_sec_max
                ),
                1,
            )

            self.fn_logger.debug(f"Next download will start in {time_sleep} seconds.")

            # Use event_stop or event_abort for interruptible sleep
            if event_stop:
                event_stop.wait(time_sleep)
            elif self.event_abort:
                self.event_abort.wait(time_sleep)
            else:
                time.sleep(time_sleep)

    def media_move_and_symlink(
        self, media: Track | Video, path_media_src: pathlib.Path, file_extension: str
    ) -> pathlib.Path:
        """Move a media file and create a symlink if required.

        Args:
            media (Track | Video): Media item.
            path_media_src (pathlib.Path): Source file path.
            file_extension (str): File extension.

        Returns:
            pathlib.Path: Destination path.
        """
        # Compute tracks path, sanitize and ensure path exists
        file_name_relative: str = format_path_media(
            self.settings.data.format_track,
            media,
            delimiter_artist=self.settings.data.filename_delimiter_artist,
            delimiter_album_artist=self.settings.data.filename_delimiter_album_artist,
            use_primary_album_artist=self.settings.data.use_primary_album_artist,
        )
        path_media_dst: pathlib.Path = (
            pathlib.Path(self.path_base).expanduser() / (file_name_relative + file_extension)
        ).absolute()
        path_media_dst = pathlib.Path(path_file_sanitize(path_media_dst, adapt=True))

        os.makedirs(path_media_dst.parent, exist_ok=True)

        # Move item and symlink it
        if path_media_dst != path_media_src:
            if self.skip_existing:
                skip_file: bool = check_file_exists(path_media_dst, extension_ignore=False)
                skip_symlink: bool = path_media_src.is_symlink()
            else:
                skip_file: bool = False
                skip_symlink: bool = False

            if not skip_file:
                self.fn_logger.debug(f"Move: {path_media_src} -> {path_media_dst}")
                shutil.move(path_media_src, path_media_dst)

            if not skip_symlink:
                self.fn_logger.debug(f"Symlink: {path_media_src} -> {path_media_dst}")
                path_media_dst_relative: pathlib.Path = path_media_dst.relative_to(path_media_src.parent, walk_up=True)

                path_media_src.unlink(missing_ok=True)
                path_media_src.symlink_to(path_media_dst_relative)

        return path_media_dst

    def adjust_quality_audio(self, quality: Quality) -> Quality:
        """Temporarily set audio quality and return the previous value.

        Args:
            quality (Quality): New audio quality.

        Returns:
            Quality: Previous audio quality.
        """
        # Save original quality settings
        quality_old: Quality = self.session.audio_quality
        self.session.audio_quality = quality

        return quality_old

    def adjust_quality_video(self, quality: QualityVideo) -> QualityVideo:
        """Temporarily set video quality and return the previous value.

        Args:
            quality (QualityVideo): New video quality.

        Returns:
            QualityVideo: Previous video quality.
        """
        quality_old: QualityVideo = self.settings.data.quality_video

        self.settings.data.quality_video = quality

        return quality_old

    def _move_file(self, path_file_source: pathlib.Path, path_file_destination: str | pathlib.Path) -> bool:
        """Move a file from source to destination.

        Args:
            path_file_source (pathlib.Path): Source file path.
            path_file_destination (str | pathlib.Path): Destination file path.

        Returns:
            bool: True if moved, False otherwise.
        """
        result: bool

        # Check if the file was downloaded
        if path_file_source and path_file_source.is_file():
            # Move it.
            shutil.move(path_file_source, path_file_destination)

            result = True
        else:
            result = False

        return result

    def _move_lyrics(self, path_lyrics: pathlib.Path, file_media_dst: pathlib.Path) -> bool:
        """Move a lyrics file to the destination.

        Args:
            path_lyrics (pathlib.Path): Source lyrics file.
            file_media_dst (pathlib.Path): Destination media file path.

        Returns:
            bool: True if moved, False otherwise.
        """
        # Build tmp lyrics filename
        path_file_lyrics: pathlib.Path = file_media_dst.with_suffix(EXTENSION_LYRICS)
        result: bool = self._move_file(path_lyrics, path_file_lyrics)

        return result

    def _move_cover(self, path_cover: pathlib.Path, file_media_dst: pathlib.Path) -> bool:
        """Move a cover file to the destination.

        Args:
            path_cover (pathlib.Path): Source cover file.
            file_media_dst (pathlib.Path): Destination media file path.

        Returns:
            bool: True if moved, False otherwise.
        """
        # Build cover filename
        path_file_cover: pathlib.Path = file_media_dst.parent / COVER_NAME
        result: bool = self._move_file(path_cover, path_file_cover)

        return result

    def lyrics_to_file(self, dir_destination: pathlib.Path, lyrics: str) -> str:
        """Write lyrics to a temporary file.

        Args:
            dir_destination (pathlib.Path): Directory for the temp file.
            lyrics (str): Lyrics content.

        Returns:
            str: Path to the temp file.
        """
        return self.write_to_tmp_file(dir_destination, mode="x", content=lyrics)

    def cover_to_file(self, dir_destination: pathlib.Path, image: bytes) -> str:
        """Write cover image to a temporary file.

        Args:
            dir_destination (pathlib.Path): Directory for the temp file.
            image (bytes): Image data.

        Returns:
            str: Path to the temp file.
        """
        return self.write_to_tmp_file(dir_destination, mode="xb", content=image)

    def write_to_tmp_file(self, dir_destination: pathlib.Path, mode: str, content: str | bytes) -> str:
        """Write content to a temporary file.

        Args:
            dir_destination (pathlib.Path): Directory for the temp file.
            mode (str): File open mode.
            content (str | bytes): Content to write.

        Returns:
            str: Path to the temp file.
        """
        result: pathlib.Path = dir_destination / str(uuid4())
        encoding: str | None = "utf-8" if isinstance(content, str) else None

        try:
            with open(result, mode=mode, encoding=encoding) as f:
                f.write(content)
        except OSError:
            result = ""

        return result

    @staticmethod
    def cover_data(url: str | None = None, path_file: str | None = None) -> str | bytes:
        """Retrieve cover image data from a URL or file, with up to 3 retry attempts.

        Args:
            url (str | None, optional): URL to download image from. Defaults to None.
            path_file (str | None, optional): Path to image file. Defaults to None.

        Returns:
            str | bytes: Image data or empty string on failure.
        """
        result: str | bytes = ""

        if url:
            for attempt in range(3):
                response = None
                try:
                    response = requests.get(url, timeout=REQUESTS_TIMEOUT_SEC)
                    response.raise_for_status()
                    result = response.content
                    break
                except requests.RequestException:
                    if attempt < 2:
                        time.sleep(2**attempt)
                finally:
                    if response:
                        response.close()
        elif path_file:
            try:
                with open(path_file, "rb") as f:
                    result = f.read()
            except OSError:
                pass

        return result

    def metadata_write(
        self, track: Track, path_media: pathlib.Path, is_parent_album: bool, media_stream: Stream
    ) -> tuple[bool, pathlib.Path | None, pathlib.Path | None]:
        """Write metadata, lyrics, and cover to a media file.

        Args:
            track (Track): Track object.
            path_media (pathlib.Path): Path to media file.
            is_parent_album (bool): Whether this is a parent album.
            media_stream (Stream): Stream object.

        Returns:
            tuple[bool, pathlib.Path | None, pathlib.Path | None]: (Success, path to lyrics, path to cover)
        """
        result: bool = False
        path_lyrics: pathlib.Path | None = None
        path_cover: pathlib.Path | None = None
        release_date: str = (
            track.album.available_release_date.strftime("%Y-%m-%d")
            if track.album.available_release_date
            else track.album.release_date.strftime("%Y-%m-%d") if track.album.release_date else ""
        )
        copy_right: str = track.copyright if hasattr(track, "copyright") and track.copyright else ""
        isrc: str = track.isrc if hasattr(track, "isrc") and track.isrc else ""
        lyrics: str = ""
        lyrics_synced: str = ""
        lyrics_unsynced: str = ""
        cover_data: bytes = None

        if self.settings.data.lyrics_embed or self.settings.data.lyrics_file:
            # Try to retrieve lyrics with up to 3 retries.
            for attempt in range(3):
                try:
                    lyrics_obj = track.lyrics()

                    if lyrics_obj.text:
                        lyrics_unsynced = lyrics_obj.text
                        lyrics = lyrics_unsynced
                    if lyrics_obj.subtitles:
                        lyrics_synced = lyrics_obj.subtitles
                        lyrics = lyrics_synced
                    break
                except Exception:
                    if attempt < 2:
                        time.sleep(2**attempt)
                    else:
                        lyrics = ""
                        self.fn_logger.debug(f"Could not retrieve lyrics for `{name_builder_item(track)}`.")

        if lyrics and self.settings.data.lyrics_file:
            path_lyrics = self.lyrics_to_file(path_media.parent, lyrics)

        cover_dimension = self.settings.data.metadata_cover_dimension

        if self.settings.data.metadata_cover_embed or (self.settings.data.cover_album_file and is_parent_album):
            # Do not write CoverDimensions.PxORIGIN to metadata, since it can exceed max metadata file size (>16Mb)
            url_cover = track.album.image(
                int(cover_dimension) if cover_dimension != CoverDimensions.PxORIGIN else int(CoverDimensions.Px1280)
            )
            cover_data = self.cover_data(url=url_cover)

        if cover_data and self.settings.data.cover_album_file and is_parent_album:
            if cover_dimension == CoverDimensions.PxORIGIN:
                url_cover_album_file = track.album.image(CoverDimensions.PxORIGIN)
                cover_data_album_file = self.cover_data(url=url_cover_album_file)
            else:
                cover_data_album_file = cover_data

            path_cover = self.cover_to_file(path_media.parent, cover_data_album_file)

        metadata_target_upc = MetadataTargetUPC(self.settings.data.metadata_target_upc)
        target_upc: dict[str, str] = METADATA_LOOKUP_UPC[metadata_target_upc]
        explicit: bool = track.explicit if hasattr(track, "explicit") else False
        title = name_builder_title(track)
        title += METADATA_EXPLICIT if explicit and self.settings.data.mark_explicit else ""

        # `None` values are not allowed.
        m: Metadata = Metadata(
            path_file=path_media,
            target_upc=target_upc,
            lyrics=lyrics_synced,
            lyrics_unsynced=lyrics_unsynced,
            copy_right=copy_right,
            title=title,
            artists=name_builder_artist(track, delimiter=self.settings.data.metadata_delimiter_artist),
            album=track.album.name if track.album else "",
            tracknumber=track.track_num,
            date=release_date,
            isrc=isrc,
            albumartist=name_builder_album_artist(track, delimiter=self.settings.data.metadata_delimiter_album_artist),
            totaltrack=track.album.num_tracks if track.album and track.album.num_tracks else 1,
            totaldisc=track.album.num_volumes if track.album and track.album.num_volumes else 1,
            discnumber=track.volume_num if track.volume_num else 1,
            cover_data=cover_data if self.settings.data.metadata_cover_embed else None,
            album_replay_gain=media_stream.album_replay_gain,
            album_peak_amplitude=media_stream.album_peak_amplitude,
            track_replay_gain=media_stream.track_replay_gain,
            track_peak_amplitude=media_stream.track_peak_amplitude,
            url_share=track.share_url if track.share_url and self.settings.data.metadata_write_url else "",
            replay_gain_write=self.settings.data.metadata_replay_gain,
            upc=track.album.upc if track.album and track.album.upc else "",
            explicit=explicit,
            bpm=track.bpm if track.bpm else 0,
            initial_key=format_initial_key(track.key, track.key_scale, self.settings.data.initial_key_format),
        )

        m.save()

        result = True

        return result, path_lyrics, path_cover

    def _preflight_isrc_scan(
        self,
        items: list,
        checkpoint: "DownloadCheckpoint | None" = None,
        is_album: bool = False,
    ) -> dict[str, str]:
        """Scan items for duplicate ISRCs before downloads start.

        Returns a dict mapping str(track.id) -> action ('copy', 'redownload', 'skip').
        Empty dict means no duplicates were found or ISRC dedup is disabled.

        For album downloads (is_album=True) duplicates are never skipped: source
        files are copied if available, re-downloaded if not.  This guarantees
        every album folder is complete regardless of what is already in the library.
        """
        if not self.settings.data.skip_duplicate_isrc:
            return {}

        hits_with_source: list[tuple] = []   # (Track, path_str) — source file exists
        hits_missing_source: list[tuple] = []  # (Track, path_str) — source file gone

        for item_media in items:
            if not isinstance(item_media, Track):
                continue
            # Skip tracks already completed in checkpoint
            if checkpoint is not None:
                if checkpoint.status_of(str(item_media.id)) == STATUS_DOWNLOADED:
                    continue
            isrc = getattr(item_media, "isrc", None)
            if not isrc:
                continue
            path_str = self._isrc_index.get_path(isrc)
            if path_str is None:
                continue
            if pathlib.Path(path_str).is_file():
                hits_with_source.append((item_media, path_str))
            else:
                hits_missing_source.append((item_media, path_str))

        if not hits_with_source and not hits_missing_source:
            return {}

        # Albums must always be complete: copy if source exists, re-download if not.
        # Never skip or prompt for album downloads.
        if is_album:
            resolved: dict[str, str] = {}
            for track, _ in hits_with_source:
                resolved[str(track.id)] = "copy"
            for track, _ in hits_missing_source:
                resolved[str(track.id)] = "redownload"
            if resolved:
                self.fn_logger.info(
                    f"Album download: {len(hits_with_source)} track(s) will be copied from existing "
                    f"library files, {len(hits_missing_source)} will be re-downloaded."
                )
            return resolved

        saved_action = getattr(self.settings.data, "duplicate_action", "ask")

        if saved_action != "ask":
            # Apply saved preference silently
            resolved: dict[str, str] = {}
            if saved_action == "copy":
                for track, _ in hits_with_source:
                    resolved[str(track.id)] = "copy"
                for track, _ in hits_missing_source:
                    self.fn_logger.warning(
                        f"Copy source missing for '{name_builder_item(track)}'; will re-download."
                    )
                    resolved[str(track.id)] = "redownload"
            elif saved_action == "redownload":
                for track, _ in hits_with_source + hits_missing_source:
                    resolved[str(track.id)] = "redownload"
            else:  # skip
                for track, _ in hits_with_source + hits_missing_source:
                    resolved[str(track.id)] = "skip"
            self.fn_logger.info(
                f"Duplicate action '{saved_action}': "
                f"{len(hits_with_source)} copyable, "
                f"{len(hits_missing_source)} source-missing tracks resolved."
            )
            return resolved

        return self._prompt_duplicate_action(hits_with_source, hits_missing_source)

    def _prompt_duplicate_action(
        self,
        hits_with_source: list[tuple],
        hits_missing_source: list[tuple],
    ) -> dict[str, str]:
        """Interactively prompt the user about duplicate ISRCs.

        Returns a dict mapping str(track.id) -> action ('copy', 'redownload', 'skip').
        """
        console = Console()

        if not sys.stdin.isatty():
            self.fn_logger.warning(
                "Non-interactive terminal: defaulting to skip for all duplicates."
            )
            return {
                str(t.id): "skip"
                for t, _ in hits_with_source + hits_missing_source
            }

        # Build display table
        table = Table(
            title="Duplicate tracks detected (already in ISRC index)",
            style="cyan",
            show_lines=True,
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("Artist \u2013 Title", style="white")
        table.add_column("Source path", style="dim")
        table.add_column("Source", width=8)

        for i, (track, path_str) in enumerate(hits_with_source, start=1):
            table.add_row(
                str(i),
                name_builder_item(track),
                path_str,
                "[green]EXISTS[/green]",
            )
        for i, (track, path_str) in enumerate(
            hits_missing_source, start=len(hits_with_source) + 1
        ):
            table.add_row(
                str(i),
                name_builder_item(track),
                path_str,
                "[red]MISSING[/red]",
            )

        console.print(table)

        total = len(hits_with_source) + len(hits_missing_source)
        console.print(f"\n[bold]{total} duplicate(s) found.[/bold]")
        if hits_missing_source:
            console.print(
                f"  [yellow]{len(hits_missing_source)} source file(s) are missing from disk.[/yellow]"
            )

        # Prompt for blanket action
        action_map = {"C": "copy", "R": "redownload", "S": "skip"}
        while True:
            console.print(
                "[bold]What would you like to do?[/bold]  "
                "[C]opy  [R]e-download  [S]kip all"
            )
            raw = input("Choice [C/R/S]: ").strip().upper()
            if raw in action_map:
                selected_action = action_map[raw]
                break
            console.print("[red]Invalid choice. Enter C, R, or S.[/red]")

        resolved: dict[str, str] = {}

        if selected_action == "copy":
            for track, _ in hits_with_source:
                resolved[str(track.id)] = "copy"
            if hits_missing_source:
                console.print(
                    f"  [yellow]{len(hits_missing_source)} track(s) cannot be copied "
                    f"(source missing).[/yellow]"
                )
                sub = input("Re-download missing-source tracks instead? [Y/n]: ").strip().upper()
                missing_action = "redownload" if sub in ("", "Y") else "skip"
                for track, _ in hits_missing_source:
                    resolved[str(track.id)] = missing_action
        elif selected_action == "redownload":
            for track, _ in hits_with_source + hits_missing_source:
                resolved[str(track.id)] = "redownload"
        else:  # skip
            for track, _ in hits_with_source + hits_missing_source:
                resolved[str(track.id)] = "skip"

        # Offer to save preference
        save_raw = input("Save this as your default preference for future runs? [y/N]: ").strip().upper()
        if save_raw == "Y":
            self.settings.data.duplicate_action = selected_action
            if hasattr(self.settings, "save"):
                self.settings.save()
            console.print(f"  [green]Preference '{selected_action}' saved.[/green]")

        return resolved

    def items(
        self,
        file_template: str,
        media: Album | Playlist | UserPlaylist | Mix | None = None,
        media_id: str | None = None,
        media_type: MediaType | None = None,
        video_download: bool = False,
        download_delay: bool = True,
        quality_audio: Quality | None = None,
        quality_video: QualityVideo | None = None,
        event_stop: Event | None = None,
    ) -> None:
        """Download all items in an album, playlist, or mix.

        Args:
            file_template (str): Template for file naming.
            media (Album | Playlist | UserPlaylist | Mix | None, optional): Media item. Defaults to None.
            media_id (str | None, optional): Media ID. Defaults to None.
            media_type (MediaType | None, optional): Media type. Defaults to None.
            video_download (bool, optional): Whether to allow video downloads. Defaults to False.
            download_delay (bool, optional): Whether to delay between downloads. Defaults to True.
            quality_audio (Quality | None, optional): Audio quality. Defaults to None.
            quality_video (QualityVideo | None, optional): Video quality. Defaults to None.
            event_stop (Event | None, optional): Event to stop the download. Defaults to None.
        """
        # Validate and prepare media collection
        validated_media = self._validate_and_prepare_media(media, media_id, media_type, video_download)
        if validated_media is None or not isinstance(validated_media, Album | Playlist | UserPlaylist | Mix):
            return

        media = validated_media

        # Set up download context
        download_context = self._setup_collection_download_context(media, file_template, video_download)
        file_name_relative, list_media_name, list_media_name_short, items, progress_stdout = download_context

        # Set up checkpoint for collection resume.
        collection_id = f"{type(media).__name__.lower()}_{media.id}"
        checkpoint_path = pathlib.Path(path_config_base()) / "checkpoints" / f"{collection_id}.json"
        checkpoint: DownloadCheckpoint | None = None
        try:
            track_ids = [str(item.id) for item in items if isinstance(item, Track)]
            if checkpoint_path.exists():
                checkpoint = DownloadCheckpoint.load(checkpoint_path)
                checkpoint.initialize_tracks(track_ids)
                already_done = sum(1 for v in checkpoint.tracks.values() if v == STATUS_DOWNLOADED)
                if already_done:
                    self.fn_logger.info(
                        f"Resuming '{list_media_name}': "
                        f"{already_done} track(s) already downloaded, skipping."
                    )
            else:
                checkpoint = DownloadCheckpoint(
                    path=checkpoint_path,
                    collection_id=collection_id,
                    collection_type=type(media).__name__.lower(),
                )
                checkpoint.initialize_tracks(track_ids)
                checkpoint.save()
        except Exception as exc:
            self.fn_logger.warning(
                f"Could not set up checkpoint for '{list_media_name}': {exc}. Continuing without checkpoint."
            )
            checkpoint = None

        # Pre-flight: resolve duplicate ISRCs before dispatching the thread pool.
        resolved_actions: dict[str, str] = self._preflight_isrc_scan(
            items, checkpoint, is_album=isinstance(media, Album)
        )

        # Set up progress tracking
        progress: Progress = self.progress_overall if self.progress_overall else self.progress
        progress_task: TaskID = progress.add_task(
            f"[green]List '{list_media_name_short}'", total=len(items), visible=progress_stdout
        )

        # Download configuration
        is_album: bool = isinstance(media, Album)
        sort_by_track_num: bool = bool("album_track_num" in file_name_relative or "list_pos" in file_name_relative)
        list_total: int = len(items)

        # Execute downloads
        summary = DownloadSummary()
        result_dirs: list[pathlib.Path] = self._execute_collection_downloads(
            items,
            file_name_relative,
            quality_audio,
            quality_video,
            download_delay,
            is_album,
            list_total,
            progress,
            progress_task,
            progress_stdout,
            event_stop,
            summary,
            checkpoint,
            resolved_actions=resolved_actions,
        )

        # Clean up checkpoint if all tracks succeeded.
        if checkpoint is not None:
            checkpoint.cleanup_if_complete()

        # Create playlist file if requested
        if self.settings.data.playlist_create:
            self.playlist_populate(set(result_dirs), list_media_name, is_album, sort_by_track_num)

        # Persist ISRC index after all collection downloads complete
        if self.settings.data.skip_duplicate_isrc:
            self._isrc_index.save()

        self.fn_logger.info(f"Finished list '{list_media_name}'.")

        # Print outcome summary
        summary_lines = [
            f"[green]✓ Downloaded:[/green]  {summary.downloaded}",
            f"[yellow]⏭ Skipped:[/yellow]    {summary.skipped}",
            f"[red]✗ Failed:[/red]      {summary.failed}",
        ]
        if summary.copied > 0:
            summary_lines.append(f"[cyan]⎘ Copied:[/cyan]      {summary.copied}")
        summary_lines.append(f"[bold]Total:[/bold]         {summary.total}")
        Console().print(Panel(
            "\n".join(summary_lines),
            title=f"[bold cyan]{list_media_name[:50]}[/bold cyan]",
            border_style="cyan",
            expand=False,
        ))

    def _setup_collection_download_context(
        self,
        media: Album | Playlist | UserPlaylist | Mix,
        file_template: str,
        video_download: bool,
    ) -> tuple[str, str, str, list, bool]:
        """Set up download context for media collection.

        Args:
            media (Album | Playlist | UserPlaylist | Mix): Media collection.
            file_template (str): Template for file naming.
            video_download (bool): Whether to allow video downloads.

        Returns:
            tuple[str, str, str, list, bool]: (file_name_relative, list_media_name, list_media_name_short, items, progress_stdout)
        """
        # Create file name and path
        file_name_relative: str = format_path_media(
            file_template,
            media,
            delimiter_artist=self.settings.data.filename_delimiter_artist,
            delimiter_album_artist=self.settings.data.filename_delimiter_album_artist,
            use_primary_album_artist=self.settings.data.use_primary_album_artist,
        )

        # Get the name of the list and check, if videos should be included.
        list_media_name: str = name_builder_title(media)
        list_media_name_short: str = list_media_name[:30]

        # Get all items of the list.
        items = items_results_all(media, videos_include=video_download)

        # Always output progress to stdout (no GUI)
        progress_stdout: bool = True

        return file_name_relative, list_media_name, list_media_name_short, items, progress_stdout

    def _execute_collection_downloads(
        self,
        items: list,
        file_name_relative: str,
        quality_audio: Quality | None,
        quality_video: QualityVideo | None,
        download_delay: bool,
        is_album: bool,
        list_total: int,
        progress: Progress,
        progress_task: TaskID,
        progress_stdout: bool,
        event_stop: Event | None = None,
        summary: DownloadSummary | None = None,
        checkpoint: DownloadCheckpoint | None = None,
        resolved_actions: dict[str, str] | None = None,
    ) -> list[pathlib.Path]:
        """Execute downloads for all items in the collection.

        Args:
            items (list): List of media items to download.
            file_name_relative (str): Relative file name template.
            quality_audio (Quality | None): Audio quality setting.
            quality_video (QualityVideo | None): Video quality setting.
            download_delay (bool): Whether to apply download delay.
            is_album (bool): Whether this is an album.
            list_total (int): Total number of items.
            progress (Progress): Progress bar instance.
            progress_task (TaskID): Progress task ID.
            progress_stdout (bool): Whether to show progress in stdout.
            event_stop (Event | None, optional): Event to stop the download. Defaults to None.
            summary (DownloadSummary | None, optional): Outcome counter. Defaults to None.
            checkpoint (DownloadCheckpoint | None, optional): Collection checkpoint for resume. Defaults to None.

        Returns:
            list[pathlib.Path]: List of result directories.
        """
        result_dirs: list[pathlib.Path] = []

        # Check if items list is empty
        if not items:
            # Mark progress as complete for empty lists
            progress.update(progress_task, completed=progress.tasks[progress_task].total)

            return result_dirs

        # Iterate through list items
        while not progress.finished:
            with futures.ThreadPoolExecutor(max_workers=self.settings.data.downloads_concurrent_max) as executor:
                # Build future → item_media mapping for checkpoint tracking.
                # Pre-skip tracks already marked 'downloaded' in the checkpoint.
                future_to_item: dict[futures.Future, object] = {}

                for count, item_media in enumerate(items):
                    if checkpoint is not None and isinstance(item_media, Track):
                        if checkpoint.status_of(str(item_media.id)) == STATUS_DOWNLOADED:
                            if summary is not None:
                                summary.record(DownloadOutcome.SKIPPED)
                            progress.advance(progress_task)
                            continue

                    # Apply pre-flight resolved action for this track.
                    override: str | None = None
                    if resolved_actions and isinstance(item_media, Track):
                        resolved = resolved_actions.get(str(item_media.id))
                        if resolved == "skip":
                            if summary is not None:
                                summary.record(DownloadOutcome.SKIPPED)
                            progress.advance(progress_task)
                            continue
                        elif resolved in ("copy", "redownload"):
                            override = resolved

                    future = executor.submit(
                        self.item,
                        media=item_media,
                        file_template=file_name_relative,
                        quality_audio=quality_audio,
                        quality_video=quality_video,
                        download_delay=download_delay,
                        is_parent_album=is_album,
                        list_position=count + 1,
                        list_total=list_total,
                        event_stop=event_stop,
                        duplicate_action_override=override,
                    )
                    future_to_item[future] = item_media

                # Process download results
                result_dirs = self._process_download_futures(
                    list(future_to_item.keys()),
                    progress,
                    progress_task,
                    progress_stdout,
                    summary,
                    checkpoint=checkpoint,
                    future_to_item=future_to_item,
                )

                # Check for abort signal
                if self.event_abort.is_set() or (event_stop and event_stop.is_set()):
                    return result_dirs

        return result_dirs

    def _process_download_futures(
        self,
        futures_list: list[futures.Future],
        progress: Progress,
        progress_task: TaskID,
        progress_stdout: bool,
        summary: DownloadSummary | None = None,
        checkpoint: DownloadCheckpoint | None = None,
        future_to_item: dict | None = None,
    ) -> list[pathlib.Path]:
        """Process download futures and collect results.

        Args:
            futures_list (list[futures.Future]): List of download futures.
            progress (Progress): Progress bar instance.
            progress_task (TaskID): Progress task ID.
            progress_stdout (bool): Whether to show progress in stdout.
            summary (DownloadSummary | None): Optional counter to accumulate outcomes.
            checkpoint (DownloadCheckpoint | None): Collection checkpoint to update per track.
            future_to_item (dict | None): Mapping from future to original media item.

        Returns:
            list[pathlib.Path]: List of result directories.
        """
        result_dirs: list[pathlib.Path] = []

        # Report results as they become available
        for future in futures.as_completed(futures_list):
            # Retrieve result
            outcome, result_path_file = future.result()

            if summary is not None:
                summary.record(outcome)

            if result_path_file:
                result_dirs.append(result_path_file.parent)

            # Update checkpoint for track items.
            if checkpoint is not None and future_to_item is not None:
                item_media = future_to_item.get(future)
                if isinstance(item_media, Track):
                    cp_status = (
                        STATUS_DOWNLOADED if outcome == DownloadOutcome.DOWNLOADED else STATUS_FAILED
                    )
                    checkpoint.mark(str(item_media.id), cp_status)
                    checkpoint.save()

            # Advance progress bar.
            progress.advance(progress_task)

            # If app is terminated (CTRL+C)
            if self.event_abort.is_set():
                # Cancel all not yet started tasks
                for f in futures_list:
                    f.cancel()

                break

        return result_dirs

    def playlist_populate(
        self, dirs_scoped: set[pathlib.Path], name_list: str, is_album: bool, sort_alphabetically: bool
    ) -> list[pathlib.Path]:
        """Create playlist files (m3u) for downloaded tracks in each directory.

        When all tracks in ``dirs_scoped`` share a common parent (e.g. disc
        subdirectories of a multi-disc album), a single consolidated M3U is
        placed at that common parent instead of one per subdirectory.  Track
        paths are written relative to the M3U location so players can resolve
        them regardless of where the library is mounted.

        Args:
            dirs_scoped (set[pathlib.Path]): Set of directories containing tracks.
            name_list (str): Name of the playlist.
            is_album (bool): Whether this is an album.
            sort_alphabetically (bool): Whether to sort tracks alphabetically.

        Returns:
            list[pathlib.Path]: List of created playlist file paths.
        """
        result: list[pathlib.Path] = []

        if not dirs_scoped:
            return result

        # When tracks land in multiple subdirectories (e.g. CD1/, CD2/ for a
        # multi-disc album, or per-artist dirs in a custom playlist template)
        # consolidate everything under their common ancestor so the M3U covers
        # the entire collection in one file.
        if len(dirs_scoped) > 1:
            scan_dirs = [pathlib.Path(os.path.commonpath([str(d) for d in dirs_scoped]))]
        else:
            scan_dirs = list(dirs_scoped)

        for scan_root in scan_dirs:
            # Sanitize final playlist name to fit into OS boundaries.
            path_playlist = scan_root / sanitize_filename(PLAYLIST_PREFIX + name_list + PLAYLIST_EXTENSION)
            path_playlist = pathlib.Path(path_file_sanitize(path_playlist, adapt=True))

            self.fn_logger.debug(f"Playlist: Creating {path_playlist}")

            # Collect all audio tracks under scan_root (recursive so disc
            # subdirectories are included when consolidating multi-disc albums).
            path_tracks: list[pathlib.Path] = []

            for extension_audio in AudioExtensionsValid:
                path_tracks = path_tracks + list(scan_root.rglob(f"*{extension_audio!s}"))

            # Exclude the playlist file itself if it has an audio extension (safety)
            path_tracks = [p for p in path_tracks if p != path_playlist]

            # Sort alphabetically, e.g. if items are prefixed with numbers or
            # placed in CD1/CD2 subdirs — alphabetic sort preserves disc order.
            if sort_alphabetically:
                path_tracks.sort()
            elif not is_album:
                # If it is not an album sort by creation time
                path_tracks.sort(
                    key=lambda x: x.stat().st_birthtime if hasattr(x.stat(), "st_birthtime") else x.stat().st_ctime
                )

            # Write data to m3u file
            with path_playlist.open(mode="w", encoding="utf-8") as f:
                for path_track in path_tracks:
                    # Write paths relative to the M3U directory so the playlist
                    # is portable.  Symlinks point to the canonical track file.
                    if path_track.is_symlink():
                        media_file_target = path_track.resolve().relative_to(path_playlist.parent, walk_up=True)
                    else:
                        media_file_target = path_track.relative_to(path_playlist.parent)

                    f.write(str(media_file_target) + os.linesep)

            result.append(path_playlist)

        return result

    def _video_convert(self, path_file: pathlib.Path) -> pathlib.Path:
        """Convert a TS video file to MP4 using ffmpeg.

        Args:
            path_file (pathlib.Path): Path to the TS file.

        Returns:
            pathlib.Path: Path to the converted MP4 file.
        """
        path_file_out: pathlib.Path = path_file.with_suffix(AudioExtensions.MP4)

        self.fn_logger.debug(f"Converting video: {path_file.name} -> {path_file_out.name}")

        ffmpeg = (
            FFmpeg(executable=self.settings.data.path_binary_ffmpeg)
            .option("y")
            .option("hide_banner")
            .option("nostdin")
            .input(url=path_file)
            .output(url=path_file_out, codec="copy", map=0, loglevel="quiet")
        )

        ffmpeg.execute()

        self.fn_logger.debug(f"Video conversion complete: {path_file_out.name}")

        return path_file_out

    def _extract_flac(self, path_media_src: pathlib.Path) -> pathlib.Path:
        """Extract FLAC audio from a media file using ffmpeg.

        Args:
            path_media_src (pathlib.Path): Path to the source media file.

        Returns:
            pathlib.Path: Path to the extracted FLAC file.
        """
        path_media_out = path_media_src.with_suffix(AudioExtensions.FLAC)

        ffmpeg = (
            FFmpeg(executable=self.settings.data.path_binary_ffmpeg)
            .option("hide_banner")
            .option("nostdin")
            .input(url=path_media_src)
            .output(
                url=path_media_out,
                map=0,
                movflags="use_metadata_tags",
                acodec="copy",
                map_metadata="0:g",
                loglevel="quiet",
            )
        )

        ffmpeg.execute()

        return path_media_out

    def _extract_video_stream(self, m3u8_variant: m3u8.M3U8, quality: int) -> tuple[m3u8.M3U8 | bool, str]:
        """Extract the best matching video stream from an m3u8 variant playlist.

        Args:
            m3u8_variant (m3u8.M3U8): The m3u8 variant playlist.
            quality (int): Desired video quality (vertical resolution).

        Returns:
            tuple[m3u8.M3U8 | bool, str]: (Selected m3u8 playlist or False, codecs string)
        """
        m3u8_playlist: m3u8.M3U8 | bool = False
        resolution_best: int = 0
        mime_type: str = ""

        if m3u8_variant.is_variant:
            for playlist in m3u8_variant.playlists:
                if resolution_best < playlist.stream_info.resolution[1]:
                    resolution_best = playlist.stream_info.resolution[1]
                    m3u8_playlist = m3u8.load(playlist.uri)
                    mime_type = playlist.stream_info.codecs

                    if quality == playlist.stream_info.resolution[1]:
                        break

        return m3u8_playlist, mime_type
