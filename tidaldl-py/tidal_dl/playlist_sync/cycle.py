"""One playlist-sync cycle. Nothing here runs unless the caller asks."""

from __future__ import annotations

import inspect
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from tidal_dl.download.api_pacing import TidalApiPacer
from tidal_dl.playlist_sync.config import PlaylistSyncConfig, load_config, name_allowed
from tidal_dl.playlist_sync.downloads import DownloadClient, existing_library_file, service_downloader
from tidal_dl.playlist_sync.governor import Governor, status_code_of
from tidal_dl.playlist_sync.ledger import Ledger, default_ledger_path
from tidal_dl.playlist_sync.matcher import isrc_key, normalize_playlist_name, same_recording
from tidal_dl.playlist_sync.models import (
    Candidate,
    CycleReport,
    DownloadResult,
    PlaylistRef,
    PlaylistReport,
    Track,
    VerifyResult,
    candidate_from_mapping,
    candidate_from_track,
    coerce_track,
)
from tidal_dl.playlist_sync.mount import download_path_available
from tidal_dl.playlist_sync.sink import PlexSink
from tidal_dl.playlist_sync.source import Source
from tidal_dl.playlist_sync.tags import read_audio_tags
from tidal_dl.playlist_sync.unicode_norm import apply_prefix_map, nfc_path
from tidal_dl.playlist_sync.verify import verify

LibraryLookup = Callable[[Track], list[Candidate]]
SearchFn = Callable[[Track], list[Candidate]]
TagReader = Callable[[str], dict[str, Any] | None]
AuthState = Callable[[], str]


@dataclass
class _Group:
    name: str
    tidal: PlaylistRef | None = None
    apple: PlaylistRef | None = None
    tidal_source: Source | None = None
    apple_source: Source | None = None


@dataclass
class _Placed:
    track: Track
    action: str
    entry: dict[str, Any]


@dataclass
class _Work:
    cfg: PlaylistSyncConfig
    ledger: Ledger
    sink: PlexSink
    governor: Governor
    day: str
    seen_at: str
    library: LibraryLookup | None
    search: SearchFn | None
    tag_reader: TagReader
    downloads: DownloadClient | None
    path_prefixes: Mapping[str, str] = field(default_factory=dict)
    file_exists: Callable[[str], bool] = os.path.exists
    report: CycleReport = field(default_factory=CycleReport)
    recording_downloads: set[str] = field(default_factory=set)
    _downloads_ready: DownloadClient | None = None

    def client(self) -> DownloadClient:
        if self._downloads_ready is not None:
            return self._downloads_ready
        if self.downloads is not None:
            self._downloads_ready = self.downloads
            return self.downloads
        self._downloads_ready = service_downloader()
        return self._downloads_ready


def read_auth_state(tidal: Any) -> str:
    """Read auth_state from an in-memory session. Does not log in or write tokens."""
    data = getattr(tidal, "data", None)
    access = getattr(data, "access_token", None) if data is not None else None
    if not access:
        return "not_configured"
    expiry = getattr(data, "expiry_time", 0) or 0
    try:
        expiry_value = expiry.timestamp() if hasattr(expiry, "timestamp") else float(expiry)
    except (TypeError, ValueError):
        return "unavailable"
    if expiry_value > 0 and expiry_value <= datetime.now(UTC).timestamp():
        return "expired"
    user = getattr(getattr(tidal, "session", None), "user", None)
    if user is None:
        return "unavailable"
    return "credentials_ready"


def local_day(now: datetime) -> str:
    if now.tzinfo is not None:
        now = now.astimezone()
    return now.date().isoformat()


