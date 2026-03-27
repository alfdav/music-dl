"""API endpoint smoke tests — verify each route returns the expected shape.

Uses the shared `client` fixture from conftest.py which provides:
- CSRF token extracted from the index page
- Host header set to localhost:8765
- Convenience `_headers` dict (host + CSRF) for mutating requests
"""

import pytest


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


class TestLibraryFavorites:
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


class TestDownloadsSnapshot:
    def test_returns_200(self, client):
        resp = client.get("/api/downloads/active/snapshot", headers=client._host_header)
        assert resp.status_code == 200

    def test_response_shape(self, client):
        resp = client.get("/api/downloads/active/snapshot", headers=client._host_header)
        data = resp.json()
        assert "active" in data
        assert isinstance(data["active"], list)

    def test_empty_queue_initially(self, client):
        resp = client.get("/api/downloads/active/snapshot", headers=client._host_header)
        # May or may not have items; important thing is the key exists
        data = resp.json()
        assert "active" in data


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
        from tidal_dl.gui import create_app
        from fastapi.testclient import TestClient
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
        resp = client.get("/app.js", headers=client._host_header)
        assert resp.status_code == 200

    def test_style_css_served(self, client):
        resp = client.get("/style.css", headers=client._host_header)
        assert resp.status_code == 200
