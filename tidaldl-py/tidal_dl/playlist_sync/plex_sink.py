"""Append-only Plex writer. It never deletes, moves, reorders, or clears."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from tidal_dl.playlist_sync.ledger import Ledger
from tidal_dl.playlist_sync.matcher import normalize_playlist_name
from tidal_dl.playlist_sync.models import AppendResult, Track
from tidal_dl.playlist_sync.plex_client import PlexClient, PlexError, file_paths
from tidal_dl.playlist_sync.plex_token import resolve_plex_token
from tidal_dl.playlist_sync.sink import NullPlexSink, PlexSink
from tidal_dl.playlist_sync.unicode_norm import apply_prefix_map, nfc_path, nfd_path


class PlexWriterSink:
    """Find or create one playlist and append rating keys at the end.

    ``dry_run`` refuses create, add, and scan. After one scan times out,
    a later file still gets one folder scan and one lookup, and this
    instance does not wait again.
    """

    def __init__(
        self,
        client: PlexClient,
        ledger: Ledger,
        *,
        local_prefix: str,
        server_prefix: str,
        scan_timeout_sec: float = 600,
        poll_sec: float = 10,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        dry_run: bool = True,
    ) -> None:
        self._client = client
        self._ledger = ledger
        self._local_prefix = nfc_path(local_prefix)
        self._server_prefix = nfc_path(server_prefix)
        self._scan_timeout_sec = float(scan_timeout_sec)
        self._poll_sec = float(poll_sec)
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._dry_run = dry_run
        self._gave_up = False
        self._step = ""

    def __repr__(self) -> str:
        return f"PlexWriterSink(section={self._client.section_id})"

    def list_tracks(self, name: str) -> list[Track]:
        match = self._named(name)
        if match is None:
            return []
        rows = self._client.playlist_items(match["rating_key"])
        stamp = _stamp()
        tracks: list[Track] = []
        for row in rows:
            track = track_from_metadata(row)
            tracks.append(track)
            if not track.source_track_id:
                continue
            for path in file_paths(row):
                self._ledger.remember_plex_path(path, track.source_track_id, at=stamp)
        return tracks

    def find(self, track: Track) -> list[Track]:
        return [track_from_metadata(row) for row in self._client.search_tracks(track.title)]

    def append(
        self,
        name: str,
        tracks: list[Track],
        paths: Sequence[str | None] | None = None,
    ) -> AppendResult:
        if self._dry_run:
            return AppendResult(status="dry_run")
        self._step = ""
        try:
            return self._append_tracks(name, tracks, paths)
        except PlexError as exc:
            detail = exc.describe()
            if self._step:
                detail = f"{detail} during={self._step}"
            return AppendResult(status="failed", detail=detail[:500])

    def _append_tracks(
        self,
        name: str,
        tracks: list[Track],
        paths: Sequence[str | None] | None,
    ) -> AppendResult:
        jobs: list[tuple[Track, str | None, str]] = []
        saw_unmapped = False
        for index, track in enumerate(tracks):
            raw_path = paths[index] if paths is not None and index < len(paths) else None
            if (track.source or "").casefold() == "plex" and track.source_track_id:
                jobs.append((track, None, "plex"))
                continue
            mapped = self._map(raw_path)
            if mapped is None:
                saw_unmapped = True
                continue
            jobs.append((track, mapped, "file"))
        if not jobs:
            return AppendResult(status="unmapped_path" if saw_unmapped else "failed")

        match = self._named(name)
        if match is not None and match["smart"]:
            return AppendResult(status="refused_smart")

        resolved: list[tuple[Track, str, str | None]] = []
        failure = "unmapped_path" if saw_unmapped else None
        for track, mapped, kind in jobs:
            if kind == "plex":
                resolved.append((track, track.source_track_id, None))
                continue
            assert mapped is not None
            key = self._resolve_file(track.title, mapped)
            if key is None:
                failure = "pending_plex"
                continue
            resolved.append((track, key, mapped))
        if not resolved:
            return AppendResult(status=failure or "pending_plex")

        written, removed = self._write_keys(name, match, [key for _track, key, _path in resolved])
        removed_keys = set(removed)
        for track, key, mapped in resolved:
            if key in removed_keys:
                continue
            self._remember(track, name, key, mapped)
        if written:
            return AppendResult(status="added", rating_keys=written)
        if removed:
            return AppendResult(status="removed_in_plex", rating_keys=removed)
        return AppendResult(status="already_present", rating_keys=[key for _track, key, _path in resolved])

    def _named(self, name: str) -> dict[str, Any] | None:
        target = normalize_playlist_name(name)
        for item in self._client.list_audio_playlists():
            if normalize_playlist_name(str(item.get("title") or "")) == target:
                return item
        return None

    def _map(self, local_path: str | None) -> str | None:
        if not local_path or not self._local_prefix or not self._server_prefix:
            return None
        local = nfc_path(local_path)
        if not _under(local, self._local_prefix):
            return None
        return apply_prefix_map(local, {self._local_prefix: self._server_prefix})

    def _resolve_file(self, title: str, server_path: str) -> str | None:
        self._step = f"lookup path={server_path}"
        found = self._rating_for_path(title, server_path)
        if found is not None:
            return found
        self._step = f"scan folder={_folder(server_path)}"
        self._client.scan_path(_folder(server_path))
        self._step = f"lookup after scan path={server_path}"
        if self._gave_up:
            return self._rating_for_path(title, server_path)
        deadline = self._clock() + self._scan_timeout_sec
        while True:
            found = self._rating_for_path(title, server_path)
            if found is not None:
                return found
            now = self._clock()
            if now >= deadline:
                self._gave_up = True
                return None
            self._sleep(self._poll_sec)
            if self._clock() <= now:
                self._gave_up = True
                return None

    def _rating_for_path(self, title: str, server_path: str) -> str | None:
        cached = self._ledger.get_plex_rating_key(server_path)
        if cached:
            return cached
        # The file path is exact. Plex titles often differ from the source title
        # (curly quotes, accents, "(Live)" or "(Remastered)" dropped), so a title
        # search alone misses files Plex already has.
        for form in _path_forms(server_path):
            found = _match_path(self._client.tracks_by_file(form), server_path)
            if found:
                return found
        found = _match_path(self._client.search_tracks(title), server_path)
        if found:
            return found
        return _match_path(self._client.recently_added_tracks(), server_path)

    def _write_keys(
        self,
        name: str,
        match: dict[str, Any] | None,
        keys: list[str],
    ) -> tuple[list[str], list[str]]:
        """Return keys written, then keys a user removed after sync added them.

        A recorded key that is no longer on the playlist is not written back.
        If the playlist itself is gone, recorded keys do not recreate it.
        """
        ordered = _dedupe(keys)
        if not ordered:
            return [], []
        name_norm = normalize_playlist_name(name)
        recorded = self._ledger.plex_added_keys(name_norm)
        if match is None:
            removed = [key for key in ordered if key in recorded]
            fresh = [key for key in ordered if key not in recorded]
            if not fresh:
                return [], removed
            self._step = f"create playlist first_key={fresh[0]}"
            playlist_key = self._client.create_playlist(name, fresh[0])
            written = [fresh[0]]
            self._note_added(name_norm, written)
            rest = [key for key in fresh[1:] if key != fresh[0]]
            if rest:
                self._client.add_to_playlist(playlist_key, rest)
                self._note_added(name_norm, rest)
                written.extend(rest)
            return written, removed
        current = {
            str(row.get("ratingKey"))
            for row in self._client.playlist_items(match["rating_key"])
            if row.get("ratingKey") is not None and str(row.get("ratingKey")) != ""
        }
        removed = [key for key in ordered if key in recorded and key not in current]
        fresh = [key for key in ordered if key not in current and key not in recorded]
        if not fresh:
            return [], removed
        self._step = f"add keys={','.join(fresh)} playlist={match['rating_key']}"
        self._client.add_to_playlist(match["rating_key"], fresh)
        self._note_added(name_norm, fresh)
        return fresh, removed

    def _note_added(self, name_norm: str, keys: list[str]) -> None:
        stamp = _stamp()
        for key in keys:
            self._ledger.remember_plex_added(name_norm, key, at=stamp)

    def _remember(self, track: Track, playlist_name: str, rating_key: str, server_path: str | None) -> None:
        if server_path:
            self._ledger.remember_plex_path(server_path, rating_key, at=_stamp())
        self._ledger.set_plex_rating_key(track, normalize_playlist_name(playlist_name), rating_key)


def build_plex_sink(
    cfg: Any,
    ledger: Ledger,
    *,
    session: Any | None = None,
    token_resolver: Callable[[], Any] | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    poll_sec: float = 10,
) -> PlexSink:
    """Build a writer when the URL, section, and token are all set. Otherwise a null sink."""
    url = str(getattr(cfg, "plex_url", "") or "").strip()
    section = str(getattr(cfg, "plex_section_id", "") or "").strip()
    if not url or not section:
        return NullPlexSink()
    resolve = token_resolver or resolve_plex_token
    token = resolve()
    if token is None or not str(token.reveal()).strip():
        return NullPlexSink()
    dry_run = bool(getattr(cfg, "dry_run", True))
    raw_timeout = getattr(cfg, "plex_scan_timeout_sec", 600)
    timeout = 600.0 if raw_timeout is None or raw_timeout == "" else float(raw_timeout)
    client = PlexClient(url, token, section, session=session, read_only=dry_run)
    return PlexWriterSink(
        client,
        ledger,
        local_prefix=str(getattr(cfg, "plex_local_prefix", "") or ""),
        server_prefix=str(getattr(cfg, "plex_server_prefix", "") or ""),
        scan_timeout_sec=timeout,
        poll_sec=poll_sec,
        clock=clock,
        sleep=sleep,
        dry_run=dry_run,
    )


def track_from_metadata(row: dict[str, Any]) -> Track:
    original = str(row.get("originalTitle") or "").strip()
    artist = original or str(row.get("grandparentTitle") or "")
    paths = file_paths(row)
    return Track(
        source="plex",
        source_track_id=str(row.get("ratingKey") or ""),
        title=str(row.get("title") or ""),
        artist=artist,
        album=str(row.get("parentTitle") or ""),
        duration=_seconds(row.get("duration")),
        path=paths[0] if paths else "",
    )


def _seconds(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None


def _under(path: str, prefix: str) -> bool:
    if path == prefix:
        return True
    head = prefix if prefix.endswith("/") else f"{prefix}/"
    return path.startswith(head)


def _folder(path: str) -> str:
    text = nfc_path(path).rstrip("/")
    if "/" not in text:
        return text
    return text.rsplit("/", 1)[0]


def _match_path(rows: list[dict[str, Any]], server_path: str) -> str | None:
    target = nfc_path(server_path)
    for row in rows:
        if target not in file_paths(row):
            continue
        key = row.get("ratingKey")
        if key is not None and str(key) != "":
            return str(key)
    return None


def _path_forms(server_path: str) -> list[str]:
    """NFC first, then NFD when it differs. Plex stores whatever bytes the scanner saw."""
    forms = [nfc_path(server_path)]
    decomposed = nfd_path(server_path)
    if decomposed not in forms:
        forms.append(decomposed)
    return forms


def _dedupe(keys: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _stamp() -> str:
    return datetime.now(UTC).isoformat()
