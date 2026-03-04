"""TIDAL API key management with remote gist fallback.

See also:
  https://github.com/yaronzz/Tidal-Media-Downloader/commit/1d5b8cd8f65fd1def45d6406778248249d6dfbdf
  https://github.com/nathom/streamrip/tree/main/streamrip
"""

import json

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

__API_KEYS__: dict = json.loads(__KEYS_JSON__)

__ERROR_KEY__: dict = {
    "platform": "None",
    "formats": "",
    "clientId": "",
    "clientSecret": "",
    "valid": "False",
}


def getNum() -> int:
    return len(__API_KEYS__["keys"])


def getItem(index: int) -> dict:
    if index < 0 or index >= len(__API_KEYS__["keys"]):
        return __ERROR_KEY__
    return __API_KEYS__["keys"][index]


def isItemValid(index: int) -> bool:
    return getItem(index).get("valid") == "True"


def getItems() -> list[dict]:
    return __API_KEYS__["keys"]


def getVersion() -> str:
    return __API_KEYS__["version"]


# Attempt to refresh API keys from a remote gist at import time.
try:
    _resp = requests.get(
        "https://api.github.com/gists/48d01f5a24b4b7b37f19443977c22cd6",
        timeout=REQUESTS_TIMEOUT_SEC,
    )
    _resp.raise_for_status()

    if _resp.status_code == 200:
        _content = _resp.json()["files"]["tidal-api-key.json"]["content"]
        __API_KEYS__ = json.loads(_content)
except requests.RequestException as _e:
    print(f"[tidal-dl] Could not refresh API keys from gist: {_e}")
