from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "app.js"
_HOST_HEADER = {"host": "localhost:8765"}


def test_settings_status_endpoint_reports_access_and_version(client):
    resp = client.get("/api/settings/status", headers=client._host_header)

    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "read_only" in data
    assert "banner_message" in data
    assert "paths" in data
    assert isinstance(data["paths"], list)


def test_settings_status_goes_read_only_when_configured_volume_is_unavailable(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import settings as settings_api

    missing_path = "/__music_dl_missing__/volume"
    fake_settings = SimpleNamespace(
        data=SimpleNamespace(
            download_base_path=missing_path,
            scan_paths=missing_path,
        )
    )

    monkeypatch.setattr(settings_api, "Settings", lambda: fake_settings)

    data = settings_api.settings_status()

    assert data["read_only"] is True
    assert missing_path in (data["banner_message"] or "")
    assert data["paths"][0]["path"] == missing_path
    assert data["paths"][0]["ok"] is False


def test_settings_status_stays_editable_if_only_extra_scan_path_is_unavailable(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import settings as settings_api

    missing_path = "/__music_dl_missing__/volume"
    fake_settings = SimpleNamespace(
        data=SimpleNamespace(
            download_base_path=str(tmp_path),
            scan_paths=f"{tmp_path},{missing_path}",
        )
    )

    monkeypatch.setattr(settings_api, "Settings", lambda: fake_settings)

    data = settings_api.settings_status()

    assert data["read_only"] is False
    assert any(path["path"] == missing_path and path["ok"] is False for path in data["paths"])


def test_settings_status_goes_read_only_when_primary_path_is_not_writable(monkeypatch, clear_singletons):
    from tidal_dl.gui.api import settings as settings_api

    primary = "/Volumes/Music"
    fake_settings = SimpleNamespace(
        data=SimpleNamespace(
            download_base_path=primary,
            scan_paths=primary,
        )
    )

    monkeypatch.setattr(settings_api, "Settings", lambda: fake_settings)
    monkeypatch.setattr(
        settings_api,
        "_configured_paths",
        lambda s: [primary],
    )
    monkeypatch.setattr(
        settings_api,
        "_path_access_info",
        lambda path: {
            "path": path,
            "exists": True,
            "is_dir": True,
            "readable": True,
            "writable": False,
            "ok": True,
            "reason": "read_only",
        },
    )

    data = settings_api.settings_status()

    assert data["read_only"] is True
    assert primary in (data["banner_message"] or "")


def test_update_settings_allows_recovery_fields_while_read_only(monkeypatch, clear_singletons, tmp_path):
    from tidal_dl.gui.api import settings as settings_api

    fake_settings = SimpleNamespace(
        data=SimpleNamespace(download_base_path="/old", scan_paths="/old", quality_audio="HI_RES_LOSSLESS"),
        save=lambda: None,
    )

    monkeypatch.setattr(settings_api, "Settings", lambda: fake_settings)
    monkeypatch.setattr(settings_api, "settings_status", lambda: {"read_only": True})
    monkeypatch.setattr("tidal_dl.gui.security.validate_download_path", lambda path: True)
    monkeypatch.setattr(
        settings_api,
        "get_settings",
        lambda: {
            "download_base_path": fake_settings.data.download_base_path,
            "scan_paths": fake_settings.data.scan_paths,
        },
    )

    updated = settings_api.update_settings(
        settings_api.SettingsUpdate(download_base_path=str(tmp_path), scan_paths=str(tmp_path))
    )

    assert updated["download_base_path"] == str(tmp_path)
    assert updated["scan_paths"] == str(tmp_path)


def test_update_settings_rejects_non_recovery_edits_while_read_only(monkeypatch, clear_singletons):
    from fastapi import HTTPException
    from tidal_dl.gui.api import settings as settings_api

    fake_settings = SimpleNamespace(
        data=SimpleNamespace(quality_audio="HI_RES_LOSSLESS"),
        save=lambda: None,
    )

    monkeypatch.setattr(settings_api, "Settings", lambda: fake_settings)
    monkeypatch.setattr(settings_api, "settings_status", lambda: {"read_only": True})

    try:
        settings_api.update_settings(settings_api.SettingsUpdate(quality_audio="HIGH"))
    except HTTPException as exc:
        assert exc.status_code == 423
    else:
        raise AssertionError("Expected HTTPException for read-only settings")


def test_index_embeds_always_visible_version_chip():
    from tidal_dl.gui import create_app

    client = TestClient(create_app(port=8765))
    resp = client.get("/", headers=_HOST_HEADER)

    assert resp.status_code == 200
    assert 'id="app-version-chip"' in resp.text
    assert "__APP_VERSION__" not in resp.text


def test_settings_ui_contains_persistent_access_recovery_controls():
    source = APP_JS.read_text(encoding="utf-8")

    assert "Retry Access" in source
    assert "Choose Folder" in source
    assert "state.settingsReadOnly" in source
    assert "Settings are read-only until access is restored." in source
    assert "function setSettingsReadOnly(" in source