def run_cycle(
    now: datetime | None = None,
    *,
    settings: Any | None = None,
    sources: Sequence[Source] | None = None,
    sink: PlexSink | None = None,
    ledger: Ledger | None = None,
    downloads: DownloadClient | None = None,
    library: LibraryLookup | None = None,
    search: SearchFn | None = None,
    tag_reader: TagReader | None = None,
    clock: Callable[[], float] | None = None,
    rng: Any | None = None,
    sleep: Callable[[float], None] | None = None,
    pacer: TidalApiPacer | None = None,
    auth_state: AuthState | None = None,
    tidal: Any | None = None,
    force: bool = False,
    download_path_ready: Callable[[str], bool] | None = None,
    path_prefixes: Mapping[str, str] | None = None,
    file_exists: Callable[[str], bool] | None = None,
    plex_session: Any | None = None,
    plex_token_resolver: Callable[[], Any] | None = None,
) -> CycleReport:
    """Plan or run one append-only sync cycle.

    Disabled settings return a report and do no work. Dry-run queues nothing
    and appends nothing. Pass force to run when the setting is off.
    """
    cfg = load_config(settings)
    if not cfg.enabled and not force:
        return CycleReport(halted_reason="disabled")

    owned_ledger = ledger is None
    store: Ledger | None = None
    handle: _LibraryHandle | None = None
    work: _Work | None = None
    try:
        moment = now or datetime.now(UTC).astimezone()
        day = local_day(moment)
        if auth_state is None:
            auth_state = (lambda: read_auth_state(tidal)) if tidal is not None else (lambda: "not_configured")
        store = ledger or Ledger(default_ledger_path())
        governor = Governor(
            ledger=store,
            day=day,
            max_per_cycle=cfg.max_per_cycle,
            max_per_day=cfg.max_per_day,
            gap_sec_min=cfg.gap_sec_min,
            gap_sec_max=cfg.gap_sec_max,
            auth_state=auth_state,
            sleep=sleep,
            rng=rng,
            pacer=pacer,
            clock=clock,
            persist_counts=not cfg.dry_run,
        )
        if not governor.auth_ok():
            return CycleReport(halted_reason=governor.halted_reason)
        ready = download_path_ready or download_path_available
        if not ready(cfg.download_base_path):
            return CycleReport(halted_reason="download_path_unavailable")

        # An injected lookup is used as-is. Otherwise one connection covers the cycle.
        if library is not None:
            lookup = library
        else:
            handle = _LibraryHandle()
            lookup = handle
        if sink is not None:
            chosen_sink = sink
        else:
            from tidal_dl.playlist_sync.plex_sink import build_plex_sink

            chosen_sink = build_plex_sink(
                cfg,
                store,
                session=plex_session,
                token_resolver=plex_token_resolver,
                clock=clock,
                sleep=sleep,
            )
        work = _Work(
            cfg=cfg,
            ledger=store,
            sink=chosen_sink,
            governor=governor,
            day=day,
            seen_at=moment.isoformat(),
            library=lookup,
            search=search,
            tag_reader=tag_reader or read_audio_tags,
            downloads=downloads,
            path_prefixes=dict(path_prefixes or {}),
            file_exists=file_exists or os.path.exists,
        )
        readers = list(sources) if sources is not None else _default_sources(tidal)
        groups = _collect_groups(readers, cfg.allowlist, governor, work.report)
        if governor.halted_reason:
            work.report.halted_reason = governor.halted_reason
            return work.report

        for group in groups.values():
            if governor.halted_reason:
                break
            _sync_group(work, group)
        work.report.halted_reason = governor.halted_reason
        return work.report
    except Exception:
        logging.getLogger(__name__).exception("playlist sync cycle failed")
        report = work.report if work is not None else CycleReport()
        report.halted_reason = "internal_error"
        return report
    finally:
        if handle is not None:
            handle.close()
        if owned_ledger and store is not None:
            store.close()


def _default_sources(tidal: Any | None) -> list[Source]:
    if tidal is None:
        return []
    from tidal_dl.playlist_sync.tidal_source import TidalSource

    session = getattr(tidal, "session", tidal)
    return [TidalSource(session)]


def _note_source_error(
    report: CycleReport,
    source: str,
    playlist: str | None,
    exc: BaseException,
) -> None:
    report.source_errors.append(
        {
            "source": source,
            "playlist": playlist,
            "status": "source_error",
            "error": type(exc).__name__,
        }
    )


def _collect_groups(
    sources: Sequence[Source],
    allowlist: tuple[str, ...],
    governor: Governor,
    report: CycleReport,
) -> dict[str, _Group]:
    groups: dict[str, _Group] = {}
    for source in sources:
        if governor.halted_reason:
            break
        try:
            listed = source.list_playlists()
        except Exception as exc:  # noqa: BLE001 — a source listing error must not stop the cycle
            code = status_code_of(exc)
            if code in (401, 429):
                governor.halt(str(code))
                break
            _note_source_error(report, source.name, None, exc)
            continue
        kind = source.name.casefold()
        for playlist in listed:
            if not name_allowed(playlist.name, allowlist):
                continue
            key = normalize_playlist_name(playlist.name)
            group = groups.setdefault(key, _Group(name=playlist.name))
            if kind == "tidal":
                group.tidal = playlist
                group.tidal_source = source
                group.name = playlist.name
            elif kind == "apple":
                group.apple = playlist
                group.apple_source = source
                if group.tidal is None:
                    group.name = playlist.name
    return groups


def _is_plex_error(exc: BaseException) -> bool:
    # Lazy so cycle.py does not import the Plex client while the package loads.
    from tidal_dl.playlist_sync.plex_client import PlexError

    return isinstance(exc, PlexError)


def _track_snapshot(
    report: PlaylistReport,
    cycle: CycleReport,
    placed: list[_Placed],
    union: list[Track],
) -> dict[str, Any]:
    return {
        "tracks": len(report.tracks),
        "needs_review": len(report.needs_review),
        "placed": len(placed),
        "union": len(union),
        "cycle": {name: len(value) for name, value in vars(cycle).items() if isinstance(value, list)},
        "counters": {name: value for name, value in vars(report).items() if isinstance(value, int)},
    }


def _restore_track_snapshot(
    snapshot: dict[str, Any],
    report: PlaylistReport,
    cycle: CycleReport,
    placed: list[_Placed],
    union: list[Track],
) -> None:
    del report.tracks[snapshot["tracks"] :]
    del report.needs_review[snapshot["needs_review"] :]
    del placed[snapshot["placed"] :]
    del union[snapshot["union"] :]
    for name, length in snapshot["cycle"].items():
        del getattr(cycle, name)[length:]
    for name, value in snapshot["counters"].items():
        setattr(report, name, value)


