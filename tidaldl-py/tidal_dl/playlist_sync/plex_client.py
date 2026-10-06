"""Plain Plex HTTP API. The token travels only in the X-Plex-Token header.

No method here deletes, moves, clears, or edits a playlist or a library item.
The only mutation of an existing playlist is appending items at the end.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from tidal_dl.playlist_sync.plex_token import PlexToken
from tidal_dl.playlist_sync.unicode_norm import nfc_path

_PAGE = 100
_PRODUCT = "music-dl"
_CLIENT_ID = "music-dl"


class PlexError(Exception):
    """A Plex call failed. The message is status, method, and path. No query, no headers."""

    def __init__(self, status_code: int, method: str, path: str) -> None:
        self.status_code = int(status_code)
        self.method = method.upper()
        self.path = _path_only(path)
        super().__init__(f"{self.status_code} {self.method} {self.path}")


class PlexWriteBlocked(PlexError):
    """A write was refused before any network call. Used when the client is read-only."""

    def __init__(self, method: str, path: str) -> None:
        super().__init__(0, method, path)


class PlexClient:
    """JSON client for one Plex server and one library section."""

    def __init__(
        self,
        base_url: str,
        token: PlexToken,
        section_id: str,
        *,
        session: Any | None = None,
        timeout: float = 15,
        read_only: bool = False,
    ) -> None:
        self._base_url = _base_without_query(base_url)
        self._token = token
        self._section_id = str(section_id).strip()
        self._session = session
        self._timeout = timeout
        self._read_only = read_only
        self._machine_id: str | None = None

    @property
    def section_id(self) -> str:
        return self._section_id

    def __repr__(self) -> str:
        return f"PlexClient(section={self._section_id})"

    def machine_identifier(self) -> str:
        if self._machine_id:
            return self._machine_id
        payload = self._request("GET", "/identity")
        machine = str(_container(payload).get("machineIdentifier") or "")
        if not machine:
            raise PlexError(0, "GET", "/identity")
        self._machine_id = machine
        return machine

    def list_audio_playlists(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/playlists", params={"playlistType": "audio"})
        container = _container(payload)
        rows = _metadata(container)
        if not rows:
            rows = _named_list(container.get("Playlist"))
        listed: list[dict[str, Any]] = []
        for row in rows:
            kind = str(row.get("playlistType") or "audio").casefold()
            if kind != "audio":
                continue
            key = row.get("ratingKey")
            if key is None or str(key) == "":
                continue
            listed.append(
                {
                    "rating_key": str(key),
                    "title": str(row.get("title") or ""),
                    "smart": _smart_flag(row.get("smart")),
                }
            )
        return listed

    def playlist_items(self, playlist_key: str) -> list[dict[str, Any]]:
        path = f"/playlists/{playlist_key}/items"
        start = 0
        items: list[dict[str, Any]] = []
        while True:
            payload = self._request(
                "GET",
                path,
                extra_headers={
                    "X-Plex-Container-Start": str(start),
                    "X-Plex-Container-Size": str(_PAGE),
                },
            )
            container = _container(payload)
            batch = _metadata(container)
            items.extend(batch)
            if not batch:
                break
            start += len(batch)
            total = _total_size(container)
            if total is None or start >= total:
                break
        return items

    def create_playlist(self, title: str, first_rating_key: str) -> str:
        self._block_write("POST", "/playlists")
        payload = self._request(
            "POST",
            "/playlists",
            params={
                "type": "audio",
                "title": title,
                "smart": "0",
                "uri": self._metadata_uri([first_rating_key]),
            },
            write=True,
        )
        key = _first_rating_key(payload)
        if not key:
            raise PlexError(0, "POST", "/playlists")
        return key

    def add_to_playlist(self, playlist_key: str, rating_keys: list[str]) -> None:
        path = f"/playlists/{playlist_key}/items"
        self._block_write("PUT", path)
        if not rating_keys:
            return
        self._request("PUT", path, params={"uri": self._metadata_uri(rating_keys)}, write=True)

    def scan_path(self, server_folder: str) -> None:
        """Ask Plex to scan one folder. Read-only mode blocks this before any request."""
        path = f"/library/sections/{self._section_id}/refresh"
        self._block_write("GET", path)
        self._request("GET", path, params={"path": server_folder}, write=True)

    def search_tracks(self, title: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"/library/sections/{self._section_id}/all",
            params={"type": "10", "title": title},
        )
        return _metadata(_container(payload))

    def recently_added_tracks(self, limit: int = 100) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"/library/sections/{self._section_id}/all",
            params={"type": "10", "sort": "addedAt:desc"},
            extra_headers={
                "X-Plex-Container-Start": "0",
                "X-Plex-Container-Size": str(limit),
            },
        )
        return _metadata(_container(payload))

    def _metadata_uri(self, rating_keys: list[str]) -> str:
        machine = self.machine_identifier()
        joined = ",".join(rating_keys)
        return f"server://{machine}/com.plexapp.plugins.library/library/metadata/{joined}"

    def _block_write(self, method: str, path: str) -> None:
        if self._read_only:
            raise PlexWriteBlocked(method, path)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        extra_headers: Mapping[str, str] | None = None,
        write: bool = False,
    ) -> Any:
        safe_path = _path_only(path)
        verb = method.upper()
        if self._read_only and (write or verb != "GET"):
            raise PlexWriteBlocked(verb, safe_path)
        headers = {
            "Accept": "application/json",
            "X-Plex-Token": self._token.reveal(),
            "X-Plex-Product": _PRODUCT,
            "X-Plex-Client-Identifier": _CLIENT_ID,
        }
        if extra_headers:
            headers.update(extra_headers)
        url = self._base_url + safe_path
        try:
            response = self._session_or_new().request(
                verb,
                url,
                params=None if params is None else dict(params),
                headers=headers,
                timeout=self._timeout,
            )
        except Exception:  # noqa: BLE001 — transport errors must not carry headers or the token
            raise PlexError(0, verb, safe_path) from None
        status = int(getattr(response, "status_code", 0) or 0)
        if status >= 400 or status < 200:
            raise PlexError(status, verb, safe_path)
        try:
            return response.json()
        except Exception:  # noqa: BLE001 — a bad body is a PlexError, never the raw payload
            raise PlexError(status, verb, safe_path) from None

    def _session_or_new(self) -> Any:
        if self._session is not None:
            return self._session
        import requests

        self._session = requests.Session()
        return self._session


def file_paths(metadata: Mapping[str, Any]) -> list[str]:
    """NFC file paths from Media[].Part[].file."""
    found: list[str] = []
    media = metadata.get("Media") or []
    if isinstance(media, Mapping):
        media = [media]
    if not isinstance(media, list):
        return found
    for item in media:
        if not isinstance(item, Mapping):
            continue
        parts = item.get("Part") or []
        if isinstance(parts, Mapping):
            parts = [parts]
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            raw = part.get("file")
            if raw:
                found.append(nfc_path(str(raw)))
    return found


def _base_without_query(base_url: str) -> str:
    parts = urlsplit((base_url or "").strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _path_only(path: str) -> str:
    text = path.split("?", 1)[0]
    if not text.startswith("/"):
        return "/" + text
    return text


def _container(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("MediaContainer", payload)
    return raw if isinstance(raw, dict) else {}


def _metadata(container: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _named_list(container.get("Metadata"))


def _named_list(raw: object) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        return [raw]
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _total_size(container: Mapping[str, Any]) -> int | None:
    raw = container.get("totalSize")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _smart_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    text = str(value or "").strip().casefold()
    return text in {"1", "true", "yes"}


def _first_rating_key(payload: object) -> str:
    container = _container(payload)
    direct = container.get("ratingKey")
    if direct is not None and str(direct) != "":
        return str(direct)
    for row in _metadata(container) or _named_list(container.get("Playlist")):
        key = row.get("ratingKey")
        if key is not None and str(key) != "":
            return str(key)
    return ""
