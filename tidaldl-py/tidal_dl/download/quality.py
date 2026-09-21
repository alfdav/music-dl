"""Audio-quality negotiation for Tidal catalog, playbackInfo, and DASH."""

from __future__ import annotations

from tidal_dl.constants import HIFI_QUALITY_MAP, quality_name
from tidal_dl.dash import Representation

_HIRES_TIERS = frozenset({"HI_RES", "HI_RES_LOSSLESS"})
_HIRES_TAGS = frozenset({"HIRES_LOSSLESS", "HIRES", "HI_RES_LOSSLESS", "HI_RES", "MQA"})
_HIRES_FORMATS = frozenset({"FLAC_HIRES"})


def normalize_quality_name(value: object | None) -> str:
    if value is None:
        return ""
    return quality_name(value).upper() if hasattr(value, "value") or isinstance(value, str) else str(value).upper()


def parse_representation_params(representation_id: str | None) -> tuple[str, int | None, int | None]:
    raw = str(representation_id or "").strip()
    if not raw:
        return "", None, None
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    kind = parts[0].upper() if parts else ""
    rate = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    depth = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    return kind, rate, depth


def delivery_is_hires(
    quality: object | None,
    bit_depth: int | None = None,
    sample_rate: int | None = None,
    representation_id: str | None = None,
) -> bool:
    kind, rate, depth = parse_representation_params(representation_id)
    if kind == "FLAC_HIRES":
        return True
    name = normalize_quality_name(quality)
    if name in _HIRES_TIERS:
        return not (
            bit_depth is not None and bit_depth <= 16 and sample_rate is not None and sample_rate <= 44100
        )
    resolved_depth = bit_depth if bit_depth is not None else depth
    resolved_rate = sample_rate if sample_rate is not None else rate
    return bool(
        (resolved_depth is not None and resolved_depth > 16)
        or (resolved_rate is not None and resolved_rate > 44100)
    )


def delivery_is_cd_lossless(
    quality: object | None,
    bit_depth: int | None = None,
    sample_rate: int | None = None,
    representation_id: str | None = None,
) -> bool:
    if delivery_is_hires(quality, bit_depth, sample_rate, representation_id):
        return False
    kind, rate, depth = parse_representation_params(representation_id)
    if kind == "FLAC":
        return True
    name = normalize_quality_name(quality)
    if name == "LOSSLESS":
        return True
    resolved_depth = bit_depth if bit_depth is not None else depth
    resolved_rate = sample_rate if sample_rate is not None else rate
    labeled_lossless = name in _HIRES_TIERS or kind.startswith("FLAC")
    return bool(
        labeled_lossless
        and resolved_depth is not None
        and resolved_depth <= 16
        and resolved_rate is not None
        and resolved_rate <= 44100
    )


def tidal_offers_hires(catalog_tags: object | None, manifest_formats: list[str] | None) -> bool:
    if manifest_formats:
        return bool({str(item).upper() for item in manifest_formats} & _HIRES_FORMATS)
    tags = {str(tag).upper() for tag in (catalog_tags or [])}
    return bool(tags & _HIRES_TAGS)


def should_require_hires_delivery(
    requested_wants_hires: bool,
    catalog_lists_hires: bool,
    manifest_formats: list[str] | None,
) -> bool:
    if not requested_wants_hires:
        return False
    if manifest_formats:
        return tidal_offers_hires(None, manifest_formats)
    return catalog_lists_hires


def hifi_quality_param(requested: object | None) -> str:
    name = normalize_quality_name(requested)
    if name in _HIRES_TIERS or name in {"HIRES_LOSSLESS", "HIRES"}:
        return "HI_RES_LOSSLESS"
    return HIFI_QUALITY_MAP.get(name, name or "LOSSLESS")


def _jsonapi_attributes(body: object) -> dict:
    if not isinstance(body, dict):
        return {}
    data = body.get("data")
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        return {}
    attrs = data.get("attributes") or {}
    return attrs if isinstance(attrs, dict) else {}


def coerce_format_list(formats: object | None) -> list[str] | None:
    if formats is None:
        return None
    if isinstance(formats, str):
        items = [part.strip() for part in formats.split(",") if part.strip()]
        return items or None
    if isinstance(formats, (list, tuple)):
        items = [str(item).strip() for item in formats if str(item).strip()]
        return items or None
    return None


def fetch_track_manifest_formats(
    access_token: str,
    track_id: int | str,
    timeout: float = 8.0,
) -> list[str] | None:
    """Return OpenAPI trackManifests formats for this user token, or None.

    ``formats`` is an OpenAPI array. Tidal Web sends repeated keys
    (``formats=FLAC&formats=FLAC_HIRES``), which ``requests`` does for a list.
    An empty or missing list is unknown, not “Tidal has no Hi-Res.”
    """
    import requests

    response = requests.get(
        f"https://openapi.tidal.com/v2/trackManifests/{track_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.api+json",
        },
        params={
            "adaptive": "true",
            "formats": ["FLAC", "FLAC_HIRES"],
            "manifestType": "MPEG_DASH",
            "uriScheme": "HTTPS",
            "usage": "PLAYBACK",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return coerce_format_list(_jsonapi_attributes(response.json()).get("formats"))


def unwrap_playback_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    if isinstance(data, dict) and (
        "manifest" in data or "audioQuality" in data or "manifestMimeType" in data
    ):
        return data
    if "manifest" in payload or "audioQuality" in payload or "manifestMimeType" in payload:
        return payload
    return data if isinstance(data, dict) else {}


def _rep_score(rep: Representation) -> tuple[int, int, int, int]:
    kind, rate, depth = parse_representation_params(getattr(rep, "id", None))
    hires = 1 if kind == "FLAC_HIRES" or delivery_is_hires(None, depth, rate, getattr(rep, "id", None)) else 0
    try:
        bandwidth = int(getattr(rep, "bandwidth", None) or 0)
    except (TypeError, ValueError):
        bandwidth = 0
    return (hires, depth or 0, rate or 0, bandwidth)


def _is_flac_representation(rep: Representation) -> bool:
    codec = str(getattr(rep, "codec", "") or "").lower()
    kind, _rate, _depth = parse_representation_params(getattr(rep, "id", None))
    return "flac" in codec or kind.startswith("FLAC")


def select_highest_flac_representation(representations: list[Representation]) -> Representation | None:
    pool = [rep for rep in representations if _is_flac_representation(rep)]
    if not pool:
        return None
    return max(pool, key=_rep_score)