def _note_track_error(
    work: _Work,
    group: _Group,
    report: PlaylistReport,
    placed: list[_Placed],
    track: Track,
    exc: BaseException,
) -> None:
    name_norm = normalize_playlist_name(group.name)
    row = work.ledger.get_track(track.source, track.source_track_id, name_norm)
    if row is not None and row["status"] == "queued":
        work.ledger.set_status(track, name_norm, "seen", seen_at=work.seen_at)
    entry = _entry(track, "review", "review", None, None, notes=("track_error",))
    entry["status"] = "needs_review"
    entry["error"] = type(exc).__name__
    report.tracks.append(entry)
    report.needs_review.append(entry)
    work.report.needs_review.append(entry)
    placed.append(_Placed(track, "review", entry))


def _sync_group(work: _Work, group: _Group) -> None:
    try:
        listed = work.sink.list_tracks(group.name)
    except Exception as exc:  # noqa: BLE001 — a Plex listing error must not stop the cycle
        if _is_plex_error(exc):
            work.governor.halt("plex_unavailable")
            return
        _note_source_error(work.report, "plex", group.name, exc)
        return
    plex_tracks = [
        coerce_track(item, source="plex", playlist_name=group.name) for item in listed
    ]
    tidal_tracks = _load_tracks(work, work_source=group.tidal_source, playlist=group.tidal, name=group.name)
    if work.governor.halted_reason:
        _partial(work, group, plex_tracks, tidal_tracks, [])
        return
    apple_tracks = _load_tracks(work, work_source=group.apple_source, playlist=group.apple, name=group.name)
    if work.governor.halted_reason and not apple_tracks and group.apple is not None:
        _partial(work, group, plex_tracks, tidal_tracks, apple_tracks)
        return
    report = PlaylistReport(
        name=group.name,
        tidal_count=len(tidal_tracks),
        apple_count=len(apple_tracks),
        plex_count=len(plex_tracks),
    )
    union: list[Track] = list(plex_tracks)
    placed: list[_Placed] = []
    for track in (*tidal_tracks, *apple_tracks):
        if work.governor.halted_reason:
            break
        snapshot = _track_snapshot(report, work.report, placed, union)
        try:
            _consider(work, group, report, union, placed, plex_tracks, track)
        except Exception as exc:  # noqa: BLE001 — one track must not stop the cycle
            code = status_code_of(exc)
            if code in (401, 429):
                work.governor.halt(str(code))
                break
            _restore_track_snapshot(snapshot, report, work.report, placed, union)
            _note_track_error(work, group, report, placed, track, exc)
    report.union_count = len(union)
    work.report.playlists.append(report)


def _partial(
    work: _Work,
    group: _Group,
    plex_tracks: list[Track],
    tidal_tracks: list[Track],
    apple_tracks: list[Track],
) -> None:
    work.report.playlists.append(
        PlaylistReport(
            name=group.name,
            tidal_count=len(tidal_tracks),
            apple_count=len(apple_tracks),
            plex_count=len(plex_tracks),
            union_count=len(plex_tracks),
        )
    )


def _load_tracks(
    work: _Work,
    *,
    work_source: Source | None,
    playlist: PlaylistRef | None,
    name: str,
) -> list[Track]:
    if work_source is None or playlist is None or work.governor.halted_reason:
        return []
    name_norm = normalize_playlist_name(name)
    stamp = playlist.last_updated or ""
    seen = work.ledger.get_playlist(work_source.name, playlist.source_playlist_id)
    if seen is not None and seen["last_updated_seen"] == stamp:
        return work.ledger.tracks_for(work_source.name, name_norm)
    try:
        tracks = list(work_source.list_tracks(playlist))
    except Exception as exc:  # noqa: BLE001 — a track listing error must not stop the cycle
        code = status_code_of(exc)
        if code in (401, 429):
            work.governor.halt(str(code))
            return []
        _note_source_error(work.report, work_source.name, playlist.name, exc)
        return []
    work.ledger.upsert_playlist(work_source.name, playlist.source_playlist_id, name_norm, stamp)
    for track in tracks:
        work.ledger.remember_track(track, name_norm, seen_at=work.seen_at)
    work.ledger.retain_membership(work_source.name, name_norm, {track.source_track_id for track in tracks})
    return tracks


