"""Atomic file writes and a cross-process exclusive lock."""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def atomic_write_text(path: str | Path, body: str, *, mode: int = 0o600) -> None:
    """Write ``body`` via temp file, fsync, rename, and directory fsync.

    The destination is never truncated in place. A crash between the temp
    write and ``os.replace`` leaves the original file untouched.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.tmp-{secrets.token_hex(8)}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(tmp, flags, mode)
    try:
        try:
            os.fchmod(fd, mode)
        except (OSError, AttributeError, NotImplementedError):
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
        _fsync_dir(dest.parent)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _fsync_dir(directory: Path) -> None:
    try:
        dir_flags = getattr(os, "O_DIRECTORY", 0)
        dir_fd = os.open(str(directory), os.O_RDONLY | dir_flags)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def token_lock_path(token_path: str | Path) -> Path:
    path = Path(token_path)
    return path.with_name(f"{path.name}.lock")


@contextmanager
def exclusive_file_lock(lock_path: str | Path) -> Iterator[None]:
    """Exclusive lock shared by CLI and sidecar processes."""
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as handle:
        try:
            _lock_exclusive(handle)
            yield
        finally:
            _unlock(handle)


def _lock_exclusive(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
