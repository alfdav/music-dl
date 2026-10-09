"""Plex token lookup. The value is never a Settings field and is never logged.

Resolution order:

1. ``MUSIC_DL_PLEX_TOKEN``
2. On macOS, the login keychain item ``music-dl-plex-token``
3. A private ``plex_token`` file in the music-dl config directory

On macOS the user can store the token in the login keychain instead of the
file. The command prompts, so the value is not on the command line::

    security add-generic-password -s music-dl-plex-token -a music-dl -w
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_ENV_NAME = "MUSIC_DL_PLEX_TOKEN"
_KEYCHAIN_SERVICE = "music-dl-plex-token"
_KEYCHAIN_TIMEOUT_SEC = 5


class PlexToken:
    """Holds a Plex token. ``str`` and ``repr`` never reveal it."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "PlexToken(***)"

    def __str__(self) -> str:
        return "PlexToken(***)"


def plex_token_path() -> Path:
    from tidal_dl.helper.path import path_config_base

    return Path(path_config_base()) / "plex_token"


def resolve_plex_token(
    env_getter: Callable[..., str] | None = None,
    keychain_reader: Callable[[], str | None] | None = None,
    path_resolver: Callable[[], Path | str] | None = None,
    platform: str | None = None,
) -> PlexToken | None:
    """Return the first configured token, or None when every source is empty."""
    getter = env_getter or os.environ.get
    from_env = _clean(_call_env(getter, _ENV_NAME))
    if from_env:
        return PlexToken(from_env)

    system = sys.platform if platform is None else platform
    if system == "darwin":
        reader = keychain_reader or _read_login_keychain
        try:
            from_keychain = _clean(reader())
        except Exception:  # noqa: BLE001 — a keychain failure is "no token", and its output stays unread
            from_keychain = ""
        if from_keychain:
            return PlexToken(from_keychain)

    path = Path(path_resolver()) if path_resolver is not None else plex_token_path()
    try:
        from_file = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not from_file:
        return None
    return PlexToken(from_file)


def save_plex_token_file(token: str, path: Path | str | None = None) -> Path:
    """Write ``token`` to a private file (mode 0600) and return that path.

    On macOS the user can instead store it in the login keychain. The command
    prompts, so the value is not on the command line::

        security add-generic-password -s music-dl-plex-token -a music-dl -w
    """
    target = Path(path) if path is not None else plex_token_path()
    _write_private_file_atomic(target, token.strip() + "\n")
    return target


def _call_env(getter: Callable[..., str], key: str) -> object:
    try:
        return getter(key, "")
    except TypeError:
        return getter(key)


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def _read_login_keychain() -> str | None:
    """Read the login keychain item. Failures become None. Output is not logged."""
    try:
        completed = subprocess.run(
            ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            shell=False,
            timeout=_KEYCHAIN_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return _clean(completed.stdout) or None


def _write_private_file_atomic(path: Path, body: str) -> None:
    """Mirror the bot shared-token writer: exclusive create, then mode 0600."""
    import secrets

    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{secrets.token_hex(8)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