def _consider(
    work: _Work,
    group: _Group,
    report: PlaylistReport,
    union: list[Track],
    placed: list[_Placed],
    plex_tracks: list[Track],
    track: Track,
) -> None:
    name_norm = normalize_playlist_name(group.name)
    plex_state, plex_candidate, plex_result = _best(track, [candidate_from_track(item) for item in plex_tracks])
    same_isrc_review = False
    if plex_state == "none" and _same_isrc_on_plex(track, plex_tracks):
        plex_state = "review"
        same_isrc_review = True
    if plex_state == "confirmed":
        _keep(
            work,
            report,
            placed,
            track,
            name_norm,
            "skip_present",
            "confirmed",
            "seen",
            plex_candidate,
            plex_result,
            candidate_source="plex_playlist",
        )
        return
    if _sync_added_then_removed(work, track, name_norm, plex_tracks):
        _note_removed(work, report, placed, track)
        return
    if plex_state == "review":
        plex_notes = ("same_isrc_in_plex_playlist",) if same_isrc_review else ()
        _keep(
            work,
            report,
            placed,
            track,
            name_norm,
            "review",
            "review",
            "needs_review",
            plex_candidate,
            plex_result,
            bucket="needs_review",
            notes=plex_notes,
            candidate_source="plex_playlist",
        )
        return

    prior = _prior(placed, track)
    if prior is not None:
        report.duplicates_in_source += 1
        entry = _entry(
            track,
            prior.action,
            prior.entry["confidence"],
            None,
            None,
            notes=("duplicate_in_source",),
        )
        entry["status"] = "duplicate_in_source"
        report.tracks.append(entry)
        placed.append(_Placed(track, prior.action, entry))
        return

    local_state, local_candidate, local_result, stale = _local(work, track)
    notes = ("stale_library_row",) if stale else ()
    if local_state == "confirmed":
        union.append(track)
        entry = _keep(
            work,
            report,
            placed,
            track,
            name_norm,
            "append",
            "confirmed",
            "matched_local",
            local_candidate,
            local_result,
            bucket="added",
            already_local=True,
            candidate_source="local_library",
        )
        if not work.cfg.dry_run:
            local_path = local_candidate.path if local_candidate is not None else None
            result = _sink_append(work, group.name, [track], [local_path])
            _finish_append(
                work,
                entry,
                track,
                name_norm,
                result,
                report=report,
                local_path=local_path,
                pending_status="matched_local",
            )
        return
    if local_state == "review":
        union.append(track)
        _keep(
            work,
            report,
            placed,
            track,
            name_norm,
            "review",
            "review",
            "needs_review",
            local_candidate,
            local_result,
            bucket="needs_review",
            candidate_source="local_library",
        )
        return

    if local_state == "none":
        plex_hit = _plex_library(work, track)
        if work.governor.halted_reason:
            return
        if plex_hit is not None:
            plex_state, plex_track, plex_choice, plex_verified = plex_hit
            if plex_state == "confirmed" and plex_track is not None:
                union.append(track)
                entry = _keep(
                    work,
                    report,
                    placed,
                    track,
                    name_norm,
                    "append",
                    "confirmed",
                    "matched_local",
                    plex_choice,
                    plex_verified,
                    bucket="added",
                    already_local=True,
                    notes=notes,
                    candidate_source="plex_library",
                )
                if not work.cfg.dry_run:
                    result = _sink_append(work, group.name, [plex_track], [None])
                    _finish_append(
                        work,
                        entry,
                        track,
                        name_norm,
                        result,
                        report=report,
                        local_path=None,
                        pending_status="matched_local",
                    )
                return
            if plex_state == "review":
                union.append(track)
                _keep(
                    work,
                    report,
                    placed,
                    track,
                    name_norm,
                    "review",
                    "review",
                    "needs_review",
                    plex_choice,
                    plex_verified,
                    bucket="needs_review",
                    notes=notes,
                    candidate_source="plex_library",
                )
                return

    row = work.ledger.get_track(track.source, track.source_track_id, name_norm)
    if row and _retry_saved_file(work, group, report, union, placed, track, name_norm, row):
        return
    if row and row["status"] == "download_mismatch":
        union.append(track)
        _keep(
            work,
            report,
            placed,
            track,
            name_norm,
            "review",
            "review",
            "download_mismatch",
            bucket="needs_review",
            notes=(*notes, "download_mismatch"),
        )
        return
    if row and row["last_failure_day"] == work.day and row["status"] == "unobtainable":
        union.append(track)
        _keep(
            work,
            report,
            placed,
            track,
            name_norm,
            "unobtainable",
            "reject",
            "unobtainable",
            bucket="unobtainable",
            notes=notes,
        )
        return
    if row and row["last_failure_day"] == work.day and row["status"] == "failed":
        union.append(track)
        entry = _entry(track, "download", "reject", None, None, notes=notes)
        entry["status"] = "failed"
        report.tracks.append(entry)
        work.report.skipped.append(entry)
        placed.append(_Placed(track, "download", entry))
        return

    if not track.available:
        union.append(track)
        _keep(
            work,
            report,
            placed,
            track,
            name_norm,
            "unobtainable",
            "reject",
            "unobtainable",
            bucket="unobtainable",
            last_failure_day=work.day,
            notes=notes,
        )
        return

    download_id, choice_candidate, choice_result, choice = _download_choice(work, track)
    if choice == "review":
        union.append(track)
        _keep(
            work,
            report,
            placed,
            track,
            name_norm,
            "review",
            "review",
            "needs_review",
            choice_candidate,
            choice_result,
            bucket="needs_review",
            notes=notes,
            candidate_source="tidal_search" if track.source.casefold() == "apple" else None,
        )
        return
    if choice == "unmatched" or download_id is None:
        union.append(track)
        _keep(
            work,
            report,
            placed,
            track,
            name_norm,
            "review",
            "reject",
            "unmatched",
            bucket="unmatched",
            notes=notes,
        )
        return

    union.append(track)
    dl_source = "tidal_search" if track.source.casefold() == "apple" else None
    if work.cfg.dry_run:
        _plan_download(
            work,
            report,
            placed,
            track,
            name_norm,
            choice_candidate,
            choice_result,
            notes=notes,
            candidate_source=dl_source,
        )
        return
    _run_download(
        work,
        group,
        report,
        placed,
        track,
        name_norm,
        download_id,
        choice_candidate,
        choice_result,
        notes=notes,
        candidate_source=dl_source,
    )


