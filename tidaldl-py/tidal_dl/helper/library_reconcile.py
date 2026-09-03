"""Incremental library path reconciler.

Detects folder moves from directory signatures and migrates scanned-row
identity (play counts, favorites, play_events) instead of delete+insert.

Planning is pure: ``plan_path_reconcile`` never touches the filesystem.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from tidal_dl.helper.library_scanner import is_skipped_scan_dir, path_has_skipped_scan_dir

AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
DURATION_TOLERANCE_SEC = 2
RECONCILE_MIN_INTERVAL_SEC = 60

_EDITION_WORDS = frozenset({
    "remaster",
    "remastered",
    "live",
    "acoustic",
    "mono",
    "stereo",
    "deluxe",
    "instrumental",
})
_EDITION_PHRASES = frozenset({
    ("single", "edit"),
    ("radio", "edit"),
})
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_compare_text(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold().strip()


def normalize_basename(path: str) -> str:
    name = Path(path.replace("\\", "/")).name
    stem = Path(name).stem
    return normalize_compare_text(stem)


def canon_path(path: str | Path) -> str:
    raw = unicodedata.normalize("NFKC", os.fspath(path))
    return os.path.normcase(os.path.normpath(raw))


def inode_usable(inode: int | None, device: int | None) -> bool:
    return inode not in (None, 0) and device is not None


def directory_signature(mtime_ns: int, audio_count: int) -> str:
    return f"{mtime_ns}:{audio_count}"


def edition_tokens(*texts: str | None) -> frozenset[str]:
    tokens: set[str] = set()
    for text in texts:
        cleaned = _NON_WORD.sub(" ", normalize_compare_text(text))
        words = cleaned.split()
        for word in words:
            if word in {"remaster", "remastered"}:
                tokens.add("remaster")
            elif word in _EDITION_WORDS:
                tokens.add(word)
        for left, right in pairwise(words):
            if (left, right) in _EDITION_PHRASES:
                tokens.add(f"{left} {right}")
        tokens.update(_YEAR_RE.findall(cleaned))
    return frozenset(tokens)


def editions_compatible(left: FileIdentity, right: FileIdentity) -> bool:
    return edition_tokens(
        left.title, left.album, left.basename or left.path,
    ) == edition_tokens(
        right.title, right.album, right.basename or right.path,
    )


def _duration_equal(left: int | None, right: int | None, *, tolerance: int = 0) -> bool:
    if left is None or right is None:
        return False
    return abs(int(left) - int(right)) <= tolerance


@dataclass(frozen=True)
class FileIdentity:
    path: str
    size: int | None = None
    mtime: int | None = None
    inode: int | None = None
    device: int | None = None
    duration: int | None = None
    codec: str | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    isrc: str | None = None
    basename: str = ""

    def __post_init__(self) -> None:
        if not self.basename:
            object.__setattr__(self, "basename", normalize_basename(self.path))


@dataclass
class PathReconcilePlan:
    migrations: list[tuple[str, str]] = field(default_factory=list)
    mark_missing: list[str] = field(default_factory=list)
    index_new: list[str] = field(default_factory=list)


@dataclass
class PathReconcileResult:
    unchanged: bool = False
    migrations: list[tuple[str, str]] = field(default_factory=list)
    marked_missing: list[str] = field(default_factory=list)
    indexed: list[str] = field(default_factory=list)
    skipped_dirs: list[str] = field(default_factory=list)
    cleared_missing: list[str] = field(default_factory=list)


@dataclass
class _DirInfo:
    path: str
    signature: str
    audio_names: tuple[str, ...]


def _row_identity(row: dict) -> FileIdentity:
    return FileIdentity(
        path=row["path"],
        size=row.get("file_size"),
        mtime=row.get("file_mtime"),
        inode=row.get("file_inode"),
        device=row.get("file_device"),
        duration=row.get("duration"),
        codec=row.get("codec"),
        title=row.get("title"),
        artist=row.get("artist"),
        album=row.get("album"),
        isrc=row.get("isrc"),
    )


def _unique_pairs(
    vanished: Sequence[FileIdentity],
    appeared: Sequence[FileIdentity],
    matches: Callable[[FileIdentity, FileIdentity], bool],
) -> list[tuple[FileIdentity, FileIdentity]]:
    v_hits: dict[str, list[FileIdentity]] = {}
    a_hits: dict[str, list[FileIdentity]] = {}
    for vanished_row in vanished:
        v_hits[vanished_row.path] = [item for item in appeared if matches(vanished_row, item)]
    for appeared_file in appeared:
        a_hits[appeared_file.path] = [item for item in vanished if matches(item, appeared_file)]

    pairs: list[tuple[FileIdentity, FileIdentity]] = []
    for vanished_row in vanished:
        hits = v_hits[vanished_row.path]
        if len(hits) != 1:
            continue
        candidate = hits[0]
        if len(a_hits[candidate.path]) != 1:
            continue
        if a_hits[candidate.path][0].path != vanished_row.path:
            continue
        pairs.append((vanished_row, candidate))
    return pairs


def _match_inode(vanished: FileIdentity, appeared: FileIdentity) -> bool:
    if not inode_usable(vanished.inode, vanished.device):
        return False
    if not inode_usable(appeared.inode, appeared.device):
        return False
    if vanished.size is None or appeared.size is None:
        return False
    return (
        vanished.device == appeared.device
        and vanished.inode == appeared.inode
        and vanished.size == appeared.size
    )


def _match_tags(vanished: FileIdentity, appeared: FileIdentity) -> bool:
    if vanished.size is None or appeared.size is None:
        return False
    if vanished.size != appeared.size:
        return False
    if not _duration_equal(vanished.duration, appeared.duration):
        return False
    if normalize_compare_text(vanished.codec) != normalize_compare_text(appeared.codec):
        return False
    if normalize_compare_text(vanished.title) != normalize_compare_text(appeared.title):
        return False
    if normalize_compare_text(vanished.artist) != normalize_compare_text(appeared.artist):
        return False
    if normalize_compare_text(vanished.album) != normalize_compare_text(appeared.album):
        return False
    return editions_compatible(vanished, appeared)


def _match_basename(vanished: FileIdentity, appeared: FileIdentity) -> bool:
    if vanished.size is None or appeared.size is None:
        return False
    if vanished.size != appeared.size:
        return False
    if not _duration_equal(vanished.duration, appeared.duration):
        return False
    if vanished.basename != appeared.basename:
        return False
    return editions_compatible(vanished, appeared)


def _match_legacy(vanished: FileIdentity, appeared: FileIdentity) -> bool:
    if vanished.size is not None or vanished.inode not in (None, 0):
        return False
    if not _duration_equal(vanished.duration, appeared.duration, tolerance=DURATION_TOLERANCE_SEC):
        return False
    if normalize_compare_text(vanished.title) != normalize_compare_text(appeared.title):
        return False
    if normalize_compare_text(vanished.artist) != normalize_compare_text(appeared.artist):
        return False
    if normalize_compare_text(vanished.album) != normalize_compare_text(appeared.album):
        return False
    if vanished.basename != appeared.basename:
        return False
    return editions_compatible(vanished, appeared)


def plan_path_reconcile(
    vanished: Sequence[FileIdentity],
    appeared: Sequence[FileIdentity],
) -> PathReconcilePlan:
    """Match vanished rows to appeared files. Ambiguity is never guessed."""
    pending_v = list(vanished)
    pending_a = list(appeared)
    migrations: list[tuple[str, str]] = []

    for matcher in (_match_inode, _match_tags, _match_basename, _match_legacy):
        if not pending_v or not pending_a:
            break
        pairs = _unique_pairs(pending_v, pending_a, matcher)
        used_v = {left.path for left, _right in pairs}
        used_a = {right.path for _left, right in pairs}
        migrations.extend((left.path, right.path) for left, right in pairs)
        pending_v = [row for row in pending_v if row.path not in used_v]
        pending_a = [row for row in pending_a if row.path not in used_a]

    return PathReconcilePlan(
        migrations=migrations,
        mark_missing=[row.path for row in pending_v],
        index_new=[row.path for row in pending_a],
    )


def _is_under(path: str, prefixes: Iterable[str]) -> bool:
    candidate = Path(canon_path(path))
    for prefix in prefixes:
        root = Path(canon_path(prefix))
        try:
            if candidate == root or candidate.is_relative_to(root):
                return True
        except (ValueError, OSError):
            continue
    return False


def _under_configured_roots(path: str, roots: Sequence[Path]) -> bool:
    return _is_under(path, (str(root) for root in roots))


class PathReconciler:
    """Walk directory signatures, plan identity migrations, and apply them."""

    def __init__(
        self,
        db,
        roots: Sequence[Path],
        *,
        read_metadata: Callable[[Path], dict | None],
        stat_fn: Callable[..., os.stat_result] = os.stat,
        scandir_fn=os.scandir,
        now_fn: Callable[[], int] | None = None,
        index_file: Callable[[Path, FileIdentity, dict | None], None] | None = None,
    ) -> None:
        self.db = db
        self.roots = [Path(root) for root in roots]
        self.read_metadata = read_metadata
        self.stat_fn = stat_fn
        self.scandir_fn = scandir_fn
        self.now_fn = now_fn or (lambda: int(time.time()))
        self.index_file = index_file
        self.metadata_reads: list[str] = []

    def _stat(self, path: str | Path):
        return self.stat_fn(os.fspath(path))

    def walk_dirs(self) -> tuple[dict[str, _DirInfo], set[str]]:
        current: dict[str, _DirInfo] = {}
        unreadable: set[str] = set()
        for root in self.roots:
            stack = [canon_path(root)]
            seen: set[str] = set()
            while stack:
                directory = stack.pop()
                if directory in seen:
                    continue
                seen.add(directory)
                try:
                    st = self._stat(directory)
                except OSError:
                    unreadable.add(directory)
                    continue
                audio_names: list[str] = []
                try:
                    with self.scandir_fn(directory) as iterator:
                        for entry in iterator:
                            if path_has_skipped_scan_dir(Path(entry.path) / "x"):
                                continue
                            try:
                                if entry.is_symlink():
                                    continue
                                if entry.is_dir(follow_symlinks=False):
                                    if not is_skipped_scan_dir(entry.name):
                                        stack.append(canon_path(entry.path))
                                elif (
                                    entry.is_file(follow_symlinks=False)
                                    and Path(entry.name).suffix.lower() in AUDIO_EXTENSIONS
                                ):
                                    audio_names.append(entry.name)
                            except OSError:
                                continue
                except OSError:
                    unreadable.add(directory)
                    continue
                current[directory] = _DirInfo(
                    path=directory,
                    signature=directory_signature(st.st_mtime_ns, len(audio_names)),
                    audio_names=tuple(sorted(audio_names)),
                )
        return current, unreadable

    def _file_identity(self, path: Path, *, read_tags: bool) -> tuple[FileIdentity, dict | None] | None:
        try:
            st = self._stat(path)
        except OSError:
            return None
        meta = None
        if read_tags:
            self.metadata_reads.append(str(path))
            meta = self.read_metadata(path)
        return FileIdentity(
            path=str(path),
            size=st.st_size,
            mtime=int(st.st_mtime),
            inode=st.st_ino,
            device=st.st_dev,
            duration=None if meta is None else meta.get("duration"),
            codec=None if meta is None else meta.get("codec"),
            title=None if meta is None else (meta.get("name") or meta.get("title")),
            artist=None if meta is None else meta.get("artist"),
            album=None if meta is None else meta.get("album"),
            isrc=None if meta is None else meta.get("isrc"),
        ), meta

    def _index_appeared(self, path: Path, identity: FileIdentity, meta: dict | None) -> None:
        if self.index_file is not None:
            self.index_file(path, identity, meta)
            return
        payload = meta or {}
        self.db.record(
            str(path),
            status="tagged" if payload.get("isrc") else "needs_isrc",
            isrc=payload.get("isrc") or None,
            artist=payload.get("artist") or identity.artist,
            title=payload.get("name") or payload.get("title") or identity.title,
            album=payload.get("album") or identity.album,
            album_artist=payload.get("album_artist"),
            duration=payload.get("duration") if payload.get("duration") is not None else identity.duration,
            quality=payload.get("quality"),
            fmt=payload.get("format") or payload.get("fmt"),
            codec=payload.get("codec") or identity.codec,
            genre=payload.get("genre"),
            metadata_complete=True,
            file_size=identity.size,
            file_mtime=identity.mtime,
            file_inode=identity.inode,
            file_device=identity.device,
        )

    def reconcile(self, *, force: bool = False) -> PathReconcileResult:
        del force
        if not self.roots:
            return PathReconcileResult(unchanged=True)

        current, unreadable = self.walk_dirs()
        if not current and unreadable:
            return PathReconcileResult(unchanged=True, skipped_dirs=sorted(unreadable))

        stored = self.db.dir_signatures()
        stored_keys = set(stored)
        current_keys = set(current)
        skip_prefixes = set(unreadable)

        vanished_dirs = {
            directory for directory in stored_keys - current_keys
            if not _is_under(directory, skip_prefixes)
        }
        new_dirs = current_keys - stored_keys
        changed_dirs = {
            directory for directory in current_keys & stored_keys
            if stored[directory] != current[directory].signature
        }

        if not vanished_dirs and not new_dirs and not changed_dirs:
            now = self.now_fn()
            self.db.touch_dir_signatures(list(current_keys), checked_at=now)
            self.db.commit()
            return PathReconcileResult(unchanged=True, skipped_dirs=sorted(unreadable))

        work_dirs = changed_dirs | new_dirs
        vanished_rows: list[FileIdentity] = []
        seen_vanished: set[str] = set()

        for directory in work_dirs:
            for row in self.db.rows_in_directory(directory):
                if path_has_skipped_scan_dir(row["path"]):
                    continue
                name = Path(row["path"]).name
                if name not in current[directory].audio_names and row["path"] not in seen_vanished:
                    vanished_rows.append(_row_identity(row))
                    seen_vanished.add(row["path"])

        for directory in vanished_dirs:
            for row in self.db.rows_under_directory(directory):
                if path_has_skipped_scan_dir(row["path"]):
                    continue
                if _is_under(row["path"], skip_prefixes):
                    continue
                if row["path"] not in seen_vanished:
                    vanished_rows.append(_row_identity(row))
                    seen_vanished.add(row["path"])

        appeared: list[FileIdentity] = []
        appeared_meta: dict[str, dict | None] = {}
        resurfaced: list[str] = []
        known_by_canon = {canon_path(path): path for path in self.db.known_paths()}
        for directory in work_dirs:
            info = current[directory]
            for name in info.audio_names:
                file_path = Path(directory) / name
                if path_has_skipped_scan_dir(file_path):
                    continue
                known_path = known_by_canon.get(canon_path(file_path))
                if known_path is not None:
                    row = self.db.get(known_path)
                    if row and row.get("missing_since") is not None:
                        resurfaced.append(known_path)
                    continue
                packed = self._file_identity(file_path, read_tags=True)
                if packed is None:
                    continue
                identity, meta = packed
                if not _under_configured_roots(identity.path, self.roots):
                    continue
                appeared.append(identity)
                appeared_meta[identity.path] = meta

        vanished_rows = [
            row for row in vanished_rows if _under_configured_roots(row.path, self.roots)
        ]
        plan = plan_path_reconcile(vanished_rows, appeared)
        now = self.now_fn()
        appeared_by_path = {item.path: item for item in appeared}
        migrations = list(plan.migrations)
        mark_missing = list(plan.mark_missing)
        index_new = list(plan.index_new)

        with self.db.write_transaction():
            kept_migrations: list[tuple[str, str]] = []
            for old_path, new_path in migrations:
                identity = appeared_by_path[new_path]
                if not self.db.migrate_path(
                    old_path,
                    new_path,
                    file_size=identity.size,
                    file_mtime=identity.mtime,
                    file_inode=identity.inode,
                    file_device=identity.device,
                    duration=identity.duration,
                    codec=identity.codec,
                    title=identity.title,
                    artist=identity.artist,
                    album=identity.album,
                ):
                    mark_missing.append(old_path)
                    index_new.append(new_path)
                    continue
                kept_migrations.append((old_path, new_path))
            for old_path in mark_missing:
                self.db.mark_missing(old_path, since=now)
            for path in resurfaced:
                self.db.clear_missing(path)
            self.db.replace_dir_signatures(
                {path: info.signature for path, info in current.items()},
                checked_at=now,
                keep_dirs={directory for directory in stored_keys if _is_under(directory, skip_prefixes)},
            )

        for new_path in index_new:
            identity = appeared_by_path[new_path]
            self._index_appeared(Path(new_path), identity, appeared_meta.get(new_path))
            self.db.commit()

        return PathReconcileResult(
            unchanged=False,
            migrations=kept_migrations,
            marked_missing=list(mark_missing),
            indexed=list(index_new),
            skipped_dirs=sorted(unreadable),
            cleared_missing=list(resurfaced),
        )


def identity_from_stat(path: Path, st: os.stat_result, meta: dict | None = None) -> FileIdentity:
    payload = meta or {}
    return FileIdentity(
        path=str(path),
        size=st.st_size,
        mtime=int(st.st_mtime),
        inode=st.st_ino,
        device=st.st_dev,
        duration=payload.get("duration"),
        codec=payload.get("codec"),
        title=payload.get("name") or payload.get("title"),
        artist=payload.get("artist"),
        album=payload.get("album"),
        isrc=payload.get("isrc"),
    )
