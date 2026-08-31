from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, ClassVar

import requests

from tidal_dl.constants import (
    HIFI_UPTIME_TRACKER_URLS,
    REQUESTS_TIMEOUT_SEC,
)
from tidal_dl.dash import parse_manifest


def _tracker_instance_urls(*groups: object) -> list[str]:
    """Collect instance URLs from tracker lists. `streaming` first, then `api`."""
    urls: list[str] = []
    seen: set[str] = set()
    for items in groups:
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip().rstrip("/")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


@dataclass
class HiFiStreamResult:
    urls: list[str]
    file_extension: str
    codecs: str
    mime_type: str
    audio_quality: str
    bit_depth: int | None = None
    sample_rate: int | None = None
    encryption_type: str = "NONE"


class HiFiApiClient:
    _discovery_cache: ClassVar[tuple[float, list[str]] | None] = None
    _discovery_lock: ClassVar[threading.Lock] = threading.Lock()
    _request_lock: ClassVar[threading.Lock] = threading.Lock()
    _discovery_ttl_sec: ClassVar[int] = 60

    def __init__(
        self,
        instances: list[str] | None = None,
        timeout: int = REQUESTS_TIMEOUT_SEC,
        dead_ttl_sec: int = 300,
    ) -> None:
        self.timeout = timeout
        self.dead_ttl_sec = dead_ttl_sec
        self.instances = [i.strip().rstrip("/") for i in (instances or []) if i and i.strip()]
        if not self.instances:
            self.instances = self.discover_instances()
        self._dead_instances: dict[str, float] = {}

    @staticmethod
    def _extension_from_mime(mime_type: str, codecs: str = "") -> str:
        mime = (mime_type or "").lower()
        codec = (codecs or "").lower()
        if "flac" in codec or "flac" in mime:
            return ".flac"
        if "mp4" in mime or "aac" in mime or "mp4a" in codec or codec.startswith("aac"):
            return ".m4a"
        return ".bin"

    @staticmethod
    def parse_track_payload(payload: dict[str, Any]) -> HiFiStreamResult:
        data = payload.get("data", {})
        manifest_mime_type = data.get("manifestMimeType", "")
        manifest_b64 = data.get("manifest", "")
        decoded = base64.b64decode(manifest_b64)

        if manifest_mime_type == "application/vnd.tidal.bts":
            manifest = json.loads(decoded.decode("utf-8"))
            mime_type = manifest.get("mimeType", "")
            codecs = manifest.get("codecs", "")
            urls = manifest.get("urls", []) or []
            encryption_type = manifest.get("encryptionType", "NONE")
        elif manifest_mime_type == "application/dash+xml":
            manifest_xml = decoded.decode("utf-8")
            parsed = parse_manifest(manifest_xml)
            urls = []
            codecs = ""
            for period in parsed.periods:
                for adaptation in period.adaptation_sets:
                    if not adaptation.representations:
                        continue
                    rep = adaptation.representations[0]
                    codecs = rep.codec or ""
                    urls = rep.segments
                    break
                if urls:
                    break
            mime_type = "audio/flac" if "flac" in (codecs or "").lower() else "audio/mp4"
            encryption_type = "NONE"
        else:
            raise ValueError(f"Unsupported manifest type: {manifest_mime_type}")

        return HiFiStreamResult(
            urls=urls,
            file_extension=HiFiApiClient._extension_from_mime(mime_type, codecs),
            codecs=codecs,
            mime_type=mime_type,
            audio_quality=str(data.get("audioQuality", "")),
            bit_depth=data.get("bitDepth"),
            sample_rate=data.get("sampleRate"),
            encryption_type=encryption_type,
        )

    def discover_instances(self) -> list[str]:
        with self._discovery_lock:
            now = time.monotonic()
            cached = self._discovery_cache
            if cached and now - cached[0] < self._discovery_ttl_sec:
                return list(cached[1])

            for tracker in HIFI_UPTIME_TRACKER_URLS:
                try:
                    response = requests.get(tracker, timeout=self.timeout)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        continue
                    urls = _tracker_instance_urls(payload.get("streaming"), payload.get("api"))
                    type(self)._discovery_cache = (now, urls)
                    return list(urls)
                except (requests.RequestException, ValueError):
                    continue

            type(self)._discovery_cache = (now, [])
            return []

    def refresh_instances(self) -> list[str]:
        discovered = self.discover_instances()
        if discovered:
            self.instances = discovered
        return self.instances

    def _mark_instance_dead(self, instance: str) -> None:
        self._dead_instances[instance] = time.time() + self.dead_ttl_sec

    def _is_instance_dead(self, instance: str) -> bool:
        until = self._dead_instances.get(instance)
        if until is None:
            return False
        if time.time() >= until:
            self._dead_instances.pop(instance, None)
            return False
        return True

    def _iter_live_instances(self) -> list[str]:
        live = [inst for inst in self.instances if not self._is_instance_dead(inst)]
        if live:
            return live
        self.refresh_instances()
        return [inst for inst in self.instances if not self._is_instance_dead(inst)]

    def _request_with_rotation(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._request_lock:
            return self._request_once_per_instance(path, params)

    def _request_once_per_instance(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        instances = self._iter_live_instances()
        if not instances:
            raise requests.RequestException("No live Hi-Fi API instances available.")

        last_error: Exception | None = None
        for instance in instances:
            try:
                response = requests.get(f"{instance}{path}", params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as exc:
                last_error = exc
                self._mark_instance_dead(instance)
                response = getattr(exc, "response", None)
                if response is not None and response.status_code in {401, 403, 429}:
                    break
        if last_error:
            raise requests.RequestException(str(last_error)) from last_error
        raise requests.RequestException("Hi-Fi API request failed")

    def health_check(self) -> str | None:
        live = self.live_instances()
        return live[0] if live else None

    def live_instances(self) -> list[str]:
        return self._iter_live_instances()

    def track_info(self, track_id: int) -> dict[str, Any]:
        return self._request_with_rotation("/info/", params={"id": track_id})

    def album(self, album_id: int, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._request_with_rotation("/album/", params={"id": album_id, "limit": limit, "offset": offset})

    def playlist(self, playlist_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._request_with_rotation("/playlist/", params={"id": playlist_id, "limit": limit, "offset": offset})

    def mix(self, mix_id: str) -> dict[str, Any]:
        return self._request_with_rotation("/mix/", params={"id": mix_id})

    def artist(self, artist_id: int, f: int | None = None, skip_tracks: bool = False) -> dict[str, Any]:
        params: dict[str, Any] = {"id": artist_id, "skip_tracks": skip_tracks}
        if f is not None:
            params["f"] = f
        return self._request_with_rotation("/artist/", params=params)

    def search(
        self,
        *,
        s: str | None = None,
        a: str | None = None,
        al: str | None = None,
        v: str | None = None,
        p: str | None = None,
    ) -> dict[str, Any]:
        params = {k: val for k, val in {"s": s, "a": a, "al": al, "v": v, "p": p}.items() if val}
        return self._request_with_rotation("/search/", params=params)

    def track_stream(self, track_id: int, quality: str) -> HiFiStreamResult:
        payload = self._request_with_rotation("/track/", params={"id": track_id, "quality": quality})
        return self.parse_track_payload(payload)