def _deferred_by_cap(work: _Work) -> bool:
    return work.governor.halted_reason is None and not work.governor.can_download()


def _recording_key(track: Track) -> str:
    code = isrc_key(track.isrc)
    if code:
        return code
    return f"{track.source}:{track.source_track_id}"


def _skip_duplicate_download(
    work: _Work,
    report: PlaylistReport,
    placed: list[_Placed],
    track: Track,
    candidate: Candidate | None,
    result: VerifyResult | None,
    notes: tuple[str, ...],
    *,
    candidate_source: str | None,
) -> bool:
    key = _recording_key(track)
    if key not in work.recording_downloads:
        return False
    entry = _entry(
        track,
        "download",
        "confirmed",
        candidate,
        result,
        notes=(*notes, "downloaded_this_cycle"),
        candidate_source=candidate_source,
    )
    entry["status"] = "deferred_duplicate"
    report.tracks.append(entry)
    work.report.skipped.append(entry)
    placed.append(_Placed(track, "download", entry))
    return True


def _plan_download(
    work: _Work,
    report: PlaylistReport,
    placed: list[_Placed],
    track: Track,
    name_norm: str,
    candidate: Candidate | None,
    result: VerifyResult | None,
    notes: tuple[str, ...] = (),
    *,
    candidate_source: str | None = None,
) -> None:
    if _skip_duplicate_download(
        work, report, placed, track, candidate, result, notes, candidate_source=candidate_source
    ):
        return
    if not work.governor.can_download():
        entry = _entry(
            track,
            "download",
            "confirmed",
            candidate,
            result,
            notes=notes,
            candidate_source=candidate_source,
        )
        entry["status"] = "deferred_cap" if _deferred_by_cap(work) else "skipped"
        if entry["status"] == "deferred_cap":
            report.to_download += 1
        report.tracks.append(entry)
        work.report.skipped.append(entry)
        placed.append(_Placed(track, "download", entry))
        return
    work.recording_downloads.add(_recording_key(track))
    work.governor.cycle_count += 1
    report.to_download += 1
    entry = _entry(
        track,
        "download",
        "confirmed",
        candidate,
        result,
        notes=notes,
        candidate_source=candidate_source,
    )
    report.tracks.append(entry)
    placed.append(_Placed(track, "download", entry))
    work.ledger.set_status(track, name_norm, "seen", seen_at=work.seen_at)


def _run_download(
    work: _Work,
    group: _Group,
    report: PlaylistReport,
    placed: list[_Placed],
    track: Track,
    name_norm: str,
    download_id: int,
    candidate: Candidate | None,
    result: VerifyResult | None,
    notes: tuple[str, ...] = (),
    *,
    candidate_source: str | None = None,
) -> None:
    if _skip_duplicate_download(
        work, report, placed, track, candidate, result, notes, candidate_source=candidate_source
    ):
        return
    work.recording_downloads.add(_recording_key(track))
    work.ledger.set_status(track, name_norm, "queued", seen_at=work.seen_at)

    def once() -> DownloadResult:
        client = work.client()
        bind = getattr(client, "bind_lookup", None)
        if callable(bind):
            bind(track, work.library, work.file_exists)
        client.enqueue_download([download_id])
        return client.wait_for(download_id)

    outcome = work.governor.download(once)
    if outcome is None:
        entry = _entry(
            track,
            "download",
            "confirmed",
            candidate,
            result,
            notes=notes,
            candidate_source=candidate_source,
        )
        entry["status"] = "deferred_cap" if _deferred_by_cap(work) else "skipped"
        if entry["status"] == "deferred_cap":
            report.to_download += 1
        report.tracks.append(entry)
        work.report.skipped.append(entry)
        placed.append(_Placed(track, "download", entry))
        work.ledger.set_status(track, name_norm, "seen", seen_at=work.seen_at)
        return

    report.to_download += 1
    if outcome.http_status in (401, 429) or outcome.status != "completed":
        entry = _entry(
            track,
            "download",
            "reject",
            candidate,
            result,
            notes=notes,
            candidate_source=candidate_source,
        )
        entry["status"] = "failed"
        report.tracks.append(entry)
        work.report.skipped.append(entry)
        placed.append(_Placed(track, "download", entry))
        work.ledger.set_status(track, name_norm, "failed", seen_at=work.seen_at, last_failure_day=work.day)
        return

    checked, file_path = _post_download(work, track, outcome)
    if checked is None:
        entry = _entry(
            track,
            "append",
            "confirmed",
            candidate,
            result,
            notes=notes,
            candidate_source=candidate_source,
        )
        entry["status"] = "added"
        report.tracks.append(entry)
        work.report.downloaded.append(entry)
        work.report.added.append(entry)
        placed.append(_Placed(track, "append", entry))
        work.ledger.set_status(track, name_norm, "downloaded", seen_at=work.seen_at, local_path=file_path or None)
        result_append = _sink_append(work, group.name, [track], [file_path or None])
        _finish_append(
            work,
            entry,
            track,
            name_norm,
            result_append,
            report=report,
            local_path=file_path or None,
            pending_status="downloaded",
        )
        return

    mismatch_candidate, mismatch = checked
    entry = _entry(
        track,
        "review",
        mismatch.confidence,
        mismatch_candidate,
        mismatch,
        notes=notes,
        candidate_source="downloaded_file",
    )
    entry["status"] = "download_mismatch"
    report.tracks.append(entry)
    report.needs_review.append(entry)
    work.report.download_mismatch.append(entry)
    work.report.needs_review.append(entry)
    placed.append(_Placed(track, "review", entry))
    work.ledger.set_status(
        track,
        name_norm,
        "download_mismatch",
        seen_at=work.seen_at,
        last_failure_day=work.day,
    )


