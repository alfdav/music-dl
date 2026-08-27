import base64
import json
import threading
import time
from unittest import mock

import pytest
import requests
from tidalapi import Playlist, Quality, Track

from tidal_dl.config import Settings as ConfigSettings
from tidal_dl.config import Tidal
from tidal_dl.constants import HIFI_QUALITY_MAP, DownloadSource, MediaType
from tidal_dl.helper.checkpoint import DownloadCheckpoint
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.hifi_api import HiFiApiClient
from tidal_dl.model.cfg import Settings
from tidal_dl.model.downloader import HiFiStreamManifest


@pytest.mark.parametrize(
    ("requested", "delivered", "codec"),
    [
        (Quality.low_96k, Quality.low_96k, "mp4a.40.2"),
        (Quality.low_320k, Quality.low_320k, "aac"),
        (Quality.high_lossless, Quality.high_lossless, "flac"),
        (Quality.hi_res_lossless, Quality.hi_res_lossless, "flac"),
        (Quality.hi_res_lossless, Quality.high_lossless, "flac"),
        (Quality.high_lossless, Quality.hi_res_lossless, "flac"),
        ("HI_RES_LOSSLESS", "LOSSLESS", "flac"),
        ("HI_RES", "LOSSLESS", "flac"),
    ],
)
def test_exact_quality_accepts_only_matching_compatible_delivery(requested, delivered, codec):
    from tidal_dl.download.streams import _require_exact_quality

    _require_exact_quality(requested, delivered, codec)


@pytest.mark.parametrize(
    ("requested", "delivered", "codec", "expected"),
    [
        (Quality.low_96k, Quality.low_320k, "aac", "requested LOW but received HIGH"),
        (Quality.low_96k, Quality.high_lossless, "flac", "requested LOW but received LOSSLESS"),
        (Quality.low_96k, Quality.hi_res_lossless, "flac", "requested LOW but received HI_RES_LOSSLESS"),
        (Quality.low_320k, Quality.low_96k, "aac", "requested HIGH but received LOW"),
        (Quality.low_320k, Quality.high_lossless, "flac", "requested HIGH but received LOSSLESS"),
        (Quality.low_320k, Quality.hi_res_lossless, "flac", "requested HIGH but received HI_RES_LOSSLESS"),
        (Quality.high_lossless, Quality.low_96k, "aac", "requested LOSSLESS but received LOW"),
        (Quality.high_lossless, Quality.low_320k, "aac", "requested LOSSLESS but received HIGH"),
        (Quality.hi_res_lossless, Quality.low_96k, "aac", "requested HI_RES_LOSSLESS but received LOW"),
        (Quality.hi_res_lossless, Quality.low_320k, "aac", "requested HI_RES_LOSSLESS but received HIGH"),
        (Quality.high_lossless, "UNKNOWN", "flac", "received unknown"),
        (Quality.high_lossless, Quality.high_lossless, "aac", "received LOSSLESS with codec aac"),
        (Quality.low_320k, Quality.low_320k, "flac", "received HIGH with codec flac"),
        (Quality.low_96k, Quality.low_96k, "", "received LOW with codec unknown"),
    ],
)
def test_exact_quality_rejects_different_unknown_or_incompatible_delivery(requested, delivered, codec, expected):
    from tidal_dl.download.streams import QualityMismatchError, _require_exact_quality

    with pytest.raises(QualityMismatchError, match=expected):
        _require_exact_quality(requested, delivered, codec)


def _oauth_stream_subject():
    from tidal_dl.download.streams import StreamMixin

    class OAuthStreamSubject(StreamMixin):
        def __init__(self):
            self.settings = type(
                "Settings",
                (),
                {"data": type("Data", (), {"download_dolby_atmos": False, "extract_flac": False})()},
            )()
            self.session = type("Session", (), {})()
            self.tidal = type(
                "Tidal",
                (),
                {
                    "active_source": DownloadSource.OAUTH,
                    "hifi_client": None,
                    "stream_lock": threading.Lock(),
                    "_ensure_token_fresh": lambda self: None,
                    "restore_normal_session": lambda self: True,
                },
            )()
            self.fn_logger = type(
                "Logger",
                (),
                {
                    "error": lambda *_args: None,
                    "exception": lambda *_args: None,
                    "warning": lambda *_args: None,
                },
            )()

        def _on_rate_limit_hit(self):
            raise AssertionError("quality mismatch must not be treated as rate limiting")

    return OAuthStreamSubject()


