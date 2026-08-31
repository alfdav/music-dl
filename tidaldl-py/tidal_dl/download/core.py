"""Download core helpers."""

import threading

from tidal_dl.download._common import *  # noqa: F403


class DownloadCore:
    def __init__(
        self,
        tidal_obj: Tidal,  # Required for Atmos session context manager
        path_base: str,
        fn_logger: LoggerLike,
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
        self.progress = progress or Progress()
        self.progress_overall = progress_overall or Progress()
        self.path_base = path_base
        self.event_abort = event_abort or Event()
        self.event_run = event_run or Event()
        self.event_run.set()
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

        self._library_db_path = pathlib.Path(path_config_base()) / "library.db"
        self._library_db_local = threading.local()
        self._library_db = self._library_db_for_current_thread()
        self._library_db.import_legacy_isrc_index(pathlib.Path(path_config_base()) / "isrc_index.json")
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

    def _library_db_for_current_thread(self) -> LibraryDB:
        """Return this downloader's SQLite connection for the calling thread."""
        db = getattr(self._library_db_local, "db", None)
        if db is None:
            db = LibraryDB(self._library_db_path)
            db.open()
            self._library_db_local.db = db
        return db

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

    def extension_guess(self, quality_audio: Quality, metadata_tags: list[str], is_video: bool) -> str:
        """Guess the file extension for a media item based on quality and type.

        Args:
            quality_audio (Quality): Audio quality.
            metadata_tags (list[str]): Metadata tags for the media.
            is_video (bool): Whether the media is a video.

        Returns:
            str: Guessed file extension.
        """
        result: str

        if is_video:
            result = str(AudioExtensions.MP4 if self.settings.data.video_convert_mp4 else VideoExtensions.TS)
        elif quality_audio in (Quality.low_96k, Quality.low_320k):
            result = str(AudioExtensions.M4A)
        else:
            # Lossless settings (and any non-LOW/HIGH guess) write FLAC, not M4A.
            result = str(AudioExtensions.FLAC)

        return result

    def adjust_quality_audio(self, quality: Quality) -> Quality:
        """Temporarily set audio quality and return the previous value.

        Args:
            quality (Quality): New audio quality.

        Returns:
            Quality: Previous audio quality.
        """
        # Save original quality settings
        quality_old = cast(Quality, self.session.audio_quality)
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

    def _run_ffmpeg(self, *args: str) -> None:
        from tidal_dl.download_ffmpeg import run_ffmpeg

        run_ffmpeg(self.settings.data.path_binary_ffmpeg, *args)

    def _video_convert(self, path_file: pathlib.Path) -> pathlib.Path:
        """Convert a TS video file to MP4 using ffmpeg."""
        from tidal_dl.download_ffmpeg import video_convert

        path_file_out = path_file.with_suffix(AudioExtensions.MP4)
        self.fn_logger.debug(f"Converting video: {path_file.name} -> {path_file_out.name}")
        result = video_convert(self.settings.data.path_binary_ffmpeg, path_file)
        self.fn_logger.debug(f"Video conversion complete: {result.name}")
        return result

    def _extract_flac(self, path_media_src: pathlib.Path) -> pathlib.Path:
        """Extract FLAC audio from a media file using ffmpeg."""
        from tidal_dl.download_ffmpeg import extract_flac

        return extract_flac(self.settings.data.path_binary_ffmpeg, path_media_src)

    def _extract_video_stream(self, m3u8_variant: m3u8.M3U8, quality: int) -> tuple[m3u8.M3U8 | None, str]:
        """Extract the best matching video stream from an m3u8 variant playlist.

        Args:
            m3u8_variant (m3u8.M3U8): The m3u8 variant playlist.
            quality (int): Desired video quality (vertical resolution).

        Returns:
            tuple[m3u8.M3U8 | None, str]: (Selected m3u8 playlist or None, codecs string)
        """
        m3u8_playlist: m3u8.M3U8 | None = None
        resolution_best: int = 0
        mime_type: str = ""

        if m3u8_variant.is_variant:
            for playlist in m3u8_variant.playlists:
                resolution = playlist.stream_info.resolution
                uri = playlist.uri
                codecs = playlist.stream_info.codecs
                if resolution is None or uri is None or codecs is None:
                    continue

                if resolution_best < resolution[1]:
                    resolution_best = resolution[1]
                    m3u8_playlist = m3u8.load(uri)
                    mime_type = codecs

                    if quality == resolution[1]:
                        break

        return m3u8_playlist, mime_type