def _post_download(
    work: _Work,
    track: Track,
    outcome: DownloadResult,
) -> tuple[tuple[Candidate, VerifyResult] | None, str]:
    looked_up = apply_prefix_map(outcome.path or "", work.path_prefixes)
    if not looked_up:
        looked_up = _existing_library_path(work, track) or ""
    if not looked_up:
        return _downloaded_file_not_found(), ""
    tags = work.tag_reader(looked_up)
    if not tags:
        empty = Candidate(id=looked_up, title="", artist="", duration=None, isrc=None)
        return (empty, verify(track, empty)), looked_up
    candidate = candidate_from_mapping({**tags, "id": looked_up, "path": looked_up})
    result = verify(track, candidate)
    if result.confidence == "confirmed":
        return None, looked_up
    return (candidate, result), looked_up


def _existing_library_path(work: _Work, track: Track) -> str | None:
    """NFC path of an ISRC library row whose file is still on disk."""
    return existing_library_file(work.library, track, work.file_exists)


def _downloaded_file_not_found() -> tuple[Candidate, VerifyResult]:
    empty = Candidate(id="", title="", artist="", duration=None, isrc=None)
    result = VerifyResult(
        artist_ok=False,
        title_ok=False,
        duration_ok=False,
        isrc_ok=False,
        version_ok=False,
        confidence="reject",
        reasons=("downloaded_file_not_found",),
    )
    return empty, result


def _download_choice(
    work: _Work,
    track: Track,
) -> tuple[int | None, Candidate | None, VerifyResult | None, str]:
    if track.source.casefold() == "apple":
        return _apple_choice(work, track)
    track_id = _as_int(track.source_track_id)
    if track_id is None:
        return None, None, None, "unmatched"
    return track_id, None, None, "download"


def _apple_choice(
    work: _Work,
    track: Track,
) -> tuple[int | None, Candidate | None, VerifyResult | None, str]:
    if work.search is None:
        return None, None, None, "unmatched"
    passing: list[tuple[Candidate, VerifyResult]] = []
    borderline: list[tuple[Candidate, VerifyResult]] = []
    for candidate in work.search(track) or []:
        result = verify(track, candidate)
        if result.confidence == "confirmed":
            passing.append((candidate, result))
        elif result.confidence == "review":
            borderline.append((candidate, result))
    if len(passing) > 1 or borderline:
        candidate, result = (passing or borderline)[0]
        if len(passing) > 1:
            result = replace(result, reasons=(*result.reasons, "multiple_search_matches"))
        return None, candidate, result, "review"
    if len(passing) == 1:
        candidate, result = passing[0]
        track_id = _as_int(candidate.id)
        if track_id is None:
            return None, candidate, result, "unmatched"
        return track_id, candidate, result, "download"
    return None, None, None, "unmatched"


def _local(work: _Work, track: Track) -> tuple[str, Candidate | None, VerifyResult | None, bool]:
    """Return match state plus whether every library row pointed at a missing file."""
    if work.library is None:
        return "none", None, None, False
    stale = False
    live: list[Candidate] = []
    for candidate in work.library(track) or []:
        path = nfc_path(candidate.path)
        if not path or not work.file_exists(path):
            stale = True
            continue
        live.append(candidate)
    state, chosen, result = _best(track, live)
    if state != "none":
        return state, chosen, result, False
    return "none", None, None, stale


def _plex_library(
    work: _Work,
    track: Track,
) -> tuple[str, Track | None, Candidate | None, VerifyResult | None] | None:
    finder = getattr(work.sink, "find", None)
    if finder is None:
        return None
    try:
        found = list(finder(track) or [])
    except Exception as exc:
        if not _is_plex_error(exc):
            raise
        work.governor.halt("plex_unavailable")
        return None
    if not found:
        return None
    state, candidate, result = _judge(track, [candidate_from_track(item) for item in found])
    if state == "none":
        return None
    chosen = None
    if candidate is not None:
        chosen = next((item for item in found if item.source_track_id == candidate.id), found[0])
    return state, chosen, candidate, result


def _judge(
    track: Track,
    candidates: list[Candidate],
) -> tuple[str, Candidate | None, VerifyResult | None]:
    confirmed: list[tuple[Candidate, VerifyResult]] = []
    review: list[tuple[Candidate, VerifyResult]] = []
    for candidate in candidates:
        result = verify(track, candidate)
        if result.confidence == "confirmed":
            confirmed.append((candidate, result))
        elif result.confidence == "review":
            review.append((candidate, result))
    if len(confirmed) > 1 or review:
        pair = confirmed[0] if confirmed else review[0]
        candidate, result = pair
        if len(confirmed) > 1:
            result = replace(result, reasons=(*result.reasons, "multiple_plex_matches"))
        return "review", candidate, result
    if len(confirmed) == 1:
        return "confirmed", confirmed[0][0], confirmed[0][1]
    return "none", None, None