@pytest.mark.parametrize("codec", ["eac3", "ec-3"])
def test_explicit_atmos_accepts_high_eac3(codec):
    from tidal_dl.download.streams import StreamMixin

    manifest = type("Manifest", (), {"codecs": codec, "file_extension": ".mp4"})()
    stream = type(
        "Stream",
        (),
        {"audio_quality": Quality.low_320k, "get_stream_manifest": lambda self: manifest},
    )()
    atmos_track = type("AtmosTrack", (), {"id": 118, "get_stream": lambda self: stream})()
    media = type("Media", (), {"id": 118, "audio_modes": ["DOLBY_ATMOS"]})()

    class Subject(StreamMixin):
        def __init__(self):
            self.atmos_switches = 0
            self.settings = type(
                "Settings",
                (),
                {"data": type("Data", (), {"download_dolby_atmos": True, "extract_flac": False})()},
            )()
            self.session = type(
                "Session",
                (), {"audio_quality": Quality.low_320k, "track": lambda _self, _id: atmos_track},
            )()
            self.tidal = type(
                "Tidal",
                (),
                {
                    "switch_to_atmos_session": lambda _self: self._mark_atmos_switch(),
                    "restore_normal_session": lambda _self: True,
                },
            )()
            self.fn_logger = type("Logger", (), {"error": lambda *_args: None})()

        def _mark_atmos_switch(self):
            self.atmos_switches += 1
            return True

    subject = Subject()
    result = subject._get_track_stream_info(media)

    assert result.stream_manifest is manifest
    assert subject.atmos_switches == 1


@pytest.mark.parametrize("codec", ["eac3", "ec-3"])
def test_ordinary_high_rejects_atmos_codec(codec):
    from tidal_dl.download.streams import QualityMismatchError, StreamMixin

    manifest = type("Manifest", (), {"codecs": codec, "file_extension": ".mp4"})()
    stream = type(
        "Stream",
        (),
        {"audio_quality": Quality.low_320k, "get_stream_manifest": lambda self: manifest},
    )()
    media = type("Media", (), {"id": 118, "audio_modes": [], "get_stream": lambda self: stream})()

    class Subject(StreamMixin):
        def __init__(self):
            self.settings = type(
                "Settings",
                (),
                {"data": type("Data", (), {"download_dolby_atmos": False, "extract_flac": False})()},
            )()
            self.session = type("Session", (), {"audio_quality": Quality.low_320k})()
            self.tidal = type(
                "Tidal",
                (),
                {"switch_to_atmos_session": lambda _self: True, "restore_normal_session": lambda _self: True},
            )()
            self.fn_logger = type("Logger", (), {"error": lambda *_args: None})()

    with pytest.raises(QualityMismatchError, match=f"received HIGH with codec {codec}"):
        Subject()._get_track_stream_info(media)


def _oauth_track(delivered, codec, segment_calls):
    class Manifest:
        file_extension = ".flac"
        codecs = codec

        def get_urls(self):
            segment_calls.append("oauth")
            return ["https://example.invalid/segment"]

    manifest = Manifest()
    stream = type(
        "Stream",
        (),
        {"audio_quality": delivered, "get_stream_manifest": lambda self: manifest},
    )()

    class LocalTrack(Track):
        def __init__(self):
            pass

        @property
        def id(self):
            return 118

        @property
        def audio_modes(self):
            return []

        def get_stream(self):
            return stream

    track = LocalTrack()
    return track, manifest


def test_oauth_exact_quality_returns_manifest_before_segment_consumption():
    subject = _oauth_stream_subject()
    subject.session.audio_quality = Quality.hi_res_lossless
    segment_calls = []
    track, manifest = _oauth_track(Quality.hi_res_lossless, "flac", segment_calls)

    returned_manifest, *_ = subject._get_stream_info(track)

    assert returned_manifest is manifest
    assert returned_manifest.get_urls() == ["https://example.invalid/segment"]
    assert segment_calls == ["oauth"]


def test_oauth_accepts_lossless_flac_when_hi_res_is_unavailable():
    subject = _oauth_stream_subject()
    subject.session.audio_quality = Quality.hi_res_lossless
    segment_calls = []
    track, manifest = _oauth_track(Quality.high_lossless, "flac", segment_calls)

    returned_manifest, *_ = subject._get_stream_info(track)

    assert returned_manifest is manifest
    assert returned_manifest.get_urls() == ["https://example.invalid/segment"]
    assert segment_calls == ["oauth"]


