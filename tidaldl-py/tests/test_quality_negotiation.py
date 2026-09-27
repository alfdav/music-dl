"""Issue #188: Hi-Res quality negotiation from real Tidal API shapes.

Live OAuth playbackinfopostpaywall (Tidal Web, 2026-09-21, track 66024828
Leonard Cohen — If I Didn't Have Your Love) returned LOSSLESS 16/44.1 BTS
while catalog tags were HIRES_LOSSLESS and OpenAPI trackManifests listed
FLAC_HIRES with DASH representation id FLAC_HIRES,44100,24.
"""

from __future__ import annotations

import base64
import json

import pytest
import requests
from tidalapi import Quality

from tidal_dl.constants import HIFI_QUALITY_MAP, quality_name
from tidal_dl.download.quality import (
    delivered_quality_label,
    delivery_is_cd_lossless,
    delivery_is_hires,
    hifi_quality_param,
    parse_representation_params,
    select_highest_flac_representation,
    should_require_hires_delivery,
    tidal_offers_hires,
    unwrap_playback_payload,
)
from tidal_dl.download.streams import StreamMixin, _delivery_is_cd_lossless
from tidal_dl.hifi_api import HiFiApiClient

# Real OpenAPI trackManifests representation ids from track 66024828.
_CD_REP_ID = "FLAC,44100,16"
_HIRES_REP_ID = "FLAC_HIRES,44100,24"

# Real playbackinfopostpaywall fields (secrets stripped).
_OAUTH_PLAYBACKINFO = {
    "trackId": 66024828,
    "assetPresentation": "FULL",
    "audioMode": "STEREO",
    "audioQuality": "LOSSLESS",
    "manifestMimeType": "application/vnd.tidal.bts",
    "bitDepth": 16,
    "sampleRate": 44100,
}

# Real catalog listing for the same track.
_CATALOG_TAGS = ["LOSSLESS", "HIRES_LOSSLESS"]
_CATALOG_AUDIO_QUALITY = "LOSSLESS"

# Real OpenAPI trackManifests attributes.formats for the same track.
_MANIFEST_FORMATS = ["FLAC", "FLAC_HIRES"]


