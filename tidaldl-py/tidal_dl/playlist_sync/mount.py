"""Download directory must already be a writable mount. Never create it."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from tidal_dl.playlist_sync.unicode_norm import nfc_path

StatFn = Callable[[str], os.stat_result]
AccessFn = Callable[[str, int], bool]
MountFn = Callable[[str], bool]


def download_path_available(
    path: str,
    *,
    ismount: MountFn | None = None,
    stat: StatFn | None = None,
    access: AccessFn | None = None,
    platform: str | None = None,
) -> bool:
    """True when *path* exists, is writable, and is a mount or macOS network volume.

    Does not create the directory.
    """
    target = nfc_path(os.path.expanduser(path or ""))
    if not target or not os.path.isdir(target):
        return False
    if not (access or os.access)(target, os.W_OK):
        return False
    if (ismount or os.path.ismount)(target):
        return True
    if (platform or sys.platform) != "darwin":
        return False
    stat_fn = stat or os.stat
    try:
        return stat_fn(target).st_dev != stat_fn("/").st_dev
    except OSError:
        return False