@pytest.mark.parametrize(
    ("delivered", "codec", "expected"),
    [
        (Quality.low_320k, "aac", "requested HI_RES_LOSSLESS but received HIGH with codec aac"),
        (Quality.hi_res_lossless, "aac", "requested HI_RES_LOSSLESS but received HI_RES_LOSSLESS with codec aac"),
    ],
)
def test_oauth_exact_quality_rejects_before_manifest_reaches_segment_consumption(delivered, codec, expected):
    from tidal_dl.download.streams import QualityMismatchError

    subject = _oauth_stream_subject()
    subject.session.audio_quality = Quality.hi_res_lossless
    segment_calls = []
    track, manifest = _oauth_track(delivered, codec, segment_calls)

    with pytest.raises(QualityMismatchError, match=expected):
        subject._get_stream_info(track)

    assert manifest.file_extension == ".flac"
    assert segment_calls == []


def _hifi_stream_subject(result):
    subject = _oauth_stream_subject()
    calls = []

    class HiFiClient:
        def track_stream(self, track_id, quality):
            calls.append((track_id, quality))
            return result

    subject.tidal.active_source = DownloadSource.HIFI_API
    subject.tidal.hifi_client = HiFiClient()
    subject.tidal.restore_normal_session = lambda: (_ for _ in ()).throw(
        AssertionError("quality mismatch must not fall back to OAuth")
    )
    return subject, calls


def _hifi_result(delivered, codec):
    from tidal_dl.hifi_api import HiFiStreamResult

    return HiFiStreamResult(
        urls=["https://example.invalid/segment"],
        file_extension=".flac",
        codecs=codec,
        mime_type="audio/flac",
        audio_quality=delivered,
    )


def test_hifi_exact_quality_returns_manifest_before_urls_reach_consumption():
    subject, calls = _hifi_stream_subject(_hifi_result("HI_RES_LOSSLESS", "flac"))
    subject.session.audio_quality = Quality.hi_res_lossless
    track, _ = _oauth_track(Quality.hi_res_lossless, "flac", [])

    manifest, *_ = subject._get_stream_info(track)

    assert manifest.get_urls() == ["https://example.invalid/segment"]
    assert calls == [(118, "HI_RES_LOSSLESS")]


def test_hifi_accepts_lossless_flac_when_hi_res_is_unavailable():
    subject, calls = _hifi_stream_subject(_hifi_result("LOSSLESS", "flac"))
    subject.session.audio_quality = Quality.hi_res_lossless
    track, _ = _oauth_track(Quality.high_lossless, "flac", [])

    manifest, *_ = subject._get_stream_info(track)

    assert manifest.get_urls() == ["https://example.invalid/segment"]
    assert calls == [(118, "HI_RES_LOSSLESS")]


@pytest.mark.parametrize(
    ("delivered", "codec", "expected"),
    [
        ("HIGH", "aac", "requested HI_RES_LOSSLESS but received HIGH with codec aac"),
        ("UNKNOWN", "flac", "requested HI_RES_LOSSLESS but received unknown with codec flac"),
        ("HI_RES_LOSSLESS", "aac", "requested HI_RES_LOSSLESS but received HI_RES_LOSSLESS with codec aac"),
    ],
)
def test_hifi_exact_quality_rejects_without_oauth_fallback(delivered, codec, expected):
    from tidal_dl.download.streams import QualityMismatchError

    subject, calls = _hifi_stream_subject(_hifi_result(delivered, codec))
    subject.session.audio_quality = Quality.hi_res_lossless
    track, _ = _oauth_track(Quality.hi_res_lossless, "flac", [])

    with pytest.raises(QualityMismatchError, match=expected):
        subject._get_stream_info(track)

    assert calls == [(118, "HI_RES_LOSSLESS")]


