"""Download items helpers."""

from tidal_dl.download._common import *  # noqa: F403
from tidal_dl.download.registry import register_downloaded_track
from tidal_dl.helper.path import resolve_library_relative


class ItemMixin:
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
            src_path_str = self._library_db_for_current_thread().primary_path_for_isrc(isrc) if isrc else None
            if src_path_str and pathlib.Path(src_path_str).is_file():
                src_ext = pathlib.Path(src_path_str).suffix
                path_copy_dst = path_media_dst.with_suffix(src_ext)
                # Check the canonical path (without uniquify suffix like _01)
                # since uniquify may have renamed the destination to avoid an
                # existing file — which is exactly the file we want to detect.
                canonical = re.sub(r"_\d{2}$", "", path_copy_dst.stem)
                path_canonical = path_copy_dst.parent / (canonical + path_copy_dst.suffix)
                if win_long_path(path_canonical).is_file() or win_long_path(path_copy_dst).is_file():
                    return DownloadOutcome.SKIPPED, path_canonical
                win_long_path(path_copy_dst).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path_str, win_long_path(path_copy_dst))
                self.fn_logger.info(f"Copied '{name_builder_item(media)}' from '{src_path_str}'.")
                register_downloaded_track(path_copy_dst)
                return DownloadOutcome.COPIED, path_copy_dst
            else:
                # Source gone — fall through to normal download
                self.fn_logger.warning(f"Copy source missing for '{name_builder_item(media)}'; re-downloading.")
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
        download_success, path_media_dst = self._download_and_process_media(
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
                self._library_db_for_current_thread().register_isrc_path(isrc, path_media_dst, commit=True)
            self._on_successful_track()
            register_downloaded_track(path_media_dst)

        return outcome, path_media_dst

    def _validate_and_prepare_media(
        self,
        media: Track | Video | Album | Playlist | UserPlaylist | Mix | Artist | None,
        media_id: str | None,
        media_type: MediaType | None,
        video_download: bool = True,
    ) -> Track | Video | Album | Playlist | UserPlaylist | Mix | Artist | None:
        """Validate and prepare media instance for download.

        Args:
            media (Track | Video | Album | Playlist | UserPlaylist | Mix | None): Media instance.
            media_id (str | None): Media ID if creating new instance.
            media_type (MediaType | None): Media type if creating new instance.
            video_download (bool, optional): Whether video downloads are allowed. Defaults to True.

        Returns:
            Track | Video | Album | Playlist | UserPlaylist | Mix | Artist | None: Prepared media instance or None if invalid.
        """
        try:
            if media_id and media_type:
                # If no media instance is provided, we need to create the media instance.
                # Throws `tidalapi.exceptions.ObjectNotFound` if item is not available anymore.
                prefer_hifi = self.tidal.active_source == DownloadSource.HIFI_API and self.tidal.hifi_client is not None
                oauth_fallback = bool(getattr(self.settings.data, "download_source_fallback", True))
                media = instantiate_media(
                    session=self.session,
                    media_type=media_type,
                    id_media=media_id,
                    cache=self._api_cache,
                    hifi_client=self.tidal.hifi_client,
                    prefer_hifi=prefer_hifi,
                    oauth_fallback=oauth_fallback,
                )
            elif isinstance(media, Track | Video):
                # Check if media is available not deactivated / removed from TIDAL.
                if not media.allow_streaming:
                    self.fn_logger.info(
                        f"This item is not available for listening anymore on TIDAL. Skipping: {name_builder_item(media)}"
                    )
                    return None
                elif isinstance(media, Track):
                    # Re-create media instance with full album information.
                    # Skip the OAuth re-fetch when the track was resolved via
                    # Hi-Fi (marker attribute) OR the active source is Hi-Fi
                    # and the track already carries album data.
                    is_hifi_resolved = bool(getattr(media, "_resolved_via_hifi", False))
                    has_album_from_hifi = (
                        self.tidal.active_source == DownloadSource.HIFI_API
                        and self.tidal.hifi_client is not None
                        and getattr(media, "album", None) is not None
                    )
                    if not (is_hifi_resolved or has_album_from_hifi):
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
            cast(Quality, quality_for_extension),
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
        file_name_relative = resolve_library_relative(self.path_base, file_name_relative)

        path_media_dst: pathlib.Path = (
            pathlib.Path(self.path_base).expanduser() / (file_name_relative + file_extension_dummy)
        ).absolute()

        # Sanitize final path_file to fit into OS boundaries.
        # Do not uniquify yet: the real container extension is not known until
        # stream info is fetched, and pre-baking _01 here breaks skip_existing.
        path_media_dst = pathlib.Path(path_file_sanitize(path_media_dst, adapt=True))

        # Compute if and how downloads need to be skipped.
        skip_download: bool = False

        if self.skip_existing:
            skip_file = check_file_exists(path_media_dst, extension_ignore=False)

            if self.settings.data.symlink_to_track and not isinstance(media, Video):
                # Compute symlink tracks path, sanitize and check if file exists
                file_name_track_dir_relative: str = format_path_media(
                    self.settings.data.format_track,
                    media,
                    delimiter_artist=self.settings.data.filename_delimiter_artist,
                    delimiter_album_artist=self.settings.data.filename_delimiter_album_artist,
                    use_primary_album_artist=self.settings.data.use_primary_album_artist,
                )
                file_name_track_dir_relative = resolve_library_relative(self.path_base, file_name_track_dir_relative)
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
            skip_file = False

        # ISRC-based cross-context dedup: skip if the same recording was already
        # downloaded to *any* path (independent of skip_existing path check).
        # bypass_isrc=True is set for redownload overrides decided in pre-flight.
        if not bypass_isrc and not skip_file and self.settings.data.skip_duplicate_isrc and isinstance(media, Track):
            media_isrc = getattr(media, "isrc", None)
            if media_isrc and self._library_db_for_current_thread().has_live_isrc(media_isrc):
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
    ) -> tuple[bool, pathlib.Path]:
        """Download and process media file.

        Args:
            media (Track | Video): Media item.
            path_media_dst (pathlib.Path): Destination file path.
            skip_download (bool): Whether to skip download.
            is_parent_album (bool): Whether this is a parent album.
            file_extension_dummy (str): Dummy file extension.
            event_stop (Event | None, optional): Event to stop the download. Defaults to None.

        Returns:
            tuple[bool, pathlib.Path]: Whether download was successful and the final output path.
        """
        if skip_download:
            return True, path_media_dst

        # Get stream information and final file extension
        stream_manifest, file_extension, do_flac_extract, media_stream = self._get_stream_info(media)

        if stream_manifest is None and isinstance(media, Track):
            return False, path_media_dst

        # Resolve the final path only after the real stream extension is known.
        if path_media_dst.suffix != file_extension:
            path_media_dst = path_media_dst.with_suffix(file_extension)
        path_media_dst = pathlib.Path(path_file_sanitize(path_media_dst, adapt=True, uniquify=True))

        os.makedirs(win_long_path(path_media_dst).parent, exist_ok=True)

        # Perform actual download
        result_download = self._perform_actual_download(
            media,
            path_media_dst,
            stream_manifest,
            do_flac_extract,
            is_parent_album,
            media_stream,
            event_stop,
        )

        if isinstance(result_download, tuple):
            return result_download

        return result_download, path_media_dst

    def _perform_actual_download(
        self,
        media: Track | Video,
        path_media_dst: pathlib.Path,
        stream_manifest: StreamManifest | HiFiStreamManifest | None,
        do_flac_extract: bool,
        is_parent_album: bool,
        media_stream: Stream | None,
        event_stop: Event | None = None,
    ) -> tuple[bool, pathlib.Path]:
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
            tuple[bool, pathlib.Path]: Whether download succeeded and the final destination path.
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
                return False, path_media_dst

            # Convert video from TS to MP4
            if isinstance(media, Video) and self.settings.data.video_convert_mp4:
                tmp_path_file = self._video_convert(tmp_path_file)

            # Native FLAC when the stream is FLAC, even if Tidal boxed it in MP4.
            # Empty codec + dest .m4a still extracts when the box itself contains FLAC.
            if isinstance(media, Track):
                codecs = getattr(stream_manifest, "codecs", "") if stream_manifest is not None else ""
                boxed_flac = self._flac_stream_in_mp4_container(tmp_path_file, codecs, path_media_dst.suffix)
                if boxed_flac or (self.settings.data.extract_flac and do_flac_extract):
                    if not self.settings.data.extract_flac:
                        self.fn_logger.error(
                            "FLAC is boxed in MP4 but extract_flac is off (FFmpeg missing?). "
                            "Refusing to write a lying .flac or keep .m4a."
                        )
                        return False, path_media_dst
                    try:
                        tmp_path_file = self._extract_flac(tmp_path_file)
                    except Exception:
                        self.fn_logger.exception(
                            "FFmpeg failed to extract FLAC from an MP4 box. Failing closed."
                        )
                        return False, path_media_dst
                    path_media_dst = pathlib.Path(
                        path_file_sanitize(path_media_dst.with_suffix(AudioExtensions.FLAC), adapt=True, uniquify=True)
                    )
                    os.makedirs(win_long_path(path_media_dst).parent, exist_ok=True)

            if isinstance(media, Track):
                codecs = getattr(stream_manifest, "codecs", "") if stream_manifest is not None else ""
                detected_extension = self._detect_downloaded_audio_extension(
                    tmp_path_file, path_media_dst.suffix, codecs=codecs
                )
                if detected_extension != path_media_dst.suffix:
                    path_media_dst = pathlib.Path(
                        path_file_sanitize(path_media_dst.with_suffix(detected_extension), adapt=True, uniquify=True)
                    )
                    os.makedirs(win_long_path(path_media_dst).parent, exist_ok=True)

            # Handle metadata, lyrics, and cover
            self._handle_metadata_and_extras(media, tmp_path_file, path_media_dst, is_parent_album, media_stream)

            self.fn_logger.info(f"Downloaded item '{name_builder_item(media)}'.")

            # Move final file to the configured destination directory.
            shutil.move(tmp_path_file, win_long_path(path_media_dst))

            return True, path_media_dst

    def _flac_stream_in_mp4_container(
        self, path_media_src: pathlib.Path, codecs: str, current_extension: str
    ) -> bool:
        """True when a FLAC stream was written into an MP4/M4A box.

        Codec and planned `.flac` dest are enough. Empty codec + dest `.m4a`
        (DASH / audio/mp4 mime) still matches when the box itself has fLaC/dfLa.
        """
        from tidal_dl.download.streams import is_flac_codec, mp4_box_contains_flac

        try:
            header = path_media_src.read_bytes()[:16]
        except OSError:
            return False
        if len(header) < 8 or header[4:8] != b"ftyp":
            return False
        return (
            is_flac_codec(codecs)
            or current_extension == str(AudioExtensions.FLAC)
            or mp4_box_contains_flac(path_media_src)
        )

    def _detect_downloaded_audio_extension(
        self, path_media_src: pathlib.Path, current_extension: str, codecs: str = ""
    ) -> str:
        """Infer the output extension from codec + file header.

        Keep `.m4a` only when Tidal actually sent AAC/lossy. Boxed FLAC
        (codec, planned `.flac` dest, or fLaC/dfLa in the box) stays `.flac`.
        Extract or fail closed — do not rename boxed FLAC to `.m4a`.
        """
        from tidal_dl.download.streams import is_flac_codec, mp4_box_contains_flac

        try:
            header = path_media_src.read_bytes()[:16]
        except OSError:
            return str(AudioExtensions.FLAC) if is_flac_codec(codecs) else current_extension

        if header.startswith(b"fLaC"):
            return str(AudioExtensions.FLAC)

        boxed_flac = (
            is_flac_codec(codecs)
            or current_extension == str(AudioExtensions.FLAC)
            or mp4_box_contains_flac(path_media_src)
        )
        if boxed_flac:
            return str(AudioExtensions.FLAC)

        if len(header) >= 8 and header[4:8] == b"ftyp":
            return str(AudioExtensions.M4A)

        return current_extension

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

        # Write metadata to file.  media_stream may be None for Hi-Fi API
        # downloads; metadata_write handles this gracefully.
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
                random.SystemRandom().uniform(self._adaptive_delay_sec_min, self._adaptive_delay_sec_max),
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
