"""Download collections helpers."""

from tidal_dl.download._common import *  # noqa: F403

class CollectionMixin:
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
            download_delay (bool, optional): Whether to pace Tidal API/auth calls. Defaults to True.
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
                        f"Resuming '{list_media_name}': {already_done} track(s) already downloaded, skipping."
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
        # Collections (albums, playlists, mixes) are always completed in full.
        resolved_actions: dict[str, str] = self._preflight_isrc_scan(items, checkpoint, ensure_complete=True)

        # Set up progress tracking
        progress: Progress = self.progress_overall if self.progress_overall else self.progress
        progress_task: TaskID = progress.add_task(
            f"[green]List '{list_media_name_short}'", total=len(items), visible=progress_stdout
        )

        # Download configuration
        is_album: bool = isinstance(media, Album)
        is_playlist: bool = isinstance(media, Playlist | UserPlaylist)
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

        # Create playlist file: always for playlists (helps music players recognize the
        # folder), or when explicitly requested via the playlist_create setting.
        if is_playlist or self.settings.data.playlist_create:
            self.playlist_populate(set(result_dirs), list_media_name, is_album, sort_by_track_num)

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
        Console().print(
            Panel(
                "\n".join(summary_lines),
                title=f"[bold cyan]{list_media_name[:50]}[/bold cyan]",
                border_style="cyan",
                expand=False,
            )
        )

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
                        STATUS_DOWNLOADED
                        if outcome in (DownloadOutcome.DOWNLOADED, DownloadOutcome.COPIED, DownloadOutcome.SKIPPED)
                        else STATUS_FAILED
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
        """Create playlist files for downloaded tracks in each directory.

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
            path_playlist = scan_root / _sanitize_name(PLAYLIST_PREFIX + name_list + PLAYLIST_EXTENSION)
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

            # Write UTF-8 playlist data once all track paths are finalized.
            with path_playlist.open(mode="w", encoding="utf-8") as f:
                f.write("#EXTM3U" + os.linesep)
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
