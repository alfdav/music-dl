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
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from tidal_dl.helper.library_scanner import is_skipped_scan_dir, path_has_skipped_scan_dir

AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
DURATION_TOLERANCE_SEC = 2
RECONCILE_MIN_INTERVAL_SEC = 60
RECONCILE_COMMIT_BATCH = 50

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


def parent_directory(path: str) -> str:
    return canon_path(str(Path(path.replace("\\", "/")).parent))


def directory_editions_compatible(old_dir: str, new_dir: str) -> bool:
    return edition_tokens(Path(old_dir).name) == edition_tokens(Path(new_dir).name)


def editions_compatible(left: FileIdentity, right: FileIdentity) -> bool:
    return edition_tokens(
        left.title,
        left.album,
        left.basename or left.path,
        Path(left.path.replace("\\", "/")).parent.name,
    ) == edition_tokens(
        right.title,
        right.album,
        right.basename or right.path,
        Path(right.path.replace("\\", "/")).parent.name,
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
    directory_moves: list[tuple[str, str]] = field(default_factory=list)
    file_match_comparisons: int = 0


@dataclass
class PathReconcileResult:
    unchanged: bool = False
    migrations: list[tuple[str, str]] = field(default_factory=list)
    marked_missing: list[str] = field(default_factory=list)
    indexed: list[str] = field(default_factory=list)
    skipped_dirs: list[str] = field(default_factory=list)
    cleared_missing: list[str] = field(default_factory=list)
    directory_moves: list[tuple[str, str]] = field(default_factory=list)
    file_match_comparisons: int = 0


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


def _group_by_parent(items: Sequence[FileIdentity]) -> dict[str, list[FileIdentity]]:
    grouped: dict[str, list[FileIdentity]] = defaultdict(list)
    for item in items:
        grouped[parent_directory(item.path)].append(item)
    return grouped


def _dir_fingerprint(members: Sequence[FileIdentity], *, mode: str) -> tuple | None:
    keys: list[tuple[str, int]] = []
    for item in members:
        if mode == "size":
            if item.size is None:
                return None
            keys.append((item.basename, int(item.size)))
        else:
            if item.duration is None:
                return None
            keys.append((item.basename, int(item.duration)))
    return (len(members), tuple(sorted(keys)))


def _pair_dir_members(
    old_rows: Sequence[FileIdentity],
    new_files: Sequence[FileIdentity],
) -> list[tuple[FileIdentity, FileIdentity]] | None:
    if len(old_rows) != len(new_files) or not old_rows:
        return None
    by_base: dict[str, list[FileIdentity]] = defaultdict(list)
    for item in new_files:
        by_base[item.basename].append(item)
    pairs: list[tuple[FileIdentity, FileIdentity]] = []
    used: set[str] = set()
    for old in old_rows:
        hits: list[FileIdentity] = []
        for item in by_base.get(old.basename, ()):
            if item.path in used:
                continue
            if old.size is not None:
                if item.size is not None and old.size == item.size:
                    hits.append(item)
            elif _duration_equal(old.duration, item.duration):
                hits.append(item)
        if len(hits) != 1:
            return None
        pairs.append((old, hits[0]))
        used.add(hits[0].path)
    return pairs


def _index_by_fingerprint(
    dirs: dict[str, list[FileIdentity]],
    *,
    mode: str,
) -> dict[tuple, list[str]]:
    index: dict[tuple, list[str]] = defaultdict(list)
    for directory, members in dirs.items():
        fingerprint = _dir_fingerprint(members, mode=mode)
        if fingerprint is not None:
            index[fingerprint].append(directory)
    return index


def plan_directory_moves(
    vanished: Sequence[FileIdentity],
    appeared: Sequence[FileIdentity],
) -> tuple[
    list[tuple[str, str]],
    list[FileIdentity],
    list[FileIdentity],
    list[tuple[str, str]],
]:
    """Match whole vanished directories to appeared directories. 1:1 only."""
    v_dirs = _group_by_parent(vanished)
    a_dirs = _group_by_parent(appeared)
    by_size = _index_by_fingerprint(a_dirs, mode="size")
    by_duration = _index_by_fingerprint(a_dirs, mode="duration")

    candidates: dict[str, tuple[str, list[tuple[FileIdentity, FileIdentity]]]] = {}
    for v_dir, v_members in v_dirs.items():
        a_dir = None
        size_fp = _dir_fingerprint(v_members, mode="size")
        if size_fp is not None:
            hits = by_size.get(size_fp, ())
            if len(hits) == 1:
                a_dir = hits[0]
        if a_dir is None and all(item.size is None for item in v_members):
            duration_fp = _dir_fingerprint(v_members, mode="duration")
            if duration_fp is not None:
                hits = by_duration.get(duration_fp, ())
                if len(hits) == 1:
                    a_dir = hits[0]
        if a_dir is None or a_dir == v_dir:
            continue
        if not directory_editions_compatible(v_dir, a_dir):
            continue
        pairs = _pair_dir_members(v_members, a_dirs[a_dir])
        if pairs is None:
            continue
        candidates[v_dir] = (a_dir, pairs)

    claimed_new: dict[str, list[str]] = defaultdict(list)
    for v_dir, (a_dir, _pairs) in candidates.items():
        claimed_new[a_dir].append(v_dir)

    migrations: list[tuple[str, str]] = []
    directory_moves: list[tuple[str, str]] = []
    used_v: set[str] = set()
    used_a: set[str] = set()
    for v_dir, (a_dir, pairs) in candidates.items():
        if len(claimed_new[a_dir]) != 1:
            continue
        directory_moves.append((v_dir, a_dir))
        for old, new in pairs:
            migrations.append((old.path, new.path))
            used_v.add(old.path)
            used_a.add(new.path)

    pending_v = [row for row in vanished if row.path not in used_v]
    pending_a = [row for row in appeared if row.path not in used_a]
    return migrations, pending_v, pending_a, directory_moves


def _unique_pairs(
    vanished: Sequence[FileIdentity],
    appeared: Sequence[FileIdentity],
    matches: Callable[[FileIdentity, FileIdentity], bool],
    key_fn: Callable[[FileIdentity], object | None],
    comparisons: list[int],
) -> list[tuple[FileIdentity, FileIdentity]]:
    buckets: dict[object, list[FileIdentity]] = defaultdict(list)
    for item in appeared:
        key = key_fn(item)
        if key is None:
            continue
        buckets[key].append(item)

    v_hits: dict[str, list[FileIdentity]] = {}
    for vanished_row in vanished:
        key = key_fn(vanished_row)
        if key is None:
            v_hits[vanished_row.path] = []
            continue
        hits: list[FileIdentity] = []
        for item in buckets.get(key, ()):
            comparisons[0] += 1
            if matches(vanished_row, item):
                hits.append(item)
        v_hits[vanished_row.path] = hits

    a_hits: dict[str, list[FileIdentity]] = defaultdict(list)
    for vanished_row in vanished:
        for item in v_hits[vanished_row.path]:
            a_hits[item.path].append(vanished_row)

    pairs: list[tuple[FileIdentity, FileIdentity]] = []
    for vanished_row in vanished:
        hits = v_hits[vanished_row.path]
        if len(hits) != 1:
            continue
        candidate = hits[0]
        reverse = a_hits[candidate.path]
        if len(reverse) != 1 or reverse[0].path != vanished_row.path:
            continue
        pairs.append((vanished_row, candidate))
    return pairs


def _inode_key(item: FileIdentity) -> object | None:
    if not inode_usable(item.inode, item.device) or item.size is None:
        return None
    return ("ino", item.device, item.inode, item.size)


def _tags_key(item: FileIdentity) -> object | None:
    if item.size is None or item.duration is None:
        return None
    return (
        "tags",
        item.size,
        item.duration,
        normalize_compare_text(item.codec),
        normalize_compare_text(item.title),
        normalize_compare_text(item.artist),
        normalize_compare_text(item.album),
    )


def _basename_key(item: FileIdentity) -> object | None:
    if item.size is None or item.duration is None:
        return None
    return ("base", item.size, item.duration, item.basename)


def _legacy_key(item: FileIdentity) -> object | None:
    if item.duration is None or not item.basename:
        return None
    return (
        "legacy",
        item.basename,
        normalize_compare_text(item.title),
        normalize_compare_text(item.artist),
        normalize_compare_text(item.album),
    )


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


def plan_file_matches(
    vanished: Sequence[FileIdentity],
    appeared: Sequence[FileIdentity],
) -> tuple[list[tuple[str, str]], list[FileIdentity], list[FileIdentity], int]:
    pending_v = list(vanished)
    pending_a = list(appeared)
    migrations: list[tuple[str, str]] = []
    comparisons = [0]
    ladders = (
        (_match_inode, _inode_key),
        (_match_tags, _tags_key),
        (_match_basename, _basename_key),
        (_match_legacy, _legacy_key),
    )
    for matcher, key_fn in ladders:
        if not pending_v or not pending_a:
            break
        pairs = _unique_pairs(pending_v, pending_a, matcher, key_fn, comparisons)
        used_v = {left.path for left, _right in pairs}
        used_a = {right.path for _left, right in pairs}
        migrations.extend((left.path, right.path) for left, right in pairs)
        pending_v = [row for row in pending_v if row.path not in used_v]
        pending_a = [row for row in pending_a if row.path not in used_a]
    return migrations, pending_v, pending_a, comparisons[0]


def plan_path_reconcile(
    vanished: Sequence[FileIdentity],
    appeared: Sequence[FileIdentity],
) -> PathReconcilePlan:
    """Match vanished rows to appeared files. Directory moves run first."""
    dir_migrations, pending_v, pending_a, directory_moves = plan_directory_moves(
        vanished, appeared,
    )
    file_migrations, pending_v, pending_a, comparisons = plan_file_matches(
        pending_v, pending_a,
    )
    return PathReconcilePlan(
        migrations=dir_migrations + file_migrations,
        mark_missing=[row.path for row in pending_v],
        index_new=[row.path for row in pending_a],
        directory_moves=directory_moves,
        file_match_comparisons=comparisons,
    )


class _DirectoryMoveFailed(Exception):
    pass


def apply_path_migrations(
    db,
    migrations: Sequence[tuple[str, str]],
    appeared_by_path: dict[str, FileIdentity],
    *,
    directory_moves: Sequence[tuple[str, str]] = (),
    on_progress: Callable[..., None] | None = None,
    batch_size: int = RECONCILE_COMMIT_BATCH,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Apply planned migrations in per-directory transactions, then batches of 50."""

    def emit(**payload: object) -> None:
        if on_progress is not None:
            on_progress(**payload)

    def migrate_one(old_path: str, new_path: str) -> bool:
        identity = appeared_by_path[new_path]
        return db.migrate_path(
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
        )

    dir_old = {canon_path(old_dir) for old_dir, _new_dir in directory_moves}
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    leftover: list[tuple[str, str]] = []
    for old_path, new_path in migrations:
        parent = parent_directory(old_path)
        if parent in dir_old:
            grouped[parent].append((old_path, new_path))
        else:
            leftover.append((old_path, new_path))

    kept: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    done = 0
    total = len(migrations)
    emit(phase="migrating", scanned=0, total=total, migrated=0)

    for pairs in grouped.values():
        try:
            with db.write_transaction():
                for old_path, new_path in pairs:
                    if not migrate_one(old_path, new_path):
                        raise _DirectoryMoveFailed(old_path)
        except _DirectoryMoveFailed:
            leftover.extend(pairs)
        else:
            kept.extend(pairs)
            done += len(pairs)
            emit(phase="migrating", scanned=done, total=total, migrated=done)

    for offset in range(0, len(leftover), batch_size):
        chunk = leftover[offset:offset + batch_size]
        with db.write_transaction():
            for old_path, new_path in chunk:
                if migrate_one(old_path, new_path):
                    kept.append((old_path, new_path))
                else:
                    failed.append((old_path, new_path))
        done += len(chunk)
        emit(phase="migrating", scanned=done, total=total, migrated=len(kept))

    return kept, failed


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

    def _emit(self, on_progress: Callable[..., None] | None, **payload: object) -> None:
        if on_progress is not None:
            on_progress(**payload)

    def _enrich_tags(
        self,
        items: Sequence[FileIdentity],
        appeared_meta: dict[str, dict | None],
    ) -> list[FileIdentity]:
        enriched: list[FileIdentity] = []
        for item in items:
            if item.duration is not None and item.title is not None:
                enriched.append(item)
                continue
            packed = self._file_identity(Path(item.path), read_tags=True)
            if packed is None:
                enriched.append(item)
                continue
            identity, meta = packed
            appeared_meta[identity.path] = meta
            enriched.append(identity)
        return enriched

    def _collect_pools(
        self,
        current: dict[str, _DirInfo],
        skip_prefixes: set[str],
    ) -> tuple[list[FileIdentity], list[FileIdentity], dict[str, dict | None], list[str]]:
        on_disk: dict[str, str] = {}
        for directory, info in current.items():
            for name in info.audio_names:
                actual = str(Path(directory) / name)
                on_disk[canon_path(actual)] = actual

        vanished_rows: list[FileIdentity] = []
        known_by_canon: dict[str, dict] = {}
        for row in self.db.identity_rows():
            path = row["path"]
            known_by_canon[canon_path(path)] = row
            if path_has_skipped_scan_dir(path):
                continue
            if _is_under(path, skip_prefixes):
                continue
            if not _under_configured_roots(path, self.roots):
                continue
            if canon_path(path) not in on_disk:
                vanished_rows.append(_row_identity(row))

        appeared: list[FileIdentity] = []
        appeared_meta: dict[str, dict | None] = {}
        resurfaced: list[str] = []
        for canon, actual in on_disk.items():
            if path_has_skipped_scan_dir(actual):
                continue
            if not _under_configured_roots(actual, self.roots):
                continue
            known = known_by_canon.get(canon)
            if known is not None:
                if known.get("missing_since") is not None:
                    resurfaced.append(known["path"])
                continue
            packed = self._file_identity(Path(actual), read_tags=False)
            if packed is None:
                continue
            identity, _meta = packed
            appeared.append(identity)

        if any(row.size is None for row in vanished_rows):
            v_counts = {len(members) for members in _group_by_parent(vanished_rows).values()}
            a_groups = _group_by_parent(appeared)
            needs = [
                item for item in appeared
                if len(a_groups.get(parent_directory(item.path), ())) in v_counts
            ]
            need_paths = {item.path for item in needs}
            others = [item for item in appeared if item.path not in need_paths]
            appeared = others + self._enrich_tags(needs, appeared_meta)
        return vanished_rows, appeared, appeared_meta, resurfaced

    def reconcile(
        self,
        *,
        force: bool = False,
        on_progress: Callable[..., None] | None = None,
    ) -> PathReconcileResult:
        del force
        if not self.roots:
            return PathReconcileResult(unchanged=True)

        self._emit(on_progress, phase="walking")
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

        vanished_rows, appeared, appeared_meta, resurfaced = self._collect_pools(
            current, skip_prefixes,
        )
        self._emit(
            on_progress,
            phase="matching",
            vanished=len(vanished_rows),
            appeared=len(appeared),
            total=len(vanished_rows) + len(appeared),
        )

        dir_migrations, pending_v, pending_a, directory_moves = plan_directory_moves(
            vanished_rows, appeared,
        )
        pending_a = self._enrich_tags(pending_a, appeared_meta)
        file_migrations, pending_v, pending_a, comparisons = plan_file_matches(
            pending_v, pending_a,
        )
        plan = PathReconcilePlan(
            migrations=dir_migrations + file_migrations,
            mark_missing=[row.path for row in pending_v],
            index_new=[row.path for row in pending_a],
            directory_moves=directory_moves,
            file_match_comparisons=comparisons,
        )

        now = self.now_fn()
        appeared_by_path = {item.path: item for item in appeared}
        for item in pending_a:
            appeared_by_path[item.path] = item
        mark_missing = list(plan.mark_missing)
        index_new = list(plan.index_new)

        kept_migrations, failed = apply_path_migrations(
            self.db,
            plan.migrations,
            appeared_by_path,
            directory_moves=plan.directory_moves,
            on_progress=on_progress,
        )
        for old_path, new_path in failed:
            mark_missing.append(old_path)
            index_new.append(new_path)

        for offset in range(0, len(mark_missing), RECONCILE_COMMIT_BATCH):
            chunk = mark_missing[offset:offset + RECONCILE_COMMIT_BATCH]
            with self.db.write_transaction():
                for old_path in chunk:
                    self.db.mark_missing(old_path, since=now)
            self._emit(
                on_progress,
                phase="marking_missing",
                scanned=min(offset + len(chunk), len(mark_missing)),
                total=len(mark_missing),
                missing=min(offset + len(chunk), len(mark_missing)),
            )

        if resurfaced:
            with self.db.write_transaction():
                for path in resurfaced:
                    self.db.clear_missing(path)

        with self.db.write_transaction():
            self.db.replace_dir_signatures(
                {path: info.signature for path, info in current.items()},
                checked_at=now,
                keep_dirs={directory for directory in stored_keys if _is_under(directory, skip_prefixes)},
            )

        index_identities = self._enrich_tags(
            [appeared_by_path[path] for path in index_new if path in appeared_by_path],
            appeared_meta,
        )
        indexed_paths: list[str] = []
        for identity in index_identities:
            self._index_appeared(
                Path(identity.path), identity, appeared_meta.get(identity.path),
            )
            indexed_paths.append(identity.path)
            if len(indexed_paths) % RECONCILE_COMMIT_BATCH == 0:
                self.db.commit()
                self._emit(
                    on_progress,
                    phase="indexing",
                    scanned=len(indexed_paths),
                    total=len(index_identities),
                    indexed=len(indexed_paths),
                )
        if index_identities:
            self.db.commit()
            self._emit(
                on_progress,
                phase="indexing",
                scanned=len(indexed_paths),
                total=len(index_identities),
                indexed=len(indexed_paths),
            )

        return PathReconcileResult(
            unchanged=False,
            migrations=kept_migrations,
            marked_missing=list(mark_missing),
            indexed=indexed_paths,
            skipped_dirs=sorted(unreadable),
            cleared_missing=list(resurfaced),
            directory_moves=list(plan.directory_moves),
            file_match_comparisons=plan.file_match_comparisons,
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