def _best(
    track: Track,
    candidates: list[Candidate],
) -> tuple[str, Candidate | None, VerifyResult | None]:
    review: tuple[Candidate, VerifyResult] | None = None
    for candidate in candidates:
        result = verify(track, candidate)
        if result.confidence == "confirmed":
            return "confirmed", candidate, result
        if result.confidence == "review" and review is None:
            review = (candidate, result)
    if review is not None:
        return "review", review[0], review[1]
    return "none", None, None


def _same_isrc_on_plex(track: Track, plex_tracks: list[Track]) -> bool:
    code = isrc_key(track.isrc)
    if not code:
        return False
    return any(isrc_key(item.isrc) == code for item in plex_tracks)


def _prior(placed: list[_Placed], track: Track) -> _Placed | None:
    for item in placed:
        if same_recording(track, item.track):
            return item
    return None


def _keep(
    work: _Work,
    report: PlaylistReport,
    placed: list[_Placed],
    track: Track,
    name_norm: str,
    action: str,
    confidence: str,
    status: str,
    candidate: Candidate | None = None,
    result: VerifyResult | None = None,
    *,
    bucket: str | None = None,
    already_local: bool = False,
    last_failure_day: str | None = None,
    notes: tuple[str, ...] = (),
    candidate_source: str | None = None,
) -> dict[str, Any]:
    entry = _entry(
        track,
        action,
        confidence,
        candidate,
        result,
        notes=notes,
        candidate_source=candidate_source,
    )
    if status:
        entry["status"] = status
    report.tracks.append(entry)
    placed.append(_Placed(track, action, entry))
    if bucket == "added":
        work.report.added.append(entry)
    elif bucket == "needs_review":
        report.needs_review.append(entry)
        work.report.needs_review.append(entry)
    elif bucket == "unobtainable":
        report.unobtainable += 1
        work.report.unobtainable.append(entry)
    elif bucket == "unmatched":
        report.unmatched += 1
        work.report.unmatched.append(entry)
    if already_local:
        report.already_local += 1
    if status != "seen":
        work.ledger.set_status(
            track,
            name_norm,
            status,
            seen_at=work.seen_at,
            last_failure_day=last_failure_day,
        )
    return entry


_APPEND_OK = {"added", "already_present"}
_PLEX_ERRORS = {"refused_smart", "unmapped_path", "failed"}
_APPEND_ACCEPTS_PATHS: dict[type[Any], bool] = {}


def _append_accepts_paths(sink: Any) -> bool:
    kind = type(sink)
    cached = _APPEND_ACCEPTS_PATHS.get(kind)
    if cached is not None:
        return cached
    try:
        parameters = inspect.signature(sink.append).parameters
    except (TypeError, ValueError):
        accepts = True
    else:
        accepts = "paths" in parameters or any(
            item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
        )
    _APPEND_ACCEPTS_PATHS[kind] = accepts
    return accepts


def _sink_append(work: _Work, name: str, tracks: list[Track], paths: list[str | None]) -> Any:
    if _append_accepts_paths(work.sink):
        return work.sink.append(name, tracks, paths=paths)
    return work.sink.append(name, tracks)


def _result_status(result: Any) -> str:
    if result is None:
        return "added"
    status = getattr(result, "status", None)
    if isinstance(status, str) and status:
        return status
    return "added"


def _result_rating(result: Any) -> str | None:
    if result is None:
        return None
    keys = getattr(result, "rating_keys", None) or ()
    if not keys:
        return None
    first = keys[0]
    text = "" if first is None else str(first)
    return text or None


