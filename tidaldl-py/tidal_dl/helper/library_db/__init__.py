"""SQLite-backed scan ledger for the music library."""

from tidal_dl.helper.library_db.browse import BrowseMixin
from tidal_dl.helper.library_db.core import LibraryDBCore, is_sqlite_lock_error
from tidal_dl.helper.library_db.utils import canonical_library_path, library_path_forms
from tidal_dl.helper.library_db.downloads import DownloadsMixin
from tidal_dl.helper.library_db.favorites import FavoritesMixin
from tidal_dl.helper.library_db.images import ImagesMixin
from tidal_dl.helper.library_db.meta import MetaMixin
from tidal_dl.helper.library_db.playback import PlaybackMixin
from tidal_dl.helper.library_db.probes import ProbesMixin
from tidal_dl.helper.library_db.scanned import ScannedMixin


class LibraryDB(
    BrowseMixin,
    DownloadsMixin,
    FavoritesMixin,
    ImagesMixin,
    MetaMixin,
    PlaybackMixin,
    ProbesMixin,
    ScannedMixin,
    LibraryDBCore,
):
    """Thin wrapper around a SQLite scan ledger."""


__all__ = ["LibraryDB", "canonical_library_path", "is_sqlite_lock_error", "library_path_forms"]
