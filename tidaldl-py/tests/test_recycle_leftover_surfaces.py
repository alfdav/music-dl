"""Leftover NAS `#recycle` rows must not be library, search, or album hits.

`#recycle` is a recycle/trash path component on UGreen, Synology, and any NAS
that uses that name. Track *titles* named Recycle stay. Disk files stay.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tidal_dl.gui.api.library import _resolve_local_metadata
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.library_scanner import path_has_skipped_scan_dir


def _write_audio(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fLaC")
    return path


def _seed_row(
    db: LibraryDB,
    path: Path | str,
    *,
    artist: str,
    title: str,
    album: str,
    isrc: str | None = None,
) -> None:
    db.record(
        str(path),
        status="tagged",
        artist=artist,
        title=title,
        album=album,
        isrc=isrc,
        duration=1,
        quality="FLAC",
        fmt="FLAC",
        codec="flac",
        metadata_complete=True,
    )


def _zeratool_paths(library_dir: Path) -> dict[str, Path]:
    return {
        "untagged": _write_audio(
            library_dir / "#recycle" / "High Bit Rate" / "08 Menu Groove Edit.wav"
        ),
        "gota_live": _write_audio(
            library_dir / "Carlos Vives" / "Clasicos de la Provincia" / "La Gota Fria.flac"
        ),
        "gota_trash": _write_audio(
            library_dir
            / "#recycle"
            / "High Bit Rate"
            / "Carlos Vives"
            / "01 - La Gota Fria.flac"
        ),
        "hybrid_live_a": _write_audio(
            library_dir / "Linkin Park" / "Hybrid Theory" / "01 Papercut.flac"
        ),
        "hybrid_live_b": _write_audio(
            library_dir / "Linkin Park" / "Hybrid Theory" / "02 One Step Closer.flac"
        ),
        "titled": _write_audio(library_dir / "SLEEPARCHIVE" / "Recycle" / "Recycle.wav"),
    }


def _seed_zeratool_library(db: LibraryDB, paths: dict[str, Path]) -> None:
    _seed_row(
        db,
        paths["untagged"],
        artist="#recycle",
        title="08 Menu Groove Edit",
        album="High Bit Rate",
    )
    _seed_row(
        db,
        paths["gota_live"],
        artist="Carlos Vives",
        title="La Gota Fria",
        album="Clasicos de la Provincia",
        isrc="COC019300016",
    )
    _seed_row(
        db,
        paths["gota_trash"],
        artist="Carlos Vives",
        title="La Gota Fria",
        album="Clasicos de la Provincia",
        isrc="COC019300016",
    )
    _seed_row(
        db,
        paths["hybrid_live_a"],
        artist="Linkin Park",
        title="Papercut",
        album="Hybrid Theory",
    )
    _seed_row(
        db,
        paths["hybrid_live_b"],
        artist="Linkin Park",
        title="One Step Closer",
        album="Hybrid Theory",
    )
    for index in range(36):
        dest = _write_audio(
            paths["hybrid_live_a"].parents[2]
            / "#recycle"
            / "High Bit Rate"
            / "Hybrid Theory 20th Anniversary Edition"
            / f"{index + 1:02d} Deluxe {index}.flac"
        )
        _seed_row(
            db,
            dest,
            artist="#recycle" if index % 2 == 0 else "Mike Shinoda",
            title=f"Deluxe {index}",
            album="Hybrid Theory",
        )
    _seed_row(
        db,
        paths["titled"],
        artist="SLEEPARCHIVE",
        title="Recycle",
        album="Recycle",
    )
    db.commit()


def _patch_library_api(monkeypatch, tmp_path: Path, library_dir: Path):
    import tidal_dl.gui.api.library as library_api

    class FakeSettings:
        data = SimpleNamespace(download_base_path=str(library_dir), scan_paths="")

    monkeypatch.setattr(library_api, "Settings", FakeSettings)
    monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
    monkeypatch.setattr(library_api, "_schedule_album_enrichment", lambda: None)
    library_api._invalidate_db_cache()
    return library_api


class TestRecycleIsNeverAnArtist:
    def test_untagged_wav_under_recycle_does_not_take_folder_as_artist(self, tmp_path):
        root = tmp_path / "Music"
        track = (
            root / "#recycle" / "High Bit Rate" / "Soundtrack" / "08 Menu Groove Edit.wav"
        )

        resolved = _resolve_local_metadata(track, [root], title="", artist="", album="")

        assert resolved["artist"].casefold() != "#recycle"
        assert resolved["album"].casefold() != "#recycle"


    def test_recycle_title_outside_trash_stays(self, tmp_path):
        root = tmp_path / "Music"
        track = root / "SLEEPARCHIVE" / "Recycle" / "Recycle.wav"

        resolved = _resolve_local_metadata(
            track,
            [root],
            title="Recycle",
            artist="SLEEPARCHIVE",
            album="Recycle",
        )

        assert resolved == {
            "name": "Recycle",
            "artist": "SLEEPARCHIVE",
            "album": "Recycle",
        }


class TestZeratoolRecycleSurfaces:
    """Live 1.7.8 Zeratool 2026-08-31: leftover `#recycle` still served."""

    def test_library_artist_sort_does_not_start_with_recycle(self, tmp_path, monkeypatch):
        library_dir = tmp_path / "Music"
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = _zeratool_paths(library_dir)
        _seed_zeratool_library(db, paths)
        db.close()

        library_api = _patch_library_api(monkeypatch, tmp_path, library_dir)
        payload = library_api.library(sort="artist", limit=50, offset=0, q="")

        artists = [row["artist"] for row in payload["tracks"]]
        track_paths = [row["path"] for row in payload["tracks"]]
        assert artists
        assert artists[0].casefold() != "#recycle"
        assert "#recycle" not in {name.casefold() for name in artists}
        assert not any(path_has_skipped_scan_dir(path) for path in track_paths)
        assert str(paths["titled"]) in track_paths

    def test_search_prefers_live_gota_fria_over_recycle_twin(self, tmp_path, monkeypatch):
        from tidal_dl.gui.api import search as search_api
        from tidal_dl.gui.api.search import _serialize_track

        library_dir = tmp_path / "Music"
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = _zeratool_paths(library_dir)
        _seed_zeratool_library(db, paths)
        db.close()

        library_api = _patch_library_api(monkeypatch, tmp_path, library_dir)
        live_db = library_api._get_db()
        monkeypatch.setattr(search_api, "_get_library_db", lambda: live_db)

        album = SimpleNamespace(id=1, name="Clasicos de la Provincia", image=lambda size: "")
        track = SimpleNamespace(
            id=99,
            name="La Gota Fria",
            full_name="La Gota Fria",
            artists=[SimpleNamespace(name="Carlos Vives", id=1)],
            album=album,
            duration=180,
            audio_quality="LOSSLESS",
            isrc="COC019300016",
            media_metadata_tags=[],
        )
        result = _serialize_track(track)
        hits = search_api._serialize_track_hits([track])

        assert result["is_local"] is True
        assert result["path"] == str(paths["gota_live"])
        assert not path_has_skipped_scan_dir(result["path"])
        assert hits[0]["path"] == str(paths["gota_live"])

        local = library_api.library_search(q="Fria", type="tracks", limit=50)
        local_paths = [row["path"] for row in local["tracks"]]
        assert str(paths["gota_live"]) in local_paths
        assert str(paths["gota_trash"]) not in local_paths
        assert local_paths and not path_has_skipped_scan_dir(local_paths[0])

    def test_hybrid_theory_is_not_various_artists_when_mostly_recycle(
        self, tmp_path, monkeypatch,
    ):
        library_dir = tmp_path / "Music"
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = _zeratool_paths(library_dir)
        _seed_zeratool_library(db, paths)
        db.close()

        library_api = _patch_library_api(monkeypatch, tmp_path, library_dir)
        albums = library_api._get_db().all_albums()
        hybrid = [row for row in albums if (row.get("album") or "").casefold() == "hybrid theory"]
        assert hybrid
        assert hybrid[0]["artist"] == "Linkin Park"
        assert hybrid[0]["track_count"] == 2
        assert hybrid[0]["artist"] != "Various Artists"

        cards = library_api._album_cards(library_api._get_db())
        hybrid_cards = [card for card in cards if "hybrid theory" in card["name"].casefold()]
        assert hybrid_cards
        for card in hybrid_cards:
            assert card["artist"] != "Various Artists"
            assert card["track_count"] <= 2
            assert not any(path_has_skipped_scan_dir(row["path"]) for row in card.get("tracks") or [])
            assert all(
                not path_has_skipped_scan_dir(path)
                for path in [card.get("cover_path") or ""]
                if path
            )

    def test_leftover_recycle_rows_hidden_before_any_scan(self, tmp_path, monkeypatch):
        library_dir = tmp_path / "Music"
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        paths = _zeratool_paths(library_dir)
        _seed_zeratool_library(db, paths)
        known_before = db.known_paths()
        db.close()

        assert any(path_has_skipped_scan_dir(path) for path in known_before)

        library_api = _patch_library_api(monkeypatch, tmp_path, library_dir)
        payload = library_api.library(sort="artist", limit=50, offset=0, q="")
        assert not any(path_has_skipped_scan_dir(row["path"]) for row in payload["tracks"])

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        known = db.known_paths()
        db.close()
        assert str(paths["gota_live"]) in known
        assert str(paths["titled"]) in known
        assert str(paths["gota_trash"]) not in known
        assert str(paths["untagged"]) not in known
        assert not any(path_has_skipped_scan_dir(path) for path in known)