def _drop_entry(bucket: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    for index, item in enumerate(bucket):
        if item is entry:
            del bucket[index]
            return


def _sync_added_then_removed(
    work: _Work,
    track: Track,
    name_norm: str,
    plex_tracks: list[Track],
) -> bool:
    """True when sync added this rating key and the playlist no longer has it."""
    row = work.ledger.get_track(track.source, track.source_track_id, name_norm)
    if row is None:
        return False
    key = row.get("plex_rating_key")
    if key is None or str(key) == "":
        return False
    rating_key = str(key)
    if rating_key not in work.ledger.plex_added_keys(name_norm):
        return False
    present = {item.source_track_id for item in plex_tracks}
    return rating_key not in present


def _note_removed(
    work: _Work,
    report: PlaylistReport,
    placed: list[_Placed],
    track: Track,
) -> None:
    entry = _entry(track, "skip_removed", "confirmed", None, None, notes=("removed_in_plex",))
    entry["status"] = "removed_in_plex"
    report.tracks.append(entry)
    report.removed_in_plex += 1
    work.report.removed_in_plex.append(entry)
    placed.append(_Placed(track, "skip_removed", entry))


def _finish_append(
    work: _Work,
    entry: dict[str, Any],
    track: Track,
    name_norm: str,
    result: Any,
    *,
    report: PlaylistReport,
    local_path: str | None,
    pending_status: str,
) -> None:
    status = _result_status(result)
    rating = _result_rating(result)
    if status in _APPEND_OK:
        work.ledger.set_status(
            track,
            name_norm,
            "added",
            seen_at=work.seen_at,
            plex_rating_key=rating,
            local_path=local_path,
        )
        return
    _drop_entry(work.report.added, entry)
    if status == "removed_in_plex":
        entry["action"] = "skip_removed"
        entry["status"] = "removed_in_plex"
        entry["reasons"] = ["removed_in_plex"]
        report.removed_in_plex += 1
        work.report.removed_in_plex.append(entry)
        if rating:
            work.ledger.set_plex_rating_key(track, name_norm, rating)
        return
    if status == "pending_plex":
        entry["status"] = "pending_plex"
        work.report.pending_plex.append(entry)
        work.ledger.set_status(
            track,
            name_norm,
            pending_status,
            seen_at=work.seen_at,
            local_path=local_path,
        )
        return
    if status == "dry_run":
        entry["status"] = "dry_run"
        return
    entry["status"] = status
    work.report.plex_errors.append(entry)
    if status in _PLEX_ERRORS:
        work.ledger.set_status(
            track,
            name_norm,
            pending_status,
            seen_at=work.seen_at,
            local_path=local_path,
        )


def _file_is_missing(work: _Work, local_path: str) -> bool:
    return not local_path or not work.file_exists(local_path)


def _note_file_missing(
    work: _Work,
    report: PlaylistReport,
    placed: list[_Placed],
    track: Track,
) -> None:
    entry = _entry(track, "review", "review", None, None, notes=("file_missing",))
    entry["status"] = "needs_review"
    report.tracks.append(entry)
    report.needs_review.append(entry)
    work.report.needs_review.append(entry)
    placed.append(_Placed(track, "review", entry))


def _retry_saved_file(
    work: _Work,
    group: _Group,
    report: PlaylistReport,
    union: list[Track],
    placed: list[_Placed],
    track: Track,
    name_norm: str,
    row: dict[str, Any],
) -> bool:
    """Retry a saved file into Plex. A missing download is reviewed, not queued."""
    status = str(row["status"])
    local_path = str(row.get("local_path") or "")
    if status == "downloaded":
        union.append(track)
        _replay_append(work, group, report, placed, track, name_norm, local_path, "downloaded")
        return True
    if status == "matched_local" and local_path and work.file_exists(local_path):
        union.append(track)
        _replay_append(work, group, report, placed, track, name_norm, local_path, "matched_local")
        return True
    return False


def _replay_append(
    work: _Work,
    group: _Group,
    report: PlaylistReport,
    placed: list[_Placed],
    track: Track,
    name_norm: str,
    local_path: str,
    pending_status: str,
) -> None:
    if _file_is_missing(work, local_path):
        _note_file_missing(work, report, placed, track)
        return
    entry = _entry(track, "append", "confirmed", None, None)
    report.tracks.append(entry)
    placed.append(_Placed(track, "append", entry))
    if work.cfg.dry_run:
        entry["status"] = "pending_plex"
        work.report.pending_plex.append(entry)
        return
    entry["status"] = "added"
    work.report.added.append(entry)
    result = _sink_append(work, group.name, [track], [local_path])
    _finish_append(
        work,
        entry,
        track,
        name_norm,
        result,
        report=report,
        local_path=local_path,
        pending_status=pending_status,
    )


def _entry(
    track: Track,
    action: str,
    confidence: str,
    candidate: Candidate | None,
    result: VerifyResult | None,
    notes: tuple[str, ...] = (),
    *,
    candidate_source: str | None = None,
) -> dict[str, Any]:
    reasons = [] if result is None else list(result.reasons)
    reasons.extend(notes)
    return {
        "source": track.source,
        "source_track": track.source_view(),
        "matched_candidate": None if candidate is None else candidate.to_dict(),
        "fields_matched": [] if result is None else result.fields_matched(),
        "confidence": confidence,
        "action": action,
        "reasons": reasons,
        "candidate_source": candidate_source,
    }


def _as_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class _LibraryHandle:
    """One library.db read for a cycle. Opened on the first ISRC lookup."""

    def __init__(self) -> None:
        self._db: Any | None = None

    def __call__(self, track: Track) -> list[Candidate]:
        if not track.isrc:
            return []
        if self._db is None:
            self._db = open_library_db()
        return library_candidates(self._db, track)

    def close(self) -> None:
        database = self._db
        self._db = None
        if database is not None:
            database.close()


def open_library_db() -> Any:
    """Open library.db for one read. The caller closes it."""
    from pathlib import Path

    from tidal_dl.helper.library_db import LibraryDB
    from tidal_dl.helper.path import path_config_base

    database = LibraryDB(Path(path_config_base()) / "library.db")
    database.open()
    return database


def library_candidates(db: Any, track: Track) -> list[Candidate]:
    """ISRC lookup against an open library database. Closes nothing."""
    if not track.isrc or not hasattr(db, "tracks_by_isrc"):
        return []
    rows = db.tracks_by_isrc(track.isrc) or []
    return [candidate_from_mapping(dict(row)) for row in rows if row]
