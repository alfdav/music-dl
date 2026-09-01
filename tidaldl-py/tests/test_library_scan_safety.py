"""Library sync must not destroy cache rows or hide progress."""

from __future__ import annotations

import os
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.library_scanner import (
    drop_skipped_scan_paths,
    is_skipped_scan_dir,
    path_has_skipped_scan_dir,
    scan_directory,
    visible_scanned_path_sql,
)

PRIOR_CACHE_ROWS = 11_974
LARGE_RECYCLE_ROWS = 3_000
MAC_GOOD_COMPLETE_ROWS = 8_554
MAC_SKIPPED_ROWS = 3_420
INCOMPLETE_REPAIR_ROWS = 3
SCAN_TIME_BUDGET_SEC = 30.0


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\x00\x00" * 8)


def _hardlink_wav(sample: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.link(sample, dest)


def _seed_row(
    db: LibraryDB,
    path: Path | str,
    *,
    artist: str = "Artist",
    title: str = "Title",
    album: str = "Album",
    status: str = "tagged",
    codec: str | None = "pcm",
    metadata_complete: bool = True,
) -> None:
    db.record(
        str(path),
        status=status,
        artist=artist,
        title=title,
        album=album,
        duration=1,
        quality="WAV",
        fmt="WAV",
        codec=codec,
        metadata_complete=metadata_complete,
    )


def _track_directory_descent(monkeypatch) -> list[Path]:
    visited: list[Path] = []
    real_scandir = os.scandir

    def tracking_scandir(path):
        visited.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", tracking_scandir)
    return visited


def _descended_into_skipped(visited: list[Path]) -> bool:
    return any(
        is_skipped_scan_dir(path.name) or path_has_skipped_scan_dir(path / "dummy")
        for path in visited
    )


@pytest.fixture
def library_scan(monkeypatch, tmp_path):
    import tidal_dl.gui.api.library as library_api

    library_dir = tmp_path / "music"
    library_dir.mkdir()

    class FakeSettings:
        data = SimpleNamespace(download_base_path=str(library_dir), scan_paths="")

    monkeypatch.setattr(library_api, "Settings", FakeSettings)
    monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
    monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
    monkeypatch.setattr(library_api, "_album_cards", lambda db, *args, **kwargs: [])
    monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)
    monkeypatch.setattr(library_api, "_has_local_art", lambda path: False)
    monkeypatch.setattr(
        library_api,
        "_read_metadata",
        lambda path, scan_dirs=None: {
            "path": str(path),
            "name": path.stem,
            "artist": path.parts[-3] if len(path.parts) >= 3 else "Artist",
            "album": path.parts[-2] if len(path.parts) >= 2 else "Album",
            "duration": 1,
            "isrc": "",
            "genre": None,
            "quality": "WAV",
            "format": "WAV",
            "codec": "pcm",
            "metadata_complete": True,
            "is_local": True,
        },
    )
    library_api._scan_running = False
    library_api._scan_progress = {
        "scanned": 0,
        "total": 0,
        "done": True,
        "phase": "idle",
        "error": None,
    }
    yield library_api, library_dir, tmp_path
    library_api._scan_running = False
    library_api._scan_progress = {
        "scanned": 0,
        "total": 0,
        "done": True,
        "phase": "idle",
        "error": None,
    }


def _run_background_scan(library_api, *, rescan: bool = False) -> None:
    library_api._scan_running = True
    library_api._background_scan(rescan)


class TestSkippedDirectoryPolicyIsCentralized:
    def test_gui_and_cli_reuse_scanner_skip_helpers(self) -> None:
        import inspect

        from tidal_dl.cli import isrc_tag
        from tidal_dl.gui.api import library as library_api
        from tidal_dl.gui.services import download_job_service

        for source in (
            inspect.getsource(library_api),
            inspect.getsource(isrc_tag),
            inspect.getsource(download_job_service),
        ):
            assert "_SKIPPED_SCAN_DIR_NAMES" not in source
            assert "is_skipped_scan_dir" in source


