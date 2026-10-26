"""Post-download library registration."""

from __future__ import annotations

import logging
import pathlib

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.library_db.utils import sqlite_int64
from tidal_dl.helper.path import path_config_base

logger = logging.getLogger("music-dl.download.registry")


def register_downloaded_track(file_path: pathlib.Path | str) -> None:
    """Register a newly downloaded track in the library DB."""
    try:
        from tidal_dl.gui.api.library import _read_metadata

        fp = pathlib.Path(file_path) if not isinstance(file_path, pathlib.Path) else file_path
        if not fp.is_file():
            return

        meta = _read_metadata(fp)
        if not meta:
            return
        try:
            st = fp.stat()
            identity = {
                "file_size": st.st_size,
                "file_mtime": int(st.st_mtime),
                "file_inode": sqlite_int64(st.st_ino),
                "file_device": sqlite_int64(st.st_dev),
            }
        except (OSError, OverflowError, ValueError):
            identity = {}

        db = LibraryDB(pathlib.Path(path_config_base()) / "library.db")
        db.open()
        try:
            db.record(
                str(fp),
                status="tagged" if meta["isrc"] else "needs_isrc",
                isrc=meta["isrc"] or None,
                artist=meta["artist"],
                title=meta["name"],
                album=meta["album"],
                album_artist=meta.get("album_artist"),
                release_date=meta.get("release_date"),
                track_number=meta.get("track_number"),
                track_total=meta.get("track_total"),
                disc_number=meta.get("disc_number"),
                disc_total=meta.get("disc_total"),
                musicbrainz_release_id=meta.get("musicbrainz_release_id"),
                musicbrainz_release_group_id=meta.get("musicbrainz_release_group_id"),
                provider_namespace=meta.get("provider_namespace"),
                provider_album_id=meta.get("provider_album_id"),
                barcode=meta.get("barcode"),
                duration=meta["duration"],
                genre=meta.get("genre"),
                quality=meta["quality"],
                fmt=meta["format"],
                codec=meta["codec"],
                metadata_complete=True,
                **identity,
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("Could not register downloaded track", exc_info=True)