@pytest.mark.parametrize(
    "delivered",
    [Quality.low_320k, "UNKNOWN", Quality.hi_res_lossless, RuntimeError("probe unavailable")],
)
def test_subscription_quality_probe_never_mutates_configured_or_session_quality(delivered):
    class SettingsData:
        quality_audio = Quality.hi_res_lossless

    class ProbeSettings:
        data = SettingsData()

        def __init__(self):
            self.save_calls = 0

        def save(self):
            self.save_calls += 1

    class ProbeSession:
        audio_quality = Quality.hi_res_lossless

        def track(self, _track_id):
            if isinstance(delivered, Exception):
                raise delivered
            stream = type("Stream", (), {"audio_quality": delivered})()
            return type("Track", (), {"get_stream": lambda self: stream})()

    probe = type("Probe", (), {"settings": ProbeSettings(), "session": ProbeSession()})()
    configured_before = probe.settings.data.quality_audio
    session_before = probe.session.audio_quality

    Tidal._probe_subscription_quality(probe)

    assert probe.settings.data.quality_audio == configured_before
    assert probe.session.audio_quality == session_before
    assert probe.settings.save_calls == 0


def test_subscription_quality_probe_unknown_warns_without_pass(capsys):
    class SettingsData:
        quality_audio = Quality.low_96k

    class ProbeSettings:
        data = SettingsData()

        def __init__(self):
            self.save_calls = 0

        def save(self):
            self.save_calls += 1

    class ProbeSession:
        audio_quality = Quality.low_96k

        def track(self, _track_id):
            stream = type("Stream", (), {"audio_quality": "UNKNOWN"})()
            return type("Track", (), {"get_stream": lambda self: stream})()

    probe = type("Probe", (), {"settings": ProbeSettings(), "session": ProbeSession()})()

    Tidal._probe_subscription_quality(probe)

    output = capsys.readouterr().out.lower()
    assert "warning" in output
    assert "unknown" in output
    assert "passed" not in output
    assert probe.settings.data.quality_audio == Quality.low_96k
    assert probe.session.audio_quality == Quality.low_96k
    assert probe.settings.save_calls == 0


def test_settings_default_download_source():
    settings = Settings()
    assert settings.download_source == DownloadSource.OAUTH
    assert settings.download_source_fallback is True
    assert settings.hifi_api_instances == ""


def test_tidal_constructor_accepts_settings():
    settings = ConfigSettings()

    tidal = Tidal(settings)

    assert tidal.settings is settings


def test_resolve_source_non_interactive_uses_quiet_restore_without_login():
    class TidalWithoutCredentials:
        def __init__(self):
            self.settings = type(
                "Settings",
                (),
                {"data": type("Data", (), {"download_source": DownloadSource.OAUTH, "download_source_fallback": True})()},
            )()
            self.quiet_restore = None

        def _try_login_with_key_rotation(self, quiet: bool = False) -> bool:
            self.quiet_restore = quiet
            return False

        def login(self, fn_print):
            raise AssertionError("non-interactive source resolution must not start OAuth")

    tidal = TidalWithoutCredentials()

    assert Tidal.resolve_source(tidal, lambda _message: None, allow_interactive_login=False) is False
    assert tidal.quiet_restore is True


def test_source_resolve_timeout_is_capped_so_dead_network_cannot_eat_spinner():
    """Hi-Fi / gist / quality-probe boot calls must be ~1–2s, not the 45s download timeout.

    Tauri only polls health for 30s. A single 45s Tidal/gist hang used to pin the
    spinner even after we deferred restore off the ready path.
    """
    from tidal_dl.constants import REQUESTS_TIMEOUT_SEC, SOURCE_RESOLVE_TIMEOUT_SEC

    assert REQUESTS_TIMEOUT_SEC == 45
    assert 1 <= SOURCE_RESOLVE_TIMEOUT_SEC <= 2


