"""Download files helpers."""

from tidal_dl.download._common import *  # noqa: F403
from tidal_dl.helper.path import resolve_library_relative


class FileMixin:
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
        file_name_relative = resolve_library_relative(self.path_base, file_name_relative)
        path_media_dst: pathlib.Path = (
            pathlib.Path(self.path_base).expanduser() / (file_name_relative + file_extension)
        ).absolute()
        path_media_dst = pathlib.Path(path_file_sanitize(path_media_dst, adapt=True))

        os.makedirs(win_long_path(path_media_dst).parent, exist_ok=True)

        # Move item and symlink it
        if path_media_dst != path_media_src:
            if self.skip_existing:
                skip_file = check_file_exists(path_media_dst, extension_ignore=False)
                skip_symlink = path_media_src.is_symlink()
            else:
                skip_file = False
                skip_symlink = False

            if not skip_file:
                self.fn_logger.debug(f"Move: {path_media_src} -> {path_media_dst}")
                shutil.move(path_media_src, win_long_path(path_media_dst))

            if not skip_symlink:
                self.fn_logger.debug(f"Symlink: {path_media_src} -> {path_media_dst}")
                path_media_dst_relative: pathlib.Path = path_media_dst.relative_to(path_media_src.parent, walk_up=True)

                path_media_src.unlink(missing_ok=True)
                path_media_src.symlink_to(path_media_dst_relative)

        return path_media_dst

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
            shutil.move(path_file_source, win_long_path(pathlib.Path(path_file_destination)))

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

    def lyrics_to_file(self, dir_destination: pathlib.Path, lyrics: str) -> pathlib.Path | None:
        """Write lyrics to a temporary file.

        Args:
            dir_destination (pathlib.Path): Directory for the temp file.
            lyrics (str): Lyrics content.

        Returns:
            pathlib.Path | None: Path to the temp file.
        """
        return self.write_to_tmp_file(dir_destination, mode="x", content=lyrics)

    def cover_to_file(self, dir_destination: pathlib.Path, image: bytes) -> pathlib.Path | None:
        """Write cover image to a temporary file.

        Args:
            dir_destination (pathlib.Path): Directory for the temp file.
            image (bytes): Image data.

        Returns:
            pathlib.Path | None: Path to the temp file.
        """
        return self.write_to_tmp_file(dir_destination, mode="xb", content=image)

    def write_to_tmp_file(self, dir_destination: pathlib.Path, mode: str, content: str | bytes) -> pathlib.Path | None:
        """Write content to a temporary file.

        Args:
            dir_destination (pathlib.Path): Directory for the temp file.
            mode (str): File open mode.
            content (str | bytes): Content to write.

        Returns:
            pathlib.Path | None: Path to the temp file.
        """
        result: pathlib.Path | None = dir_destination / str(uuid4())
        encoding: str | None = "utf-8" if isinstance(content, str) else None

        try:
            with open(result, mode=mode, encoding=encoding) as f:
                f.write(content)
        except OSError:
            result = None

        return result

    @staticmethod
    def cover_data(url: str | None = None, path_file: str | None = None) -> bytes:
        """Retrieve cover image data from a URL or file, with up to 3 retry attempts.

        Args:
            url (str | None, optional): URL to download image from. Defaults to None.
            path_file (str | None, optional): Path to image file. Defaults to None.

        Returns:
            bytes: Image data or empty bytes on failure.
        """
        result = b""

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
        self,
        track: Track,
        path_media: pathlib.Path,
        is_parent_album: bool,
        media_stream: Stream | None = None,
    ) -> tuple[bool, pathlib.Path | None, pathlib.Path | None]:
        """Write metadata, lyrics, and cover to a media file.

        Args:
            track (Track): Track object.
            path_media (pathlib.Path): Path to media file.
            is_parent_album (bool): Whether this is a parent album.
            media_stream (Stream | None): Stream object. May be None for Hi-Fi API downloads;
                replay gain fields use neutral defaults when unavailable.

        Returns:
            tuple[bool, pathlib.Path | None, pathlib.Path | None]: (Success, path to lyrics, path to cover)
        """
        result: bool = False
        path_lyrics: pathlib.Path | None = None
        path_cover: pathlib.Path | None = None
        album = track.album
        release_date: str = (
            album.available_release_date.strftime("%Y-%m-%d")
            if album and album.available_release_date
            else album.release_date.strftime("%Y-%m-%d")
            if album and album.release_date
            else ""
        )
        copy_right: str = track.copyright if hasattr(track, "copyright") and track.copyright else ""
        isrc: str = track.isrc if hasattr(track, "isrc") and track.isrc else ""
        lyrics: str = ""
        lyrics_synced: str = ""
        lyrics_unsynced: str = ""
        cover_bytes = b""

        if self.settings.data.lyrics_embed or self.settings.data.lyrics_file:
            from tidal_dl.gui.lyrics_tidal import lyrics_obj_from_track

            # Try to retrieve lyrics with up to 3 retries.
            for attempt in range(3):
                try:
                    lyrics_obj = lyrics_obj_from_track(track, session=getattr(self, "session", None))

                    if lyrics_obj and lyrics_obj.text:
                        lyrics_unsynced = lyrics_obj.text
                        lyrics = lyrics_unsynced
                    if lyrics_obj and lyrics_obj.subtitles:
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

        if album and (
            self.settings.data.metadata_cover_embed or (self.settings.data.cover_album_file and is_parent_album)
        ):
            # Do not write CoverDimensions.PxORIGIN to metadata, since it can exceed max metadata file size (>16Mb)
            url_cover = album.image(
                int(cover_dimension) if cover_dimension != CoverDimensions.PxORIGIN else int(CoverDimensions.Px1280)
            )
            cover_bytes = self.cover_data(url=url_cover)

        if cover_bytes and album and self.settings.data.cover_album_file and is_parent_album:
            if cover_dimension == CoverDimensions.PxORIGIN:
                url_cover_album_file = album.image(CoverDimensions.PxORIGIN)
                cover_data_album_file = self.cover_data(url=url_cover_album_file)
            else:
                cover_data_album_file = cover_bytes

            path_cover = self.cover_to_file(path_media.parent, cover_data_album_file)

        metadata_target_upc = MetadataTargetUPC(self.settings.data.metadata_target_upc)
        target_upc: dict[str, str] = METADATA_LOOKUP_UPC[metadata_target_upc]
        explicit: bool = track.explicit if hasattr(track, "explicit") else False
        title = name_builder_title(track)
        title += METADATA_EXPLICIT if explicit and self.settings.data.mark_explicit else ""

        albumartist = name_builder_album_artist(track, delimiter=self.settings.data.metadata_delimiter_album_artist)

        # `None` values are not allowed.
        m: Metadata = Metadata(
            path_file=path_media,
            target_upc=target_upc,
            lyrics=lyrics_synced,
            lyrics_unsynced=lyrics_unsynced,
            copy_right=copy_right,
            title=title,
            artists=name_builder_artist(track, delimiter=self.settings.data.metadata_delimiter_artist),
            album=album.name if album and album.name else "",
            tracknumber=track.track_num,
            date=release_date,
            isrc=isrc,
            albumartist=albumartist,
            totaltrack=album.num_tracks if album and album.num_tracks else 1,
            totaldisc=album.num_volumes if album and album.num_volumes else 1,
            discnumber=track.volume_num if track.volume_num else 1,
            cover_data=cover_bytes if self.settings.data.metadata_cover_embed else None,
            album_replay_gain=media_stream.album_replay_gain if media_stream else 1.0,
            album_peak_amplitude=media_stream.album_peak_amplitude if media_stream else 1.0,
            track_replay_gain=media_stream.track_replay_gain if media_stream else 1.0,
            track_peak_amplitude=media_stream.track_peak_amplitude if media_stream else 1.0,
            url_share=track.share_url if track.share_url and self.settings.data.metadata_write_url else "",
            replay_gain_write=self.settings.data.metadata_replay_gain,
            upc=album.upc if album and album.upc else "",
            explicit=explicit,
            bpm=track.bpm if track.bpm else 0,
            initial_key=format_initial_key(track.key, track.key_scale, self.settings.data.initial_key_format),
        )

        m.save()

        result = True

        return result, path_lyrics, path_cover
