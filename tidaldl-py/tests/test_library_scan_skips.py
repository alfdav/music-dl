"""Local library scan must skip NAS trash and system directories."""

from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.library_scanner import (
    is_skipped_scan_dir,
    path_has_skipped_scan_dir,
    scan_directory,
)

SKIPPED_DIR_NAMES = (
    "#recycle",
    "#Recycle",
    "@eaDir",
    "@tmp",
    "#snapshot",
    "$RECYCLE.BIN",
    "Recycle.bin",
    ".Trash",
    ".Trashes",
    "lost+found",
)


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\x00\x00" * 100)


def _write_mp3_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3")


class TestSkippedScanDirNames:
    @pytest.mark.parametrize("name", SKIPPED_DIR_NAMES)
    def test_skips_trash_and_system_dir_names(self, name: str) -> None:
        assert is_skipped_scan_dir(name) is True

    def test_does_not_skip_ordinary_album_or_artist_names(self) -> None:
        assert is_skipped_scan_dir("Recycled Hits") is False
        assert is_skipped_scan_dir("Horizon Chase") is False
        assert is_skipped_scan_dir("recycle") is False

    def test_path_skip_is_directory_component_not_title(self, tmp_path: Path) -> None:
        keep = tmp_path / "Horizon Chase" / "Soundtrack" / "08 Menu Groove Edit.wav"
        recycle = tmp_path / "#recycle" / "Soundtrack" / "01 Top Gear - Horizon Chase.wav"
        titled = tmp_path / "Artist" / "Recycled Hits" / "recycle in the title.wav"
        file_named = tmp_path / "Artist" / "Album" / "recycle.bin"

        assert path_has_skipped_scan_dir(keep) is False
        assert path_has_skipped_scan_dir(recycle) is True
        assert path_has_skipped_scan_dir(tmp_path / "#Recycle" / "12 Retro Race.wav") is True
        assert path_has_skipped_scan_dir(titled) is False
        assert path_has_skipped_scan_dir(file_named) is False


class TestScanDirectorySkips:
    def test_scan_directory_does_not_examine_recycle_files(self, tmp_path: Path) -> None:
        keep = tmp_path / "Artist" / "Album" / "keep.mp3"
        trash = tmp_path / "#recycle" / "Album" / "08 Menu Groove Edit.mp3"
        _write_mp3_stub(keep)
        _write_mp3_stub(trash)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        result = scan_directory(tmp_path, db, dry_run=True)
        db.close()

        assert result.files_scanned == 1


class TestBackgroundScanSkips:
    def _patch_scan(self, monkeypatch, tmp_path: Path, library_dir: Path) -> None:
        import tidal_dl.gui.api.library as library_api

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(library_dir), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
        monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)

    def test_background_scan_does_not_index_recycle_as_artist(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        import tidal_dl.gui.api.library as library_api

        library_dir = tmp_path / "music"
        keep = library_dir / "Horizon Chase" / "Soundtrack" / "01 Top Gear - Horizon Chase.wav"
        recycle = library_dir / "#recycle" / "Soundtrack" / "08 Menu Groove Edit.wav"
        recycle_case = library_dir / "#Recycle" / "Soundtrack" / "12 Retro Race.wav"
        titled = library_dir / "Artist" / "Recycled Hits" / "recycle in the title.wav"
        hidden = library_dir / ".hidden-album" / "dotfile.wav"
        _write_wav(keep)
        _write_wav(recycle)
        _write_wav(recycle_case)
        _write_wav(titled)
        _write_wav(hidden)

        self._patch_scan(monkeypatch, tmp_path, library_dir)
        library_api._background_scan(rescan=False)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        artist_names = {row["artist"] for row in db.artists_page(limit=200)[0]}

        assert str(keep) in paths
        assert str(titled) in paths
        assert str(hidden) in paths
        assert str(recycle) not in paths
        assert str(recycle_case) not in paths
        assert "#recycle" not in {name.casefold() for name in artist_names}
        db.close()

    def test_background_scan_drops_already_indexed_recycle_rows(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        import tidal_dl.gui.api.library as library_api

        library_dir = tmp_path / "music"
        keep = library_dir / "Horizon Chase" / "Soundtrack" / "keep.wav"
        recycle = library_dir / "#recycle" / "Soundtrack" / "08 Menu Groove Edit.wav"
        _write_wav(keep)
        _write_wav(recycle)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        db.record(
            str(recycle),
            status="tagged",
            artist="#recycle",
            title="08 Menu Groove Edit",
            album="#recycle",
        )
        db.commit()
        db.close()

        self._patch_scan(monkeypatch, tmp_path, library_dir)
        library_api._background_scan(rescan=False)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = db.known_paths()
        artist_names = {row["artist"] for row in db.artists_page(limit=200)[0]}

        assert str(keep) in paths
        assert str(recycle) not in paths
        assert "#recycle" not in {name.casefold() for name in artist_names}
        db.close()
