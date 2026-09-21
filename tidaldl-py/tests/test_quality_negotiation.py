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
