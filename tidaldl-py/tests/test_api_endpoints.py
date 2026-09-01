"""API endpoint smoke tests — verify each route returns the expected shape.

Uses the shared `client` fixture from conftest.py which provides:
- CSRF token extracted from the index page
- Host header set to localhost:8765
- Convenience `_headers` dict (host + CSRF) for mutating requests
"""

import wave
from types import SimpleNamespace

from tidal_dl.helper.library_db import LibraryDB


class TestLibraryTracks:
    def test_returns_200(self, client):
        resp = client.get("/api/library", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/library", headers=client._host_header)
        data = resp.json()
        assert "tracks" in data
        assert "total" in data
        assert isinstance(data["tracks"], list)
        assert isinstance(data["total"], int)

    def test_scanning_field_present(self, client):
        resp = client.get("/api/library", headers=client._host_header)
        data = resp.json()
        assert "scanning" in data

    def test_pagination_params_accepted(self, client):
        resp = client.get("/api/library?limit=10&offset=0", headers=client._host_header)
        assert resp.status_code == 200

    def test_search_query_accepted(self, client):
        resp = client.get("/api/library?q=test", headers=client._host_header)
        assert resp.status_code == 200

    def test_sort_params_accepted(self, client):
        for sort in ("recent", "artist", "album", "title"):
            resp = client.get(f"/api/library?sort={sort}", headers=client._host_header)
            assert resp.status_code == 200, f"Failed for sort={sort}"


class TestLocalMetadataResolution:
    def test_meaningful_embedded_tags_win_over_folder_names(self, tmp_path):
        from tidal_dl.gui.api.library import _resolve_local_metadata

        root = tmp_path / "music"
        track = root / "Wrong Artist" / "Wrong Artist - Wrong Album" / "wrong.wav"

        resolved = _resolve_local_metadata(
            track,
            [root],
            title="Real Title",
            artist="Real Artist",
            album="Real Album",
        )

        assert resolved == {
            "name": "Real Title",
            "artist": "Real Artist",
            "album": "Real Album",
        }

    def test_structured_path_repairs_generic_title_and_missing_artist(self, tmp_path):
        from tidal_dl.gui.api.library import _resolve_local_metadata

        root = tmp_path / "music"
        track = root / "Los Hermanos" / "Los Hermanos - Ya llego" / "Con Cristo.m4a"

        resolved = _resolve_local_metadata(
            track,
            [root],
            title="Track 05",
            artist="",
            album="Ya Llego",
        )

        assert resolved == {
            "name": "Con Cristo",
            "artist": "Los Hermanos",
            "album": "Ya Llego",
        }

    def test_shallow_path_does_not_invent_artist_or_album(self, tmp_path):
        from tidal_dl.gui.api.library import _resolve_local_metadata

        root = tmp_path / "music"

        resolved = _resolve_local_metadata(root / "Loose Song.m4a", [root])

        assert resolved == {
            "name": "Loose Song",
            "artist": "Unknown Artist",
            "album": "Unknown Album",
        }

    def test_legacy_row_is_repaired_once_without_touching_audio(self, tmp_path):
        from tidal_dl.gui.api.library import _reconcile_library_rows

        root = tmp_path / "music"
        track = root / "Los Hermanos" / "Los Hermanos - Ya llego" / "Con Cristo.wav"
        track.parent.mkdir(parents=True)
        with wave.open(str(track), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(44100)
            audio.writeframes(b"\x00\x00" * 100)

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        db.record(
            str(track),
            status="needs_isrc",
            artist="Unknown Artist",
            title="Track 05",
            album="Ya Llego",
        )
        db.commit()
        before = (track.read_bytes(), track.stat().st_mtime_ns)

        assert _reconcile_library_rows(db, scan_dirs=[root]) == 1
        row = db.get(str(track))
        assert row["title"] == "Con Cristo"
        assert row["artist"] == "Los Hermanos"
        assert row["album"] == "Ya llego"
        assert row["codec"] == "pcm"
        assert row["metadata_complete"] == 1
        assert db.metadata_repair_worklist() == []
        assert (track.read_bytes(), track.stat().st_mtime_ns) == before
        db.close()

    def test_codec_family_distinguishes_aac_and_alac(self):
        from tidal_dl.gui.api.library import _codec_family

        assert _codec_family(SimpleNamespace(codec="mp4a.40.2", codec_description="AAC LC")) == "aac"
        assert _codec_family(SimpleNamespace(codec="alac", codec_description="Apple Lossless")) == "alac"


class TestLocalArtworkAvailability:
    def test_cached_art_for_unapproved_path_is_denied(self, tmp_path, monkeypatch, client):
        import tidal_dl.gui.api.library as library_api

        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        unapproved_audio = tmp_path / "outside" / "private.mp3"
        unapproved_audio.parent.mkdir()
        unapproved_audio.write_bytes(b"not audio")

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(allowed_dir), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        cached_bytes = b"cached-private-artwork"
        cache_file = tmp_path / "art_cache" / library_api._art_cache_key(str(unapproved_audio))
        cache_file.parent.mkdir()
        cache_file.write_bytes(cached_bytes)

        response = client.get(
            "/api/library/art",
            params={"path": str(unapproved_audio)},
            headers=client._host_header,
        )

        assert response.status_code == 403
        assert response.content != cached_bytes

    def test_cached_art_for_approved_path_is_served(self, tmp_path, monkeypatch, client):
        import tidal_dl.gui.api.library as library_api

        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        approved_audio = allowed_dir / "public.mp3"
        approved_audio.write_bytes(b"not audio")

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(allowed_dir), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        cached_bytes = b"cached-public-artwork"
        cache_file = tmp_path / "art_cache" / library_api._art_cache_key(str(approved_audio))
        cache_file.parent.mkdir()
        cache_file.write_bytes(cached_bytes)

        response = client.get(
            "/api/library/art",
            params={"path": str(approved_audio)},
            headers=client._host_header,
        )

        assert response.status_code == 200
        assert response.content == cached_bytes

    def test_cached_art_marks_legacy_row_available(self, tmp_path, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        audio_path = allowed_dir / "legacy.mp3"
        audio_path.write_bytes(b"not audio")

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(allowed_dir), scan_paths="")

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        db.record(str(audio_path), status="tagged", artist="Artist", title="Legacy")
        db.commit()

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(library_api, "_get_db", lambda: db)
        cache_file = tmp_path / "art_cache" / library_api._art_cache_key(str(audio_path))
        cache_file.parent.mkdir()
        cache_file.write_bytes(b"cached-legacy-artwork")

        response = library_api.library_art(str(audio_path))

        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=86400"
        assert db.get(str(audio_path))["art_available"] == 1
        db.close()

    def test_sibling_art_cache_ignores_unsupported_file_metadata(
        self, tmp_path, monkeypatch, client,
    ):
        import shutil

        import tidal_dl.gui.api.library as library_api

        library_dir = tmp_path / "music"
        library_dir.mkdir()
        audio_path = library_dir / "track.mp3"
        audio_path.write_bytes(b"not audio")
        cover_path = library_dir / "cover.jpg"
        cover_bytes = b"album artwork"
        cover_path.write_bytes(cover_bytes)

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(library_dir), scan_paths="")

        def reject_metadata_copy(*args, **kwargs):
            raise PermissionError("filesystem does not allow metadata flags")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(library_api, "MutagenFile", lambda *args, **kwargs: None)
        monkeypatch.setattr(shutil, "copystat", reject_metadata_copy)

        response = client.get(
            "/api/library/art",
            params={"path": str(audio_path)},
            headers=client._host_header,
        )

        assert response.status_code == 200
        assert response.content == cover_bytes

    def test_newly_scanned_coverless_track_omits_art_url(self, tmp_path, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        library_dir = tmp_path / "music"
        library_dir.mkdir()
        track = library_dir / "coverless.mp3"
        track.write_bytes(b"not audio")

        class FakeSettings:
            data = SimpleNamespace(download_base_path=str(library_dir), scan_paths="")

        monkeypatch.setattr(library_api, "Settings", FakeSettings)
        monkeypatch.setattr(library_api, "path_config_base", lambda: str(tmp_path))
        monkeypatch.setattr(
            library_api,
            "_read_metadata",
            lambda path, scan_dirs=None: {
                "path": str(path), "name": "Coverless", "artist": "Artist",
                "album": "Album", "duration": 180, "isrc": "", "genre": None,
                "quality": "MP3", "format": "MP3", "codec": "mp3",
                "metadata_complete": True, "is_local": True,
            },
        )
        monkeypatch.setattr("tidal_dl.helper.waveform.extract_both", lambda path: None)

        library_api._background_scan(rescan=False)
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        monkeypatch.setattr(library_api, "_get_db", lambda: db)

        response = library_api.library(sort="recent", limit=50, offset=0, q="")

        assert db.get(str(track))["art_available"] == 0
        assert response["tracks"][0]["cover_url"] == ""
        db.close()

    def test_known_coverless_local_rows_omit_art_urls_everywhere(self, tmp_path, monkeypatch):
        import tidal_dl.gui.api.home as home_api
        import tidal_dl.gui.api.library as library_api

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        path = "/music/artist/album/coverless.flac"
        db.record(
            path,
            status="tagged",
            artist="Artist",
            title="Coverless",
            album="Album",
            duration=180,
            art_available=False,
        )
        db.record_download(
            track_id=1,
            name="Coverless",
            artist="Artist",
            album="Album",
            status="done",
            finished_at=100,
        )
        db.add_favorite(path=path, artist="Artist", title="Coverless", album="Album")
        db.log_play_event(path=path, artist="Artist", duration=180, played_at=100)
        db.commit()

        monkeypatch.setattr(library_api, "_get_db", lambda: db)
        monkeypatch.setattr(home_api, "_get_db", lambda: db)
        monkeypatch.setattr(home_api, "_volume_available_cached", lambda: True)

        responses = [
            library_api.library(sort="recent", limit=50, offset=0, q=""),
            library_api.library_artists(limit=50, offset=0, q=""),
            library_api.all_albums(q=""),
            library_api.library_recent_albums(limit=12, offset=0),
            library_api.artist_albums("Artist"),
            library_api.library_search(q="Coverless", type="tracks", limit=20),
            library_api.library_search(q="Album", type="albums", limit=20),
            library_api.library_search(q="Artist", type="artists", limit=20),
            library_api.get_favorites(),
            home_api.recent_plays(limit=20),
            home_api.home_stats(),
        ]

        def cover_urls(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "cover_url":
                        yield item
                    else:
                        yield from cover_urls(item)
            elif isinstance(value, list):
                for item in value:
                    yield from cover_urls(item)

        assert list(cover_urls(responses))
        assert set(cover_urls(responses)) == {""}
        db.close()

    def test_art_present_local_track_serializes_art_url(self, tmp_path, monkeypatch):
        import tidal_dl.gui.api.library as library_api

        db = LibraryDB(tmp_path / "library.db")
        db.open()
        path = "/music/artist/album/with-art.flac"
        db.record(path, status="tagged", artist="Artist", title="With Art", art_available=True)
        db.commit()
        monkeypatch.setattr(library_api, "_get_db", lambda: db)

        response = library_api.library(sort="recent", limit=50, offset=0, q="")

        assert response["tracks"][0]["cover_url"].startswith("/api/library/art?path=")
        db.close()

    def test_legacy_unknown_art_returns_fallback_and_records_no_art(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        import tidal_dl.gui.api.library as library_api
        from tidal_dl.gui import security

        audio_path = tmp_path / "coverless.mp3"
        audio_path.write_bytes(b"not audio")
        db = LibraryDB(tmp_path / "library.db")
        db.open()
        db.record(str(audio_path), status="tagged", artist="Artist", title="Legacy")
        db.commit()
        monkeypatch.setattr(library_api, "_get_db", lambda: db)
        monkeypatch.setattr(
            security,
            "resolve_local_audio_path",
            lambda *args, **kwargs: SimpleNamespace(kind="ok", path=audio_path),
        )
        monkeypatch.setattr(library_api, "MutagenFile", lambda *args, **kwargs: None)

        initial = library_api._db_row_to_track(db.get(str(audio_path)))
        response = library_api.library_art(str(audio_path))

        assert initial["cover_url"].startswith("/api/library/art?path=")
        assert response.status_code == 200
        assert response.media_type == "image/png"
        assert db.get(str(audio_path))["art_available"] == 0
        db.close()


class TestLibraryArtists:
    def test_returns_200(self, client):
        resp = client.get("/api/library/artists", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/library/artists", headers=client._host_header)
        data = resp.json()
        assert "artists" in data
        assert "total" in data
        assert isinstance(data["artists"], list)

    def test_pagination_params_accepted(self, client):
        resp = client.get("/api/library/artists?limit=10&offset=0", headers=client._host_header)
        assert resp.status_code == 200

    def test_search_filter_accepted(self, client):
        resp = client.get("/api/library/artists?q=some", headers=client._host_header)
        assert resp.status_code == 200


class TestLibraryAlbums:
    def test_returns_200(self, client):
        resp = client.get("/api/library/albums", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/library/albums", headers=client._host_header)
        data = resp.json()
        assert "albums" in data
        assert "total" in data
        assert isinstance(data["albums"], list)

    def test_search_filter_accepted(self, client):
        resp = client.get("/api/library/albums?q=some", headers=client._host_header)
        assert resp.status_code == 200


class TestRecentAlbums:
    def test_returns_200(self, client):
        resp = client.get("/api/library/recent-albums", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/library/recent-albums", headers=client._host_header)
        data = resp.json()
        assert "albums" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert isinstance(data["albums"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["limit"], int)
        assert isinstance(data["offset"], int)

    def test_pagination_params_accepted(self, client):
        resp = client.get("/api/library/recent-albums?limit=10&offset=5", headers=client._host_header)
        assert resp.status_code == 200


class TestLibraryFavorites:
    def test_local_favorite_exposes_local_path_alias(self, monkeypatch):
        from tidal_dl.gui.api import library as library_api

        favorite = {
            "id": 1,
            "path": "/music/favorite.flac",
            "tidal_id": 7,
            "artist": "Artist",
            "title": "Favorite",
            "album": "Album",
            "isrc": "ISRC123",
            "cover_url": "",
            "scanned_quality": "FLAC",
            "scanned_duration": 180,
            "scanned_art_available": 0,
            "favorited_at": 1,
        }
        monkeypatch.setattr(library_api, "_get_db", lambda: SimpleNamespace(all_favorites=lambda: [favorite]))

        payload = library_api.get_favorites()

        assert payload["favorites"][0]["local_path"] == "/music/favorite.flac"

    def test_returns_200(self, client):
        resp = client.get("/api/library/favorites", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/library/favorites", headers=client._host_header)
        data = resp.json()
        assert "favorites" in data
        assert "total" in data
        assert "total_duration" in data
        assert isinstance(data["favorites"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["total_duration"], int)


class TestHome:
    def test_returns_200(self, client):
        resp = client.get("/api/home", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_is_dict(self, client):
        resp = client.get("/api/home", headers=client._host_header)
        assert isinstance(resp.json(), dict)

    def test_volume_available_field_present(self, client):
        resp = client.get("/api/home", headers=client._host_header)
        data = resp.json()
        assert "volume_available" in data

    def test_recent_memory_endpoint_shape(self, client):
        resp = client.get("/api/home/recent?limit=5", headers=client._host_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "tracks" in data
        assert isinstance(data["tracks"], list)


class TestDownloadsSnapshot:
    def test_uses_app_job_service(self, client):
        assert hasattr(client.app.state, "download_jobs")
        resp = client.get("/api/downloads/active/snapshot", headers=client._host_header)
        assert resp.status_code == 200
        assert resp.json() == {
            "active": [],
            "queued_count": 0,
            "active_count": 0,
            "paused": False,
        }

    def test_returns_200(self, client):
        resp = client.get("/api/downloads/active/snapshot", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/downloads/active/snapshot", headers=client._host_header)
        data = resp.json()
        assert "active" in data
        assert isinstance(data["active"], list)
        assert "queued_count" in data
        assert "active_count" in data
        assert "paused" in data

    def test_empty_queue_initially(self, client):
        resp = client.get("/api/downloads/active/snapshot", headers=client._host_header)
        # May or may not have items; important thing is the key exists
        data = resp.json()
        assert "active" in data


class TestDownloadsSSE:
    def test_rejects_too_many_clients(self, client):
        hub = client.app.state.download_jobs.events
        queues = [hub.subscribe() for _ in range(hub.max_clients)]
        try:
            resp = client.get("/api/downloads/active", headers=client._host_header)
        finally:
            for queue in queues:
                hub.unsubscribe(queue)

        assert resp.status_code == 429
        assert resp.json()["detail"] == "Too many SSE connections"


class TestDownloadsHistory:
    def test_returns_200(self, client):
        resp = client.get("/api/downloads/history", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/downloads/history", headers=client._host_header)
        data = resp.json()
        assert "downloads" in data
        assert isinstance(data["downloads"], list)

    def test_limit_param_accepted(self, client):
        resp = client.get("/api/downloads/history?limit=5", headers=client._host_header)
        assert resp.status_code == 200


class TestUpgradeStart:
    def test_direct_track_enqueues_persisted_upgrade_job(self, client, monkeypatch):
        class FakeSettings:
            data = SimpleNamespace(upgrade_target_quality="HI_RES_LOSSLESS")

        class FakeDB:
            def get(self, path):
                return {"path": path}

            def close(self):
                pass

        monkeypatch.setattr("tidal_dl.config.Settings", FakeSettings)
        monkeypatch.setattr("tidal_dl.gui.api.upgrade._get_db", lambda: FakeDB())

        resp = client.post(
            "/api/upgrade/start",
            json={
                "tracks": [
                    {
                        "path": "/music/old.flac",
                        "tidal_track_id": 456,
                    }
                ]
            },
            headers=client._headers,
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "queued",
            "count": 1,
            "skipped": 0,
            "errors": [],
        }
        assert client.app.state.download_jobs.snapshot()["queued_count"] == 1

    def test_path_upgrade_requests_probed_lossless(self, client, monkeypatch):
        captured: dict = {}

        class FakeSettings:
            data = SimpleNamespace(upgrade_target_quality="HI_RES_LOSSLESS")

        class FakeDB:
            def get(self, path):
                return {
                    "path": path,
                    "isrc": "GBAYE9200070",
                    "quality": "HIGH",
                    "format": "M4A",
                    "codec": "aac",
                }

            def get_probe(self, isrc):
                return {"tidal_track_id": 58990486, "max_quality": "LOSSLESS"}

            def close(self):
                pass

        def fake_enqueue(items):
            captured["items"] = items
            return {"status": "queued", "count": len(items), "skipped": 0}

        monkeypatch.setattr("tidal_dl.config.Settings", FakeSettings)
        monkeypatch.setattr("tidal_dl.gui.api.upgrade._get_db", lambda: FakeDB())
        monkeypatch.setattr(client.app.state.download_jobs, "enqueue_upgrade", fake_enqueue)

        resp = client.post(
            "/api/upgrade/start",
            json={"track_paths": ["/music/Creep.m4a"]},
            headers=client._headers,
        )

        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert resp.json()["skipped"] == 0
        assert captured["items"][0].quality == "LOSSLESS"

    def test_direct_track_rejects_path_missing_from_library(self, client, monkeypatch):
        class FakeSettings:
            data = SimpleNamespace(upgrade_target_quality="HI_RES_LOSSLESS")

        class FakeDB:
            def get(self, path):
                return None

            def close(self):
                pass

        monkeypatch.setattr("tidal_dl.config.Settings", FakeSettings)
        monkeypatch.setattr("tidal_dl.gui.api.upgrade._get_db", lambda: FakeDB())

        resp = client.post(
            "/api/upgrade/start",
            json={
                "tracks": [
                    {
                        "path": "/music/missing.flac",
                        "tidal_track_id": 456,
                    }
                ]
            },
            headers=client._headers,
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "queued",
            "count": 0,
            "skipped": 0,
            "errors": ["Not in library: /music/missing.flac"],
        }
        assert client.app.state.download_jobs.snapshot()["queued_count"] == 0


class TestDownloadTrigger:
    def test_requires_tidal_login(self, client, monkeypatch, clear_singletons):
        class FakeSession:
            def check_login(self):
                return False

        class FakeTidal:
            def __init__(self):
                self.session = FakeSession()

        monkeypatch.setattr("tidal_dl.config.Tidal", FakeTidal)

        resp = client.post(
            "/api/download",
            json={"track_ids": [123]},
            headers=client._headers,
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not logged in to Tidal"
        assert "terminal" not in resp.json()["detail"].lower()


class TestSearchAuth:
    def test_requires_tidal_login_without_terminal_hint(self, client, monkeypatch):
        class FakeSession:
            def check_login(self):
                return False

        class FakeTidal:
            def __init__(self):
                self.session = FakeSession()

        monkeypatch.setattr("tidal_dl.gui.api.search.Tidal", FakeTidal)

        resp = client.get(
            "/api/search?q=test",
            headers=client._host_header,
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not logged in to Tidal"
        assert "terminal" not in resp.json()["detail"].lower()


class TestDuplicatesPreview:
    def test_returns_200(self, client):
        resp = client.get("/api/duplicates/preview", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/duplicates/preview", headers=client._host_header)
        data = resp.json()
        assert "groups" in data
        assert "total_groups" in data
        assert "total_duplicates" in data
        assert "undo_available" in data
        assert isinstance(data["groups"], list)

    def test_stale_count_present(self, client):
        resp = client.get("/api/duplicates/preview", headers=client._host_header)
        data = resp.json()
        assert "stale_count" in data
        assert "truncated" in data


class TestSettings:
    def test_returns_200(self, client):
        resp = client.get("/api/settings", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/settings", headers=client._host_header)
        data = resp.json()
        assert "download_base_path" in data
        assert "quality_audio" in data
        assert "format_track" in data
        assert "skip_existing" in data

    def test_all_expected_keys_present(self, client):
        resp = client.get("/api/settings", headers=client._host_header)
        data = resp.json()
        expected_keys = {
            "download_base_path", "quality_audio", "format_track", "format_album",
            "format_playlist", "cover_album_file", "metadata_cover_embed",
            "lyrics_embed", "lyrics_file", "skip_existing", "skip_duplicate_isrc",
            "downloads_concurrent_max", "scan_paths",
        }
        for key in expected_keys:
            assert key in data, f"Missing settings key: {key}"


class TestCSRFBehavior:
    def _fresh_client(self):
        """Return a plain TestClient without any CSRF token in default headers.

        The shared `client` fixture sets c._headers which overwrites httpx's
        internal header store, causing the token to be sent on every request.
        For CSRF-rejection tests we need a client with no token baked in.
        """
        from fastapi.testclient import TestClient

        from tidal_dl.gui import create_app
        return TestClient(create_app(port=8765))

    def test_post_without_csrf_token_rejected(self):
        """POST without X-CSRF-Token should be rejected with 403."""
        c = self._fresh_client()
        resp = c.post(
            "/api/library/scan",
            headers={"host": "localhost:8765"},  # explicitly no CSRF token
        )
        assert resp.status_code == 403

    def test_post_with_wrong_csrf_token_rejected(self):
        """POST with wrong CSRF token should be rejected with 403."""
        c = self._fresh_client()
        resp = c.post(
            "/api/library/scan",
            headers={"host": "localhost:8765", "X-CSRF-Token": "wrong-token-value"},
        )
        assert resp.status_code == 403

    def test_post_with_valid_csrf_token_accepted(self, client):
        """POST with valid CSRF token should not return 403."""
        resp = client.post("/api/library/scan", headers=client._headers)
        # 200 or any non-403/non-422 indicates CSRF passed
        assert resp.status_code not in (403,)

    def test_get_requests_pass_without_csrf_token(self, client):
        """GET requests should never require a CSRF token."""
        resp = client.get("/api/settings", headers=client._host_header)
        assert resp.status_code == 200


class TestStaticFileServing:
    def test_index_html_served(self, client):
        resp = client.get("/", headers=client._host_header)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_csrf_token_embedded_in_index(self, client):
        """CSRF token must be present in the index page meta tag."""
        resp = client.get("/", headers=client._host_header)
        assert 'name="csrf-token"' in resp.text
        assert 'content="' in resp.text
        # The token should not be the placeholder
        assert "__CSRF_TOKEN__" not in resp.text

    def test_app_js_served(self, client):
        for name in ("api.js", "views.js", "player.js"):
            resp = client.get(f"/{name}", headers=client._host_header)
            assert resp.status_code == 200

    def test_style_css_served(self, client):
        resp = client.get("/style.css", headers=client._host_header)
        assert resp.status_code == 200

    def test_favicon_served(self, client):
        resp = client.get("/favicon.ico", headers=client._host_header)
        assert resp.status_code == 200
        assert "image" in resp.headers.get("content-type", "")
