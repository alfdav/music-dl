"""TIDAL API key management with remote gist fallback.

See also:
  https://github.com/yaronzz/Tidal-Media-Downloader/commit/1d5b8cd8f65fd1def45d6406778248249d6dfbdf
  https://github.com/nathom/streamrip/tree/main/streamrip
"""

import json
from typing import Any, TypedDict, cast

import requests

from tidal_dl.constants import REQUESTS_TIMEOUT_SEC

# Key 0 (Tidal Web) is applied first at login. It reliably delivers LOSSLESS FLAC
# (v1.7.4) but typically cannot return HI_RES_LOSSLESS. Hi-Res FLAC needs a PKCE /
# Android-type client — proposed for Tidal auth v2, not switched here, and never
# by wiping token.json or auto-relogin.
__KEYS_JSON__: str = """
{
    "version": "1.0.2",
    "keys": [
        {
            "platform": "Tidal Web",
            "formats": "Normal/High/HiFi/Master",
            "clientId": "4N3n6Q1x95LL5K7p",
            "clientSecret": "oKOXfJW371cX6xaZ0PyhgGNBdNLlBZd4AKKYougMjik=",
            "valid": "True",
            "from": "sky8282/Tidal-Web-Downloader (streamrip#966)"
        },
        {
            "platform": "Android Auto",
            "formats": "Normal/High/HiFi/Master",
            "clientId": "zU4XHVVkc2tDPo4t",
            "clientSecret": "VJKhDFqJPqvsPVNBV6ukXTJmwlvbttP7wlMlrc72se4=",
            "valid": "True",
            "from": "1nikolas (https://github.com/yaronzz/Tidal-Media-Downloader/pull/840)"
        }
    ]
}
"""


class ApiKey(TypedDict):
    platform: str
    formats: str
    clientId: str
    clientSecret: str
    valid: str
    from_: str


class ApiKeysPayload(TypedDict):
    version: str
    keys: list[ApiKey]


def _api_key(data: dict[str, Any]) -> ApiKey:
    return {
        "platform": str(data.get("platform", "")),
        "formats": str(data.get("formats", "")),
        "clientId": str(data.get("clientId", "")),
        "clientSecret": str(data.get("clientSecret", "")),
        "valid": str(data.get("valid", "False")),
        "from_": str(data.get("from", "")),
    }


def _load_api_keys(payload: str) -> ApiKeysPayload:
    raw = cast(dict[str, Any], json.loads(payload))
    keys_raw = raw.get("keys", [])
    keys = [_api_key(item) for item in keys_raw if isinstance(item, dict)]
    return {"version": str(raw.get("version", "")), "keys": keys}


_API_KEYS: ApiKeysPayload = _load_api_keys(__KEYS_JSON__)

_ERROR_KEY: ApiKey = {
    "platform": "None",
    "formats": "",
    "clientId": "",
    "clientSecret": "",
    "valid": "False",
    "from_": "",
}


def getNum() -> int:
    return len(_API_KEYS["keys"])


def getItem(index: int) -> ApiKey:
    if index < 0 or index >= len(_API_KEYS["keys"]):
        return _ERROR_KEY
    return _API_KEYS["keys"][index]


def isItemValid(index: int) -> bool:
    return getItem(index).get("valid") == "True"


def first_valid_index() -> int:
    """Return the first valid key index, or -1 if none are valid."""
    for index, key in enumerate(_API_KEYS["keys"]):
        if key.get("valid") == "True" and key.get("clientId"):
            return index
    return -1


def getItems() -> list[ApiKey]:
    return _API_KEYS["keys"]


def getVersion() -> str:
    return _API_KEYS["version"]


def refresh_api_keys(timeout: float | None = None) -> bool:
    """Refresh API keys from the remote gist on demand."""
    global _API_KEYS

    try:
        resp = requests.get(
            "https://api.github.com/gists/48d01f5a24b4b7b37f19443977c22cd6",
            timeout=REQUESTS_TIMEOUT_SEC if timeout is None else timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[music-dl] Could not refresh API keys from gist: {exc}")
        return False

    resp_json = cast(dict[str, Any], resp.json())
    files = cast(dict[str, Any], resp_json.get("files", {}))
    file_data = cast(dict[str, Any], files.get("tidal-api-key.json", {}))
    content = cast(str, file_data.get("content", ""))
    if not content:
        return False

    try:
        remote = _load_api_keys(content)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"[music-dl] Could not parse API keys from gist: {exc}")
        return False

    # Keep bundled Hi-Fi clients when the gist is stale or lists them as invalid.
    bundled = _load_api_keys(__KEYS_JSON__)
    remote_ids = {key.get("clientId") for key in remote["keys"]}
    extras = [key for key in bundled["keys"] if key.get("clientId") and key["clientId"] not in remote_ids]
    remote["keys"].extend(extras)
    remote["keys"].sort(key=lambda key: key.get("clientId") != "4N3n6Q1x95LL5K7p")
    _API_KEYS = remote
    return True