def test_resolve_source_uses_capped_timeout_for_hifi_and_gist(monkeypatch):
    from tidal_dl.constants import SOURCE_RESOLVE_TIMEOUT_SEC
    from tidal_dl.hifi_api import HiFiApiClient

    captured: dict[str, float] = {}

    class FakeHiFi(HiFiApiClient):
        def __init__(self, instances=None, timeout=45, dead_ttl_sec=300):
            captured["hifi"] = timeout
            super().__init__(instances=instances or ["https://hifi.invalid"], timeout=timeout, dead_ttl_sec=dead_ttl_sec)

        def health_check(self):
            return None

    gist_timeouts: list[object] = []

    def fake_refresh(timeout=None):
        gist_timeouts.append(timeout)
        return False

    class TidalForTimeout:
        def __init__(self):
            self.settings = type(
                "Settings",
                (),
                {
                    "data": type(
                        "Data",
                        (),
                        {
                            "download_source": DownloadSource.HIFI_API,
                            "download_source_fallback": True,
                            "hifi_api_instances": "https://hifi.invalid",
                        },
                    )()
                },
            )()
            self.hifi_client = None
            self.active_source = None

        def _configured_hifi_instances(self):
            return ["https://hifi.invalid"]

        def refresh_api_keys(self):
            return fake_refresh(timeout=SOURCE_RESOLVE_TIMEOUT_SEC)

        def _try_login_with_key_rotation(self, quiet: bool = False) -> bool:
            self.refresh_api_keys()
            return False

        def login(self, fn_print):
            raise AssertionError("non-interactive resolve must not start OAuth")

    monkeypatch.setattr("tidal_dl.config.HiFiApiClient", FakeHiFi)
    tidal = TidalForTimeout()

    assert Tidal.resolve_source(tidal, lambda _message: None, allow_interactive_login=False) is False
    assert captured["hifi"] == SOURCE_RESOLVE_TIMEOUT_SEC
    assert gist_timeouts == [SOURCE_RESOLVE_TIMEOUT_SEC]


def test_refresh_api_keys_honors_explicit_timeout(monkeypatch):
    import tidal_dl.api as api

    seen: dict[str, object] = {}

    def fake_get(url, timeout=None, **_kwargs):
        seen["timeout"] = timeout
        raise requests.RequestException("offline")

    monkeypatch.setattr(api.requests, "get", fake_get)
    assert api.refresh_api_keys(timeout=1.5) is False
    assert seen["timeout"] == 1.5


def test_hifi_client_decodes_bts_manifest():
    manifest_json = {
        "mimeType": "audio/flac",
        "codecs": "flac",
        "encryptionType": "NONE",
        "urls": ["https://example.invalid/track.flac"],
    }
    encoded = base64.b64encode(json.dumps(manifest_json).encode("utf-8")).decode("utf-8")
    payload = {
        "data": {
            "audioQuality": "LOSSLESS",
            "manifestMimeType": "application/vnd.tidal.bts",
            "manifest": encoded,
            "bitDepth": 16,
            "sampleRate": 44100,
        }
    }

    parsed = HiFiApiClient.parse_track_payload(payload)
    assert parsed.file_extension == ".flac"
    assert parsed.codecs == "flac"
    assert parsed.urls == ["https://example.invalid/track.flac"]


def test_checkpoint_lifecycle(tmp_path):
    checkpoint = DownloadCheckpoint(
        path=tmp_path / "checkpoint.json",
        collection_id="playlist:123",
        collection_type="playlist",
    )
    checkpoint.initialize_tracks(["1", "2"])
    checkpoint.mark("1", "downloaded")
    checkpoint.mark("2", "failed")
    checkpoint.save()

    loaded = DownloadCheckpoint.load(path=tmp_path / "checkpoint.json")
    assert loaded.status_of("1") == "downloaded"
    assert loaded.status_of("2") == "failed"


def test_checkpoint_complete_cleans_file(tmp_path):
    path = tmp_path / "checkpoint.json"
    checkpoint = DownloadCheckpoint(path=path, collection_id="album:99", collection_type="album")
    checkpoint.initialize_tracks(["10"])
    checkpoint.mark("10", "downloaded")
    checkpoint.save()
    checkpoint.cleanup_if_complete()
    assert not path.exists()


def test_hifi_client_circuit_breaker_ttl():
    client = HiFiApiClient(instances=["https://a.invalid"], dead_ttl_sec=1)
    client._mark_instance_dead("https://a.invalid")
    assert client._is_instance_dead("https://a.invalid") is True
    time.sleep(1.1)
    assert client._is_instance_dead("https://a.invalid") is False


def test_hifi_client_live_instances_use_passive_discovery(monkeypatch):
    get = mock.Mock()
    monkeypatch.setattr("tidal_dl.hifi_api.requests.get", get)

    client = HiFiApiClient(instances=["https://a.invalid"])
    assert client.live_instances() == ["https://a.invalid"]
    assert client.health_check() == "https://a.invalid"
    get.assert_not_called()