def _adaptive_dash_xml() -> str:
    """Minimal adaptive MPD with CD first, then Hi-Res — live order can be either."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">'
        "  <Period>"
        '    <AdaptationSet contentType="audio" mimeType="audio/mp4">'
        f'      <Representation id="{_CD_REP_ID}" bandwidth="594128" codecs="flac" audioSamplingRate="44100">'
        "        <SegmentList>"
        '          <SegmentURL media="https://example.invalid/cd.flac"/>'
        "        </SegmentList>"
        "      </Representation>"
        f'      <Representation id="{_HIRES_REP_ID}" bandwidth="1281250" codecs="flac" audioSamplingRate="44100">'
        "        <SegmentList>"
        '          <SegmentURL media="https://example.invalid/hires.flac"/>'
        "        </SegmentList>"
        "      </Representation>"
        "    </AdaptationSet>"
        "  </Period>"
        "</MPD>"
    )


def _bts_manifest() -> str:
    return base64.b64encode(
        json.dumps(
            {
                "mimeType": "audio/flac",
                "codecs": "flac",
                "encryptionType": "NONE",
                "urls": ["https://example.invalid/cd.flac"],
            }
        ).encode()
    ).decode()


def test_oauth_playbackinfo_label_lossless_is_not_hires_when_16_44():
    assert delivery_is_hires(
        _OAUTH_PLAYBACKINFO["audioQuality"],
        _OAUTH_PLAYBACKINFO["bitDepth"],
        _OAUTH_PLAYBACKINFO["sampleRate"],
    ) is False
    assert delivery_is_cd_lossless(
        _OAUTH_PLAYBACKINFO["audioQuality"],
        _OAUTH_PLAYBACKINFO["bitDepth"],
        _OAUTH_PLAYBACKINFO["sampleRate"],
    ) is True


def test_lossless_label_with_24bit_is_hires_delivery():
    """Tidal sometimes labels a 24-bit stream LOSSLESS. Bit depth wins."""
    assert _delivery_is_cd_lossless("LOSSLESS", 24, 96000) is False
    assert delivery_is_hires("LOSSLESS", 24, 96000) is True
    assert delivery_is_cd_lossless("LOSSLESS", 24, 44100) is False


def test_hires_label_with_missing_params_is_not_forced_cd():
    assert delivery_is_cd_lossless("HI_RES_LOSSLESS", None, None) is False
    assert delivery_is_hires("HI_RES_LOSSLESS", None, None) is True


def test_hires_label_with_cd_params_is_cd_delivery():
    """Tidal sometimes labels the 16/44.1 fallback HI_RES_LOSSLESS."""
    assert delivery_is_hires("HI_RES_LOSSLESS", 16, 44100) is False
    assert delivery_is_cd_lossless("HI_RES_LOSSLESS", 16, 44100) is True
    assert delivery_is_hires("HI_RES", 16, 44100) is False
    assert delivery_is_cd_lossless("HI_RES", 16, 44100) is True


def test_representation_id_from_track_manifests_is_hires():
    kind, rate, depth = parse_representation_params(_HIRES_REP_ID)
    assert kind == "FLAC_HIRES"
    assert rate == 44100
    assert depth == 24
    assert delivery_is_hires("LOSSLESS", None, None, representation_id=_HIRES_REP_ID) is True
    assert delivery_is_cd_lossless("LOSSLESS", None, None, representation_id=_CD_REP_ID) is True


def test_catalog_tags_and_audio_quality_disagree_on_hires():
    """Listing metadata uses HIRES_LOSSLESS tags; audioQuality stays LOSSLESS."""
    assert tidal_offers_hires(_CATALOG_TAGS, None) is True
    assert _CATALOG_AUDIO_QUALITY == "LOSSLESS"
    assert tidal_offers_hires(["LOSSLESS"], ["FLAC"]) is False
    assert tidal_offers_hires(["LOSSLESS"], _MANIFEST_FORMATS) is True


def test_should_require_hires_only_when_tidal_actually_offers_it():
    assert should_require_hires_delivery(True, True, None) is True
    assert should_require_hires_delivery(True, True, _MANIFEST_FORMATS) is True
    assert should_require_hires_delivery(True, True, ["FLAC"]) is False
    assert should_require_hires_delivery(True, False, ["FLAC"]) is False
    assert should_require_hires_delivery(False, True, _MANIFEST_FORMATS) is False
    assert should_require_hires_delivery(True, True, []) is True
    assert should_require_hires_delivery(True, False, []) is False


def test_hifi_quality_param_never_defaults_hires_request_to_lossless():
    assert hifi_quality_param(Quality.hi_res_lossless) == "HI_RES_LOSSLESS"
    assert hifi_quality_param("HI_RES_LOSSLESS") == "HI_RES_LOSSLESS"
    assert hifi_quality_param("HI_RES") == "HI_RES_LOSSLESS"
    assert hifi_quality_param("HIRES_LOSSLESS") == "HI_RES_LOSSLESS"
    assert HIFI_QUALITY_MAP.get(quality_name(Quality.hi_res_lossless)) == "HI_RES_LOSSLESS"
    assert hifi_quality_param(Quality.high_lossless) == "LOSSLESS"


def test_unwrap_playback_payload_accepts_flat_and_wrapped_tidal_shapes():
    wrapped = {"version": "2.3", "data": dict(_OAUTH_PLAYBACKINFO)}
    assert unwrap_playback_payload(wrapped)["audioQuality"] == "LOSSLESS"
    assert unwrap_playback_payload(dict(_OAUTH_PLAYBACKINFO))["audioQuality"] == "LOSSLESS"
    assert unwrap_playback_payload({"data": {}}) == {}
    listed = {"data": [dict(_OAUTH_PLAYBACKINFO)]}
    assert unwrap_playback_payload(listed)["audioQuality"] == "LOSSLESS"


def test_hifi_parses_flat_tidal_playbackinfo_payload():
    payload = {
        **_OAUTH_PLAYBACKINFO,
        "manifest": _bts_manifest(),
    }
    parsed = HiFiApiClient.parse_track_payload(payload)
    assert parsed.audio_quality == "LOSSLESS"
    assert parsed.bit_depth == 16
    assert parsed.sample_rate == 44100
    assert parsed.urls == ["https://example.invalid/cd.flac"]
    assert parsed.asset_presentation == "FULL"


def test_hifi_payload_keeps_preview_presentation():
    """Track 66024828: Hi-Fi stamped HI_RES_LOSSLESS on a PREVIEW clip."""
    from tidal_dl.download.quality import is_preview_presentation

    payload = {
        **_OAUTH_PLAYBACKINFO,
        "assetPresentation": "PREVIEW",
        "audioQuality": "HI_RES_LOSSLESS",
        "bitDepth": 24,
        "sampleRate": 44100,
        "manifest": _bts_manifest(),
    }
    parsed = HiFiApiClient.parse_track_payload(payload)
    assert parsed.asset_presentation == "PREVIEW"
    assert parsed.audio_quality == "HI_RES_LOSSLESS"
    assert parsed.bit_depth == 24
    assert is_preview_presentation(parsed.asset_presentation) is True
    assert is_preview_presentation("full") is False
    assert is_preview_presentation(None) is False


def test_decoded_duration_far_short_of_catalog_is_a_preview():
    """29.91s decoded against a 216s track is a preview; a few seconds short is not."""
    from tidal_dl.download.quality import duration_is_far_short

    assert duration_is_far_short(29.91, 216) is True
    assert duration_is_far_short(100, 216) is True
    assert duration_is_far_short(210, 216) is False
    assert duration_is_far_short(200, 216) is False
    assert duration_is_far_short(216, 216) is False
    assert duration_is_far_short(None, 216) is False
    assert duration_is_far_short(30, 0) is False


def test_hifi_dash_selects_flac_hires_not_first_cd_representation():
    encoded = base64.b64encode(_adaptive_dash_xml().encode()).decode()
    payload = {
        "data": {
            "audioQuality": "LOSSLESS",
            "manifestMimeType": "application/dash+xml",
            "manifest": encoded,
            "bitDepth": 16,
            "sampleRate": 44100,
        }
    }
    parsed = HiFiApiClient.parse_track_payload(payload)
    assert parsed.urls == ["https://example.invalid/hires.flac"]
    assert parsed.audio_quality == "HI_RES_LOSSLESS"
    assert parsed.bit_depth == 24
    assert parsed.sample_rate == 44100
    assert delivery_is_cd_lossless(parsed.audio_quality, parsed.bit_depth, parsed.sample_rate) is False


def test_hifi_dash_picks_flac_hires_across_adaptation_sets():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">'
        "  <Period>"
        '    <AdaptationSet contentType="audio" mimeType="audio/mp4">'
        '      <Representation id="AACLC,44100,16" bandwidth="256000" codecs="mp4a.40.2">'
        "        <SegmentList>"
        '          <SegmentURL media="https://example.invalid/aac.m4a"/>'
        "        </SegmentList>"
        "      </Representation>"
        "    </AdaptationSet>"
        '    <AdaptationSet contentType="audio" mimeType="audio/mp4">'
        f'      <Representation id="{_CD_REP_ID}" bandwidth="594128" codecs="flac">'
        "        <SegmentList>"
        '          <SegmentURL media="https://example.invalid/cd.flac"/>'
        "        </SegmentList>"
        "      </Representation>"
        f'      <Representation id="{_HIRES_REP_ID}" bandwidth="1281250" codecs="flac">'
        "        <SegmentList>"
        '          <SegmentURL media="https://example.invalid/hires.flac"/>'
        "        </SegmentList>"
        "      </Representation>"
        "    </AdaptationSet>"
        "  </Period>"
        "</MPD>"
    )
    encoded = base64.b64encode(xml.encode()).decode()
    parsed = HiFiApiClient.parse_track_payload(
        {
            "data": {
                "audioQuality": "LOSSLESS",
                "manifestMimeType": "application/dash+xml",
                "manifest": encoded,
                "bitDepth": 16,
                "sampleRate": 44100,
            }
        }
    )
    assert parsed.urls == ["https://example.invalid/hires.flac"]
    assert parsed.audio_quality == "HI_RES_LOSSLESS"
    assert parsed.bit_depth == 24


def _rep(rep_id: str, bandwidth: str, codec: str):
    from tidal_dl.dash import Representation

    return Representation(
        id=rep_id,
        bandwidth=bandwidth,
        codec=codec,
        base_url="",
        segment_template=None,
        segment_list=None,
    )


def test_select_highest_flac_representation_prefers_hires_id():
    cd = _rep(_CD_REP_ID, "594128", "flac")
    hires = _rep(_HIRES_REP_ID, "1281250", "flac")
    chosen = select_highest_flac_representation([cd, hires])
    assert chosen is hires
    chosen_first_hires = select_highest_flac_representation([hires, cd])
    assert chosen_first_hires is hires


def test_select_highest_flac_representation_skips_aac_across_sets():
    aac = _rep("AACLC,44100,16", "256000", "mp4a.40.2")
    cd = _rep(_CD_REP_ID, "594128", "flac")
    hires = _rep(_HIRES_REP_ID, "1281250", "flac")
    assert select_highest_flac_representation([aac, cd, hires]) is hires
    assert select_highest_flac_representation([aac]) is None


def test_hifi_dash_aac_only_keeps_aac_urls_instead_of_empty():
    """LOW/HIGH Hi-Fi DASH is AAC-only. Dropping it yields empty URLs and QualityMismatchError."""
    from tidal_dl.download.quality import select_best_audio_representation

    aac = _rep("AACLC,44100,16", "256000", "mp4a.40.2")
    assert select_highest_flac_representation([aac]) is None
    assert select_best_audio_representation([aac]) is aac

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">'
        "  <Period>"
        '    <AdaptationSet contentType="audio" mimeType="audio/mp4">'
        '      <Representation id="AACLC,44100,16" bandwidth="256000" codecs="mp4a.40.2">'
        "        <SegmentList>"
        '          <SegmentURL media="https://example.invalid/aac.m4a"/>'
        "        </SegmentList>"
        "      </Representation>"
        "    </AdaptationSet>"
        "  </Period>"
        "</MPD>"
    )
    encoded = base64.b64encode(xml.encode()).decode()
    parsed = HiFiApiClient.parse_track_payload(
        {
            "data": {
                "audioQuality": "HIGH",
                "manifestMimeType": "application/dash+xml",
                "manifest": encoded,
            }
        }
    )
    assert parsed.urls == ["https://example.invalid/aac.m4a"]
    assert "mp4a" in (parsed.codecs or "")
    assert parsed.audio_quality == "HIGH"


def test_listed_hires_without_flac_hires_capability_keeps_cd(tmp_path):
    """Stale HIRES tags + trackManifests FLAC-only must not fail-closed."""
    from tests.test_hires_flac_quality import (
        _download_stream_subject,
        _listed_hires_track,
        _oauth_cd_stream,
    )

    oauth_stream = _oauth_cd_stream()
    track = _listed_hires_track(oauth_stream)
    subject, hifi_calls = _download_stream_subject()
    subject.tidal.hifi_client = type(
        "DeadHiFi",
        (),
        {
            "track_stream": staticmethod(
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    requests.RequestException("No live Hi-Fi API instances available.")
                )
            )
        },
    )()
    subject._track_manifest_formats = lambda _media, **_kwargs: ["FLAC"]

    manifest, extension, _extract, media_stream = subject._get_stream_info(track)

    assert extension == ".flac"
    assert StreamMixin._requested_audio_quality(subject) == Quality.hi_res_lossless
    assert quality_name(media_stream.audio_quality).upper() == "LOSSLESS"
    assert manifest.get_urls() == ["https://example.invalid/cd.flac"]
    assert hifi_calls == []


def test_fetch_track_manifest_formats_reads_openapi_attributes(monkeypatch):
    from tidal_dl.download.quality import fetch_track_manifest_formats

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "id": "66024828",
                    "type": "trackManifests",
                    "attributes": {
                        "formats": ["FLAC", "FLAC_HIRES"],
                        "trackPresentation": "FULL",
                    },
                }
            }

    captured: dict = {}

    def fake_get(*_args, **kwargs):
        captured["params"] = kwargs.get("params")
        return Response()

    monkeypatch.setattr("requests.get", fake_get)
    assert fetch_track_manifest_formats("token", 66024828) == ["FLAC", "FLAC_HIRES"]
    # OpenAPI `formats` is an array (Tidal Web: formats=FLAC&formats=FLAC_HIRES).
    assert captured["params"]["formats"] == ["FLAC", "FLAC_HIRES"]


def test_fetch_track_manifest_formats_jsonapi_list_and_string(monkeypatch):
    from tidal_dl.download.quality import fetch_track_manifest_formats

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {
                        "type": "trackManifests",
                        "attributes": {"formats": "FLAC,FLAC_HIRES"},
                    }
                ]
            }

    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: Response())
    assert fetch_track_manifest_formats("token", 66024828) == ["FLAC", "FLAC_HIRES"]


def test_fetch_track_manifest_formats_empty_is_unknown(monkeypatch):
    from tidal_dl.download.quality import fetch_track_manifest_formats

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"attributes": {"formats": []}}}

    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: Response())
    assert fetch_track_manifest_formats("token", 66024828) is None


def test_listed_hires_with_flac_hires_capability_still_fail_closed_without_unencrypted():
    from tests.test_hires_flac_quality import _download_stream_subject, _listed_hires_track, _oauth_cd_stream
    from tidal_dl.download.streams import QualityMismatchError

    oauth_stream = _oauth_cd_stream()
    track = _listed_hires_track(oauth_stream)
    subject, _calls = _download_stream_subject()
    subject.tidal.hifi_client = type(
        "DeadHiFi",
        (),
        {
            "track_stream": staticmethod(
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    requests.RequestException("No live Hi-Fi API instances available.")
                )
            )
        },
    )()
    subject._track_manifest_formats = lambda _media, **_kwargs: list(_MANIFEST_FORMATS)

    with pytest.raises(QualityMismatchError, match="FLAC_HIRES"):
        subject._get_stream_info(track)


def test_listed_hires_empty_manifest_formats_still_fail_closed():
    from tests.test_hires_flac_quality import _download_stream_subject, _listed_hires_track, _oauth_cd_stream
    from tidal_dl.download.streams import QualityMismatchError

    oauth_stream = _oauth_cd_stream()
    track = _listed_hires_track(oauth_stream)
    subject, _calls = _download_stream_subject()
    subject.tidal.hifi_client = type(
        "DeadHiFi",
        (),
        {
            "track_stream": staticmethod(
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    requests.RequestException("No live Hi-Fi API instances available.")
                )
            )
        },
    )()
    subject._track_manifest_formats = lambda _media, **_kwargs: []

    with pytest.raises(QualityMismatchError, match="listed Hi-Res"):
        subject._get_stream_info(track)


def test_hifi_primary_cd_with_flac_hires_fail_closes():
    from tests.test_hires_flac_quality import _download_stream_subject, _listed_hires_track, _oauth_cd_stream
    from tidal_dl.constants import DownloadSource
    from tidal_dl.download.streams import QualityMismatchError
    from tidal_dl.hifi_api import HiFiStreamResult

    cd_hifi = HiFiStreamResult(
        urls=["https://example.invalid/cd.flac"],
        file_extension=".flac",
        codecs="flac",
        mime_type="audio/flac",
        audio_quality="HI_RES_LOSSLESS",
        bit_depth=16,
        sample_rate=44100,
    )
    subject, _calls = _download_stream_subject(cd_hifi)
    subject.tidal.active_source = DownloadSource.HIFI_API
    subject._track_manifest_formats = lambda _media, **_kwargs: list(_MANIFEST_FORMATS)

    with pytest.raises(QualityMismatchError, match="FLAC_HIRES"):
        subject._get_stream_info(_listed_hires_track(_oauth_cd_stream()))


def _dead_hifi_subject():
    from tests.test_hires_flac_quality import _download_stream_subject

    subject, _calls = _download_stream_subject()
    subject.tidal.hifi_client = type(
        "DeadHiFi",
        (),
        {
            "track_stream": staticmethod(
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    requests.RequestException("No live Hi-Fi API instances available.")
                )
            )
        },
    )()
    subject._track_manifest_formats = lambda _media, **_kwargs: list(_MANIFEST_FORMATS)
    warnings: list[str] = []
    subject.fn_logger = type(
        "Logger",
        (),
        {
            "error": lambda *_args: None,
            "exception": lambda *_args: None,
            "warning": lambda _self, message: warnings.append(str(message)),
        },
    )()
    return subject, warnings


def test_delivered_quality_label_uses_cd_when_hires_stamp_is_16_44100():
    assert delivered_quality_label("HI_RES_LOSSLESS", 16, 44100) == "LOSSLESS"
    assert delivered_quality_label("HI_RES_LOSSLESS", 24, 44100) == "HI_RES_LOSSLESS"
    assert delivered_quality_label("LOSSLESS", 16, 44100) == "LOSSLESS"


def test_session_can_deliver_hires_treats_blank_as_unknown():
    from tidal_dl.download.quality import session_can_deliver_hires

    assert session_can_deliver_hires(None) is None
    assert session_can_deliver_hires("") is None
    assert session_can_deliver_hires("LOSSLESS") is False
    assert session_can_deliver_hires("HI_RES") is True
    assert session_can_deliver_hires("HI_RES_LOSSLESS") is True


def test_capped_session_accepts_cd_when_flac_hires_offered_and_hifi_down():
    from tests.test_hires_flac_quality import _listed_hires_track, _oauth_cd_stream
    from tidal_dl.constants import quality_name
    from tidal_dl.download.quality import SESSION_HIRES_FALLBACK_NOTICE

    subject, warnings = _dead_hifi_subject()
    subject.tidal.session_max_quality = "LOSSLESS"

    manifest, extension, _extract, media_stream = subject._get_stream_info(_listed_hires_track(_oauth_cd_stream()))

    assert extension == ".flac"
    assert quality_name(media_stream.audio_quality).upper() == "LOSSLESS"
    assert manifest.get_urls() == ["https://example.invalid/cd.flac"]
    assert subject.last_delivered_quality == "LOSSLESS"
    assert warnings == []
    subject._note_accepted_lossless_fallback()
    assert warnings == [SESSION_HIRES_FALLBACK_NOTICE]

    subject._get_stream_info(_listed_hires_track(_oauth_cd_stream()))
    subject._note_accepted_lossless_fallback()
    assert warnings == [SESSION_HIRES_FALLBACK_NOTICE]


def test_capable_session_still_fail_closes_when_flac_hires_and_hifi_down():
    from tests.test_hires_flac_quality import _listed_hires_track, _oauth_cd_stream
    from tidal_dl.download.streams import QualityMismatchError

    subject, warnings = _dead_hifi_subject()
    subject.tidal.session_max_quality = "HI_RES_LOSSLESS"

    with pytest.raises(QualityMismatchError, match="FLAC_HIRES"):
        subject._get_stream_info(_listed_hires_track(_oauth_cd_stream()))
    assert warnings == []


def test_unprobed_session_stays_fail_closed_when_flac_hires_and_hifi_down():
    from tests.test_hires_flac_quality import _listed_hires_track, _oauth_cd_stream
    from tidal_dl.download.streams import QualityMismatchError

    subject, _warnings = _dead_hifi_subject()
    assert getattr(subject.tidal, "session_max_quality", None) is None

    with pytest.raises(QualityMismatchError, match="FLAC_HIRES"):
        subject._get_stream_info(_listed_hires_track(_oauth_cd_stream()))


def test_restore_then_download_lazy_probes_capped_login():
    """Unprobed after silent restore must probe before the strict gate."""
    from tests.test_hires_flac_quality import _listed_hires_track, _oauth_cd_stream
    from tidal_dl.constants import quality_name
    from tidal_dl.download.quality import SESSION_HIRES_FALLBACK_NOTICE

    subject, warnings = _dead_hifi_subject()
    subject.tidal.session_max_quality = None

    def _probe():
        subject.tidal.session_max_quality = "LOSSLESS"

    subject.tidal._probe_subscription_quality = _probe

    _manifest, extension, _extract, media_stream = subject._get_stream_info(
        _listed_hires_track(_oauth_cd_stream())
    )

    assert extension == ".flac"
    assert quality_name(media_stream.audio_quality).upper() == "LOSSLESS"
    assert subject.tidal.session_max_quality == "LOSSLESS"
    assert subject.last_delivered_quality == "LOSSLESS"
    assert warnings == []
    subject._note_accepted_lossless_fallback()
    assert warnings == [SESSION_HIRES_FALLBACK_NOTICE]


def test_hires_labeled_cd_delivery_records_lossless_not_hires():
    """Tidal can stamp HI_RES_LOSSLESS on a 16/44.1 stream. Labels must be LOSSLESS."""
    from tests.test_hires_flac_quality import _listed_hires_track

    subject, _warnings = _dead_hifi_subject()
    subject.tidal.session_max_quality = "LOSSLESS"
    stream = type(
        "Stream",
        (),
        {
            "audio_quality": Quality.hi_res_lossless,
            "bit_depth": 16,
            "sample_rate": 44100,
            "get_stream_manifest": lambda self: type(
                "Manifest",
                (),
                {
                    "file_extension": ".flac",
                    "codecs": "flac",
                    "audio_quality": Quality.hi_res_lossless,
                    "bit_depth": 16,
                    "sample_rate": 44100,
                    "get_urls": lambda _self: ["https://example.invalid/cd.flac"],
                },
            )(),
        },
    )()

    subject._get_stream_info(_listed_hires_track(stream))

    assert subject.last_delivered_quality == "LOSSLESS"
