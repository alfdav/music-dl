"""TIDAL API key management with remote gist fallback.

See also:
  https://github.com/yaronzz/Tidal-Media-Downloader/commit/1d5b8cd8f65fd1def45d6406778248249d6dfbdf
  https://github.com/nathom/streamrip/tree/main/streamrip
"""

import json
from typing import Any, TypedDict, cast

import requests

from tidal_dl.constants import REQUESTS_TIMEOUT_SEC

__KEYS_JSON__: str = """
{
    "version": "1.0.1",
    "keys": [
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


def getItems() -> list[ApiKey]:
    return _API_KEYS["keys"]


def getVersion() -> str:
    return _API_KEYS["version"]


# Attempt to refresh API keys from a remote gist at import time.
try:
    _resp = requests.get(
        "https://api.github.com/gists/48d01f5a24b4b7b37f19443977c22cd6",
        timeout=REQUESTS_TIMEOUT_SEC,
    )
    _resp.raise_for_status()

    if _resp.status_code == 200:
        _resp_json = cast(dict[str, Any], _resp.json())
        _files = cast(dict[str, Any], _resp_json.get("files", {}))
        _file_data = cast(dict[str, Any], _files.get("tidal-api-key.json", {}))
        _content = cast(str, _file_data.get("content", ""))
        if _content:
            _API_KEYS = _load_api_keys(_content)
except requests.RequestException as _e:
    print(f"[music-dl] Could not refresh API keys from gist: {_e}")