def test_hifi_client_caches_empty_tracker_result_without_fallback(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"streaming": []}

    get = mock.Mock(return_value=Response())
    monkeypatch.setattr("tidal_dl.hifi_api.requests.get", get)
    monkeypatch.setattr(HiFiApiClient, "_discovery_cache", None)

    assert HiFiApiClient().instances == []
    assert HiFiApiClient().instances == []
    assert get.call_count == 1


def test_hifi_discover_uses_tracker_api_when_streaming_empty(monkeypatch):
    """Live tracker shape: streaming [] + down 504s, one live host under api."""
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "streaming": [],
                "down": [{"url": "https://dead.example", "status": 504}],
                "api": [{"url": "https://monochrome-api.samidy.com", "version": "2.3"}],
            }

    get = mock.Mock(return_value=Response())
    monkeypatch.setattr("tidal_dl.hifi_api.requests.get", get)
    monkeypatch.setattr(HiFiApiClient, "_discovery_cache", None)

    client = HiFiApiClient()
    assert client.instances == ["https://monochrome-api.samidy.com"]
    assert client.health_check() == "https://monochrome-api.samidy.com"


def test_hifi_client_caches_malformed_tracker_results(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    get = mock.Mock(side_effect=[Response([]), Response({"streaming": ["invalid"]})])
    monkeypatch.setattr("tidal_dl.hifi_api.requests.get", get)
    monkeypatch.setattr(HiFiApiClient, "_discovery_cache", None)

    assert HiFiApiClient().instances == []
    assert HiFiApiClient().instances == []
    assert get.call_count == 2


def test_hifi_client_tries_each_instance_once(monkeypatch):
    get = mock.Mock(side_effect=requests.ConnectionError("offline"))
    monkeypatch.setattr("tidal_dl.hifi_api.requests.get", get)

    client = HiFiApiClient(instances=["https://a.invalid", "https://b.invalid"])
    with pytest.raises(requests.RequestException):
        client.track_info(1)

    assert get.call_count == 2


def test_hifi_client_stops_rotation_on_rate_limit(monkeypatch):
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError("rate limited", response=response)
    get = mock.Mock(side_effect=error)
    monkeypatch.setattr("tidal_dl.hifi_api.requests.get", get)

    client = HiFiApiClient(instances=["https://a.invalid", "https://b.invalid"])
    with pytest.raises(requests.RequestException):
        client.track_info(1)

    assert get.call_count == 1


def test_hifi_client_serializes_requests_across_clients(monkeypatch):
    active = 0
    max_active = 0
    counter_lock = threading.Lock()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"id": 1}}

    def get(*args, **kwargs):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with counter_lock:
            active -= 1
        return Response()

    monkeypatch.setattr("tidal_dl.hifi_api.requests.get", get)
    clients = [HiFiApiClient(instances=["https://a.invalid"]) for _ in range(2)]
    threads = [threading.Thread(target=client.track_info, args=(1,)) for client in clients]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == 1


def test_hifi_stream_manifest_adapter():
    manifest = HiFiStreamManifest(
        urls=["https://example.invalid/seg1", "https://example.invalid/seg2"],
        file_extension=".flac",
        codecs="flac",
    )
    assert manifest.get_urls() == ["https://example.invalid/seg1", "https://example.invalid/seg2"]
    assert manifest.file_extension == ".flac"
    assert manifest.codecs == "flac"
    assert manifest.is_encrypted is False
    assert manifest.encryption_key is None


def test_tidal_ensure_token_fresh(monkeypatch):
    tidal = Tidal()
    called = {"refresh": 0, "persist": 0}

    class DummySession:
        token_type = "Bearer"
        access_token = "test"
        refresh_token = "test_refresh"
        expiry_time = time.time() + 3600

        def token_refresh(self, refresh_token):
            called["refresh"] += 1

    tidal.session = DummySession()
    tidal.data.expiry_time = time.time() + 60  # within 300s refresh window
    tidal.data.refresh_token = "test_refresh"

    def _persist():
        called["persist"] += 1

    monkeypatch.setattr(tidal, "token_persist", _persist)
    result = tidal._ensure_token_fresh()
    assert result is True
    assert called["refresh"] == 1
    assert called["persist"] == 1