class TestLargeTreePrunesTrashWithoutDescent:
    def test_large_nas_tree_never_descends_into_recycle_or_trash(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, library_dir, tmp_path = library_scan
        sample = tmp_path / "sample.wav"
        _write_wav(sample)
        keep = library_dir / "Horizon Chase" / "Soundtrack" / "keep.wav"
        recycle = library_dir / "#recycle" / "deep" / "nested" / "08 Menu Groove Edit.wav"
        trash = library_dir / ".Trash" / "deleted" / "old.wav"
        _hardlink_wav(sample, keep)
        for index in range(400):
            _hardlink_wav(
                sample,
                library_dir / "#recycle" / f"bucket{index // 50}" / f"trashed{index:04d}.wav",
            )
        _hardlink_wav(sample, recycle)
        _hardlink_wav(sample, trash)

        visited = _track_directory_descent(monkeypatch)
        _run_background_scan(library_api)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        db.close()

        assert str(keep) in paths
        assert str(recycle) not in paths
        assert str(trash) not in paths
        assert not _descended_into_skipped(visited)


class TestInterruptedScanPreservesCache:
    def test_failed_scan_does_not_delete_prior_good_or_recycle_rows(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, library_dir, tmp_path = library_scan
        keep = library_dir / "Artist" / "Album" / "keep.wav"
        recycle = library_dir / "#recycle" / "Album" / "stale.wav"
        _write_wav(keep)
        _write_wav(recycle)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        for index in range(80):
            _seed_row(db, tmp_path / "prior" / f"track{index:04d}.wav", title=f"Prior {index}")
        _seed_row(db, recycle, artist="#recycle", title="08 Menu Groove Edit")
        db.commit()
        prior_count = len(db.known_paths())
        db.close()
        assert prior_count == 81

        def explode_walk(*args, **kwargs):
            raise RuntimeError("scan interrupted")

        monkeypatch.setattr(os, "walk", explode_walk)
        _run_background_scan(library_api)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        db.close()

        assert len(paths) == prior_count
        assert str(recycle) in paths
        status = library_api.scan_status()
        assert status["scanning"] is False
        assert status["done"] is True
        assert status["phase"] == "error"
        assert status.get("error")

    def test_scan_directory_failure_does_not_drop_skipped_rows(self, tmp_path, monkeypatch) -> None:
        recycle = tmp_path / "#recycle" / "Album" / "stale.mp3"
        recycle.parent.mkdir(parents=True, exist_ok=True)
        recycle.write_bytes(b"ID3")

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _seed_row(db, recycle, artist="#recycle")
        db.commit()

        def explode_walk(*args, **kwargs):
            raise RuntimeError("walk failed")

        monkeypatch.setattr(os, "walk", explode_walk)
        with pytest.raises(RuntimeError, match="walk failed"):
            scan_directory(tmp_path, db)

        assert str(recycle) in db.known_paths()
        db.close()


class TestSuccessfulSweepHappensAfterCompletion:
    def test_stale_recycle_rows_remain_during_walk_and_drop_after_success(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, library_dir, tmp_path = library_scan
        keep = library_dir / "Horizon Chase" / "Soundtrack" / "keep.wav"
        recycle = library_dir / "#recycle" / "Soundtrack" / "08 Menu Groove Edit.wav"
        _write_wav(keep)
        _write_wav(recycle)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _seed_row(db, recycle, artist="#recycle", title="08 Menu Groove Edit")
        db.commit()
        db.close()

        seen_during_walk: list[int] = []
        real_walk = os.walk

        def walk_and_count(*args, **kwargs):
            mid = LibraryDB(tmp_path / "library.db")
            mid.open()
            seen_during_walk.append(len(mid.known_paths()))
            assert str(recycle) in mid.known_paths()
            mid.close()
            yield from real_walk(*args, **kwargs)

        monkeypatch.setattr(os, "walk", walk_and_count)
        _run_background_scan(library_api)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        db.close()

        assert seen_during_walk
        assert seen_during_walk[0] >= 1
        assert str(keep) in paths
        assert str(recycle) not in paths

    def test_fingerprint_fast_path_still_sweeps_stale_recycle_rows(
        self, library_scan, monkeypatch,
    ) -> None:
        import json

        library_api, library_dir, tmp_path = library_scan
        keep = library_dir / "Horizon Chase" / "Soundtrack" / "keep.wav"
        recycle = library_dir / "#recycle" / "Soundtrack" / "08 Menu Groove Edit.wav"
        _write_wav(keep)
        _write_wav(recycle)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        _seed_row(db, keep, artist="Horizon Chase", title="keep")
        _seed_row(db, recycle, artist="#recycle", title="08 Menu Groove Edit")
        finger = json.dumps({
            "dirs": [str(library_dir)],
            "mtimes": [os.stat(str(library_dir)).st_mtime],
            "known_count": 2,
        }, sort_keys=True)
        db.set_meta("scan_fingerprint", finger)
        db.commit()
        db.close()

        walked = {"count": 0}
        real_walk = os.walk

        def counting_walk(*args, **kwargs):
            walked["count"] += 1
            yield from real_walk(*args, **kwargs)

        monkeypatch.setattr(os, "walk", counting_walk)
        _run_background_scan(library_api)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        db.close()

        assert walked["count"] == 0
        assert str(keep) in paths
        assert str(recycle) not in paths

    def test_reconcile_does_not_read_skipped_directory_files(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, library_dir, tmp_path = library_scan
        keep = library_dir / "Artist" / "Album" / "keep.wav"
        recycle = library_dir / "#recycle" / "Album" / "stale.wav"
        _write_wav(keep)
        _write_wav(recycle)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        db.record(
            str(keep),
            status="tagged",
            artist="Unknown Artist",
            title="Track 01",
            album="Unknown Album",
            metadata_complete=False,
        )
        db.record(
            str(recycle),
            status="tagged",
            artist="#recycle",
            title="Track 02",
            album="Unknown Album",
            metadata_complete=False,
        )
        db.commit()
        db.close()

        read_paths: list[str] = []
        original_read = library_api._read_metadata

        def tracking_read(path, scan_dirs=None):
            read_paths.append(str(path))
            return original_read(path, scan_dirs)

        monkeypatch.setattr(library_api, "_read_metadata", tracking_read)
        _run_background_scan(library_api)

        assert str(recycle) not in read_paths
        assert any(path.endswith("keep.wav") for path in read_paths)


class TestScanStatusIsTruthful:
    def test_status_exposes_named_phase_before_any_file_is_found(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, _library_dir, _tmp_path = library_scan
        entered = threading.Event()
        release = threading.Event()
        snapshots: list[dict] = []

        def blocking_backup(db_path: Path) -> Path:
            snapshots.append(library_api.scan_status())
            entered.set()
            assert release.wait(timeout=2)
            return Path(str(db_path) + ".bak")

        monkeypatch.setattr(library_api, "_backup_library_db", blocking_backup)

        thread = threading.Thread(target=_run_background_scan, args=(library_api,), daemon=True)
        thread.start()
        assert entered.wait(timeout=2)
        snapshots.append(library_api.scan_status())
        release.set()
        thread.join(timeout=5)
        assert not thread.is_alive()

        assert snapshots
        for snapshot in snapshots:
            assert snapshot["scanning"] is True
            assert snapshot["done"] is False
            assert snapshot["phase"]
            assert snapshot["phase"] != "idle"
            assert snapshot["phase"] not in {"done", "error"}
        assert snapshots[0]["scanned"] == 0
        assert snapshots[0]["total"] == 0

        final = library_api.scan_status()
        assert final["scanning"] is False
        assert final["done"] is True
        assert final["phase"] == "done"

    def test_discovery_increments_scanned_while_total_is_unknown(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, library_dir, _tmp_path = library_scan
        for index in range(6):
            _write_wav(library_dir / "Artist" / f"Album{index}" / f"track{index}.wav")

        snapshots: list[dict] = []
        real_walk = os.walk

        def snapshot_walk(*args, **kwargs):
            for item in real_walk(*args, **kwargs):
                snapshots.append(dict(library_api.scan_status()))
                yield item

        monkeypatch.setattr(os, "walk", snapshot_walk)
        _run_background_scan(library_api)

        discovering = [row for row in snapshots if row.get("phase") == "discovering"]
        assert discovering
        assert any(row["scanned"] > 0 for row in discovering)
        assert all(row["done"] is False for row in discovering)

        final = library_api.scan_status()
        assert final["done"] is True
        assert final["phase"] == "done"
        assert final["scanning"] is False

    def test_scan_status_endpoint_includes_phase(self, library_scan, client) -> None:
        _library_api, _library_dir, _tmp_path = library_scan
        response = client.get("/api/library/scan/status", headers=client._host_header)
        assert response.status_code == 200
        payload = response.json()
        assert "phase" in payload
        assert "scanned" in payload
        assert "total" in payload
        assert "done" in payload
        assert "scanning" in payload


class TestConcurrentReadsDuringScan:
    def test_prior_rows_remain_readable_while_scan_walks(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, library_dir, tmp_path = library_scan
        keep = library_dir / "Artist" / "Album" / "new.wav"
        _write_wav(keep)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        for index in range(40):
            _seed_row(db, tmp_path / "cached" / f"old{index:02d}.wav", title=f"Cached {index}")
        db.commit()
        db.close()

        entered = threading.Event()
        release = threading.Event()
        real_walk = os.walk

        def blocking_walk(*args, **kwargs):
            entered.set()
            assert release.wait(timeout=2)
            yield from real_walk(*args, **kwargs)

        monkeypatch.setattr(os, "walk", blocking_walk)
        thread = threading.Thread(target=_run_background_scan, args=(library_api,), daemon=True)
        thread.start()
        assert entered.wait(timeout=2)

        started = time.monotonic()
        reader = LibraryDB(tmp_path / "library.db")
        reader.open()
        rows, total = reader.tracks_page(limit=50)
        reader.close()
        elapsed = time.monotonic() - started

        release.set()
        thread.join(timeout=5)
        assert not thread.is_alive()

        assert total == 40
        assert len(rows) == 40
        assert elapsed < 1.0


class TestWriterLockNotHeldAcrossFilesystem:
    def test_metadata_reads_happen_outside_an_open_write_transaction(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, library_dir, _tmp_path = library_scan
        for index in range(3):
            _write_wav(library_dir / "Artist" / "Album" / f"track{index}.wav")

        state = {"dirty": False, "metadata_while_dirty": False}
        original_record = LibraryDB.record
        original_commit = LibraryDB.commit

        def tracking_record(self, *args, **kwargs):
            state["dirty"] = True
            return original_record(self, *args, **kwargs)

        def tracking_commit(self):
            result = original_commit(self)
            state["dirty"] = False
            return result

        def tracking_metadata(path, scan_dirs=None):
            if state["dirty"]:
                state["metadata_while_dirty"] = True
            return {
                "path": str(path),
                "name": path.stem,
                "artist": "Artist",
                "album": "Album",
                "duration": 1,
                "isrc": "",
                "genre": None,
                "quality": "WAV",
                "format": "WAV",
                "codec": "pcm",
                "metadata_complete": True,
                "is_local": True,
            }

        monkeypatch.setattr(LibraryDB, "record", tracking_record)
        monkeypatch.setattr(LibraryDB, "commit", tracking_commit)
        monkeypatch.setattr(library_api, "_read_metadata", tracking_metadata)
        _run_background_scan(library_api)

        assert state["metadata_while_dirty"] is False


class TestTwelveThousandRowFixture:
    def test_sync_completes_on_12k_tree_without_recycle_descent(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, library_dir, tmp_path = library_scan
        sample = tmp_path / "sample.wav"
        _write_wav(sample)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        for index in range(PRIOR_CACHE_ROWS):
            artist = f"a{index // 120:03d}"
            album = f"album{index // 12:04d}"
            dest = library_dir / artist / album / f"track{index:05d}.wav"
            _hardlink_wav(sample, dest)
            _seed_row(db, dest, artist=artist, title=f"Track {index}")
        db.commit()
        assert len(db.known_paths()) == PRIOR_CACHE_ROWS
        db.close()

        extra_keep = library_dir / "New Artist" / "New Album" / "fresh.wav"
        _hardlink_wav(sample, extra_keep)
        for index in range(LARGE_RECYCLE_ROWS):
            _hardlink_wav(
                sample,
                library_dir / "#recycle" / f"bucket{index // 100}" / f"gone{index:05d}.wav",
            )

        visited = _track_directory_descent(monkeypatch)
        started = time.monotonic()
        _run_background_scan(library_api)
        elapsed = time.monotonic() - started

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        db.close()
        status = library_api.scan_status()

        assert elapsed < SCAN_TIME_BUDGET_SEC
        assert len(paths) == PRIOR_CACHE_ROWS + 1
        assert str(extra_keep) in paths
        assert not any(path_has_skipped_scan_dir(path) for path in paths)
        assert not _descended_into_skipped(visited)
        assert status["done"] is True
        assert status["phase"] == "done"
        assert status["scanning"] is False

    def test_complete_and_recycle_rows_are_not_opened_for_tag_repair(
        self, library_scan, monkeypatch,
    ) -> None:
        library_api, library_dir, tmp_path = library_scan
        sample = tmp_path / "sample.wav"
        _write_wav(sample)

        complete_paths: list[str] = []
        recycle_paths: list[str] = []
        incomplete_paths: list[str] = []

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        for index in range(MAC_GOOD_COMPLETE_ROWS):
            artist = f"a{index // 120:03d}"
            album = f"album{index // 12:04d}"
            dest = library_dir / artist / album / f"song{index:05d}.wav"
            _hardlink_wav(sample, dest)
            # Mac v7 reset: tagged identity is already present, flag is 0.
            _seed_row(
                db,
                dest,
                artist=artist,
                title=f"Song {index}",
                album=album,
                codec=None,
                metadata_complete=False,
            )
            complete_paths.append(str(dest))
        for index in range(MAC_SKIPPED_ROWS):
            dest = library_dir / "#recycle" / f"bucket{index // 100}" / f"gone{index:05d}.wav"
            _hardlink_wav(sample, dest)
            _seed_row(
                db,
                dest,
                artist="#recycle",
                title="Track 01",
                album="Unknown Album",
                codec=None,
                metadata_complete=False,
            )
            recycle_paths.append(str(dest))
        for index in range(INCOMPLETE_REPAIR_ROWS):
            dest = library_dir / "Needs Repair" / "Unknown Album" / f"track{index:02d}.wav"
            _hardlink_wav(sample, dest)
            _seed_row(
                db,
                dest,
                artist="Unknown Artist",
                title=f"Track {index:02d}",
                album="Unknown Album",
                status="needs_isrc",
                codec=None,
                metadata_complete=False,
            )
            incomplete_paths.append(str(dest))
        db.commit()
        worklist = db.metadata_repair_worklist()
        db.close()

        opened: list[str] = []
        original_read = library_api._read_metadata
        phases_at_open: list[str] = []

        def tracking_read(path, scan_dirs=None):
            opened.append(str(path))
            phases_at_open.append(library_api.scan_status().get("phase"))
            return original_read(path, scan_dirs)

        mutagen_opened: list[str] = []
        original_mutagen = library_api.MutagenFile

        def tracking_mutagen(path, *args, **kwargs):
            mutagen_opened.append(str(path))
            return original_mutagen(path, *args, **kwargs)

        phase_order: list[str] = []
        original_update = library_api._update_scan_progress

        def tracking_progress(**overrides):
            phase = overrides.get("phase")
            if phase and (not phase_order or phase_order[-1] != phase):
                phase_order.append(phase)
            return original_update(**overrides)

        monkeypatch.setattr(library_api, "_read_metadata", tracking_read)
        monkeypatch.setattr(library_api, "MutagenFile", tracking_mutagen)
        monkeypatch.setattr(library_api, "_update_scan_progress", tracking_progress)

        _run_background_scan(library_api)

        complete = set(complete_paths)
        recycle = set(recycle_paths)
        incomplete = set(incomplete_paths)
        opened_set = set(opened)
        mutagen_set = set(mutagen_opened)

        assert not complete.intersection(opened_set)
        assert not complete.intersection(mutagen_set)
        assert not recycle.intersection(opened_set)
        assert not recycle.intersection(mutagen_set)
        assert opened_set == incomplete
        assert {row["path"] for row in worklist} == incomplete
        assert "discovering" in phase_order
        if "repairing" in phase_order:
            assert phase_order.index("discovering") < phase_order.index("repairing")
        assert not any(phase == "repairing" and path in complete for path, phase in zip(opened, phases_at_open))


def test_drop_skipped_scan_paths_still_centralized() -> None:
    assert callable(drop_skipped_scan_paths)
    assert is_skipped_scan_dir("#recycle")
    assert is_skipped_scan_dir(".Trash")
    sql = visible_scanned_path_sql()
    assert "/#recycle/" in sql
    assert "/.trash/" in sql


def _seed_zeratool_recycle_library(db: LibraryDB, library_dir: Path) -> dict[str, Path]:
    """Nested NAS `#recycle` trash plus a real file and a Recycle *title*."""
    keep = (
        library_dir / "Carlos Vives" / "Clasicos de la Provincia"
        / "Carlos Vives - La Gota Fria.wav"
    )
    trash_a = (
        library_dir / "#recycle" / "High Bit Rate" / "Carlos Vives"
        / "Clasicos de la Provincia" / "Carlos Vives - La Gota Fria.wav"
    )
    trash_b = (
        library_dir / "#recycle" / "High Bit Rate" / "Carlos Vives"
        / "Carlos Vives - Clasicos de la Provincia" / "01 - La Gota Fria.wav"
    )
    titled = library_dir / "SLEEPARCHIVE" / "Recycle" / "Recycle.wav"
    horizon_dir = (
        library_dir / "#recycle" / "High Bit Rate" / "Barry Leitch"
        / "Barry Leitch - Top Gear - Horizon Chase"
    )
    _write_wav(keep)
    _write_wav(trash_a)
    _write_wav(trash_b)
    _write_wav(titled)
    horizon = []
    for index in range(3):
        dest = horizon_dir / f"{index + 1:02d} Menu Groove Edit.wav"
        _write_wav(dest)
        horizon.append(dest)
        _seed_row(
            db,
            dest,
            artist="#recycle",
            title=dest.stem,
            album="Barry Leitch - Top Gear - Horizon Chase",
        )
    _seed_row(db, keep, artist="Carlos Vives", title="La Gota Fria", album="Clasicos de la Provincia")
    _seed_row(db, trash_a, artist="Carlos Vives", title="La Gota Fria", album="Clasicos de la Provincia")
    _seed_row(db, trash_b, artist="Carlos Vives", title="La Gota Fria", album="Clasicos de la Provincia")
    _seed_row(db, titled, artist="SLEEPARCHIVE", title="Recycle", album="Recycle")
    db.commit()
    return {
        "keep": keep,
        "trash_a": trash_a,
        "trash_b": trash_b,
        "titled": titled,
        "horizon": horizon[0],
    }


def _library_surfaces(library_api):
    library_api._invalidate_db_cache()
    return (
        library_api.library(sort="title", limit=200, offset=0, q=""),
        library_api.all_albums(q=""),
        library_api.library_search(q="Gota", type="tracks", limit=50),
        library_api.library_search(q="Horizon", type="albums", limit=50),
        library_api.library_search(q="Recycle", type="tracks", limit=50),
    )


def _assert_recycle_absent_and_title_kept(library, albums, search_gota, search_horizon, search_recycle, paths):
    track_paths = [row["path"] for row in library["tracks"]]
    assert str(paths["keep"]) in track_paths
    assert str(paths["titled"]) in track_paths
    assert str(paths["trash_a"]) not in track_paths
    assert str(paths["trash_b"]) not in track_paths
    assert str(paths["horizon"]) not in track_paths
    assert not any(path_has_skipped_scan_dir(path) for path in track_paths)
    assert "#recycle" not in {row["artist"].casefold() for row in library["tracks"]}

    gota_paths = [row["path"] for row in search_gota["tracks"]]
    assert str(paths["keep"]) in gota_paths
    assert str(paths["trash_a"]) not in gota_paths
    assert str(paths["trash_b"]) not in gota_paths

    recycle_titles = [row["name"] for row in search_recycle["tracks"]]
    assert "Recycle" in recycle_titles
    assert all(not path_has_skipped_scan_dir(row["path"]) for row in search_recycle["tracks"])

    assert not any(
        album["artist"].casefold() == "#recycle" or album["name"].casefold() == "#recycle"
        for album in albums["albums"]
    )
    assert not any("#recycle" in (album.get("cover_url") or "").casefold() for album in albums["albums"])
    assert not any("%23recycle" in (album.get("cover_url") or "").casefold() for album in albums["albums"])
    assert not any(
        album["artist"].casefold() == "#recycle" or "horizon" in album["name"].casefold()
        for album in search_horizon["albums"]
    )
    assert any(album["name"].casefold() == "recycle" for album in albums["albums"])


class TestNestedRecycleNeverReturned:
    """Leftover /Music/#recycle/... rows must not be library or album hits."""

    @pytest.fixture
    def live_library(self, monkeypatch, tmp_path):
        import tidal_dl.gui.api.library as library_api

        library_dir = tmp_path / "Music"
        library_dir.mkdir()

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(library_dir), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
        monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)
        monkeypatch.setattr(library_api, "_has_local_art", lambda path: False)
        library_api._scan_running = False
        library_api._scan_progress = {
            "scanned": 0,
            "total": 0,
            "done": True,
            "phase": "idle",
            "error": None,
        }
        library_api._invalidate_db_cache()
        yield library_api, library_dir, tmp_path
        library_api._scan_running = False
        library_api._invalidate_db_cache()

    def test_path_component_matcher_sees_nested_volume_recycle(self) -> None:
        live = (
            "/Volumes/Music/#recycle/High Bit Rate/Barry Leitch"
            "/Barry Leitch - Top Gear - Horizon Chase/01 Menu Groove Edit.wav"
        )
        keep = "/Volumes/Music/Carlos Vives/Clasicos de la Provincia/Carlos Vives - La Gota Fria.flac"
        titled = "/Volumes/Music/SLEEPARCHIVE/Recycle/Recycle.wav"
        assert path_has_skipped_scan_dir(live) is True
        assert path_has_skipped_scan_dir(keep) is False
        assert path_has_skipped_scan_dir(titled) is False

    def test_leftover_rows_hidden_before_any_scan(self, live_library) -> None:
        library_api, library_dir, tmp_path = live_library
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = _seed_zeratool_recycle_library(db, library_dir)
        db.close()

        _assert_recycle_absent_and_title_kept(*_library_surfaces(library_api), paths)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        known = db.known_paths()
        db.close()
        assert str(paths["trash_a"]) not in known
        assert str(paths["horizon"]) not in known
        assert str(paths["keep"]) in known
        assert str(paths["titled"]) in known

    def test_full_scan_does_not_index_nested_recycle(self, live_library) -> None:
        library_api, library_dir, tmp_path = live_library
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = _seed_zeratool_recycle_library(db, library_dir)
        db.close()

        _run_background_scan(library_api)
        _assert_recycle_absent_and_title_kept(*_library_surfaces(library_api), paths)

    def test_fingerprint_skip_rescan_drops_nested_recycle(self, live_library, monkeypatch) -> None:
        import json

        library_api, library_dir, tmp_path = live_library
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = _seed_zeratool_recycle_library(db, library_dir)
        finger = json.dumps({
            "dirs": [str(library_dir)],
            "mtimes": [os.stat(str(library_dir)).st_mtime],
            "known_count": len(db.known_paths()),
        }, sort_keys=True)
        db.set_meta("scan_fingerprint", finger)
        db.commit()
        db.close()

        walked = {"count": 0}
        real_walk = os.walk

        def counting_walk(*args, **kwargs):
            walked["count"] += 1
            yield from real_walk(*args, **kwargs)

        monkeypatch.setattr(os, "walk", counting_walk)
        _run_background_scan(library_api)

        assert walked["count"] == 0
        _assert_recycle_absent_and_title_kept(*_library_surfaces(library_api), paths)