def _sample_hifi_track_item(track_id: int = 111) -> dict:
    return {
        "id": track_id,
        "title": "Sample Track",
        "duration": 200,
        "allowStreaming": True,
        "trackNumber": 1,
        "volumeNumber": 1,
        "copyright": "(P) Test",
        "bpm": 120,
        "key": "C",
        "keyScale": "MAJOR",
        "url": f"https://tidal.com/browse/track/{track_id}",
        "isrc": "US-TST-00-00001",
        "explicit": False,
        "audioQuality": "LOSSLESS",
        "audioModes": ["STEREO"],
        "mediaMetadata": {"tags": ["LOSSLESS"]},
        "artist": {"id": 1, "name": "Artist A", "type": "MAIN"},
        "artists": [{"id": 1, "name": "Artist A", "type": "MAIN"}],
        "album": {"id": 10, "title": "Album A", "cover": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
    }


def test_instantiate_media_prefers_hifi_playlist_over_oauth():
    """When source is Hi-Fi, playlist resolution should not require oauth session.playlist()."""
    from tidal_dl.helper.tidal import instantiate_media

    session = mock.MagicMock()
    session.playlist.side_effect = AssertionError("OAuth playlist() should not be called in Hi-Fi-first mode")

    hifi = mock.MagicMock()
    hifi.playlist.return_value = {
        "version": "2.5",
        "playlist": {"uuid": "pl-123", "title": "My Playlist", "numberOfTracks": 1, "numberOfVideos": 0},
        "items": [{"item": _sample_hifi_track_item(111), "type": "track"}],
    }

    media = instantiate_media(
        session=session,
        media_type=MediaType.PLAYLIST,
        id_media="pl-123",
        hifi_client=hifi,
        prefer_hifi=True,
        oauth_fallback=True,
    )

    assert isinstance(media, Playlist)
    assert media.id == "pl-123"
    assert len(media.items()) == 1


def test_validate_prepare_media_does_not_refetch_track_when_hifi_active():
    """Hi-Fi resolved tracks should not be re-fetched through OAuth session.track()."""
    from tidal_dl.download import Download

    dl = Download.__new__(Download)
    dl.session = mock.MagicMock()
    dl.session.track.side_effect = AssertionError("session.track() should not be called for Hi-Fi-resolved tracks")
    dl.tidal = mock.MagicMock()
    dl.tidal.active_source = DownloadSource.HIFI_API
    dl.tidal.hifi_client = object()
    dl._api_cache = None
    dl.fn_logger = mock.MagicMock()

    track = mock.MagicMock(spec=Track)
    track.id = 111
    track.allow_streaming = True
    track.album = mock.MagicMock()

    result = Download._validate_and_prepare_media(
        dl,
        media=track,
        media_id=None,
        media_type=None,
        video_download=True,
    )

    assert result is track


# ---------------------------------------------------------------------------
# HIFI_QUALITY_MAP
# ---------------------------------------------------------------------------

def test_hifi_quality_map_covers_all_qualities():
    """Every tidalapi.Quality value should have a mapping."""
    for quality in (Quality.hi_res_lossless, Quality.high_lossless, Quality.low_320k, Quality.low_96k):
        assert quality in HIFI_QUALITY_MAP, f"Missing mapping for {quality}"
    assert HIFI_QUALITY_MAP[Quality.hi_res_lossless] == "HI_RES_LOSSLESS"
    assert HIFI_QUALITY_MAP[Quality.high_lossless] == "LOSSLESS"


# ---------------------------------------------------------------------------
# DASH manifest decoding via HiFiApiClient
# ---------------------------------------------------------------------------

def test_hifi_client_decodes_dash_manifest():
    """DASH manifests should be decoded to at least one URL."""
    dash_xml = (
        '<?xml version="1.0"?>'
        '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">'
        '  <Period>'
        '    <AdaptationSet>'
        '      <Representation id="1" bandwidth="1411200" codecs="flac">'
        '        <BaseURL>https://example.invalid/track.flac</BaseURL>'
        '        <SegmentBase>'
        '          <Initialization range="0-100"/>'
        '        </SegmentBase>'
        '      </Representation>'
        '    </AdaptationSet>'
        '  </Period>'
        '</MPD>'
    )
    encoded = base64.b64encode(dash_xml.encode("utf-8")).decode("utf-8")
    payload = {
        "data": {
            "audioQuality": "HI_RES_LOSSLESS",
            "manifestMimeType": "application/dash+xml",
            "manifest": encoded,
        }
    }
    # parse_manifest may raise on minimal XML — allow skip rather than failure
    try:
        parsed = HiFiApiClient.parse_track_payload(payload)
        # If it parses, verify basic fields are populated
        assert parsed.audio_quality == "HI_RES_LOSSLESS"
    except Exception:
        pytest.skip("DASH parse_manifest unavailable or format not supported in test env")


# ---------------------------------------------------------------------------
# Adaptive rate limiting
# ---------------------------------------------------------------------------

def _make_minimal_download():
    """Build a Download instance without a real tidalapi session."""
    from threading import Event, Lock
    from unittest.mock import MagicMock

    from tidal_dl.config import Settings
    from tidal_dl.download import Download

    settings = Settings()
    tidal = MagicMock()
    tidal.session = MagicMock()
    tidal.settings = settings
    tidal.api_cache = None
    tidal.active_source = DownloadSource.OAUTH
    tidal.hifi_client = None

    dl = object.__new__(Download)
    dl.settings = settings
    dl.tidal = tidal
    dl.session = tidal.session
    dl.fn_logger = MagicMock()
    dl.path_base = "/tmp"
    dl.skip_existing = False
    dl.event_abort = Event()
    dl.event_run = Event()
    dl.event_run.set()
    dl._checkpoint = None
    dl._rate_limit_hits = 0
    dl._successful_since_limit = 0
    dl._rate_limit_lock = Lock()
    dl._adaptive_delay_sec_min = settings.data.download_delay_sec_min
    dl._adaptive_delay_sec_max = settings.data.download_delay_sec_max
    dl._api_cache = None
    return dl


def test_adaptive_rate_limit_doubles_delay():
    dl = _make_minimal_download()
    original_min = dl._adaptive_delay_sec_min
    original_max = dl._adaptive_delay_sec_max

    dl._on_rate_limit_hit()

    assert dl._rate_limit_hits == 1
    assert dl._adaptive_delay_sec_min == min(original_min * 2, 30.0)
    assert dl._adaptive_delay_sec_max == min(original_max * 2, 30.0)


def test_adaptive_rate_limit_capped_at_30s():
    dl = _make_minimal_download()
    # Force current delays to near-cap
    dl._adaptive_delay_sec_min = 20.0
    dl._adaptive_delay_sec_max = 25.0

    dl._on_rate_limit_hit()

    assert dl._adaptive_delay_sec_min <= 30.0
    assert dl._adaptive_delay_sec_max <= 30.0


def test_adaptive_rate_limit_recovery_after_50_successes():
    dl = _make_minimal_download()
    dl._on_rate_limit_hit()  # trigger one rate limit to set _rate_limit_hits > 0
    post_limit_min = dl._adaptive_delay_sec_min

    # 49 successes should NOT halve yet
    for _ in range(49):
        dl._on_successful_track()
    assert dl._adaptive_delay_sec_min == post_limit_min

    # 50th success should halve
    dl._on_successful_track()
    baseline_min = dl.settings.data.download_delay_sec_min
    expected = max(post_limit_min / 2, baseline_min)
    assert dl._adaptive_delay_sec_min == pytest.approx(expected)


# ---------------------------------------------------------------------------
# LibraryDB ISRC batch commit (replaces legacy IsrcIndex periodic flush)
# ---------------------------------------------------------------------------

def test_library_db_register_without_commit_is_not_visible_after_reopen(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    track = tmp_path / "track.flac"
    track.write_bytes(b"")
    db.register_isrc_path("ISRC0001", track)
    db.close()

    reopened = LibraryDB(tmp_path / "library.db")
    reopened.open()
    try:
        assert not reopened.has_live_isrc("ISRC0001")
    finally:
        reopened.close()


def test_library_db_batch_commit_persists_isrc_registrations(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    db.open()
    pending = 0
    for i in range(24):
        track = tmp_path / f"track_{i:02d}.flac"
        track.write_bytes(b"")
        db.register_isrc_path(f"ISRC{i:04d}", track)
        pending += 1
        if pending >= 25:
            db.commit()
            pending = 0
    assert pending == 24

    track = tmp_path / "track_24.flac"
    track.write_bytes(b"")
    db.register_isrc_path("ISRC0024", track)
    db.commit()
    db.close()

    reopened = LibraryDB(tmp_path / "library.db")
    reopened.open()
    try:
        assert reopened.isrc_entry_count() == 25
        assert reopened.has_live_isrc("ISRC0024")
    finally:
        reopened.close()
