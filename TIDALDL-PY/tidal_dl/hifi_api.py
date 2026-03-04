from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import requests

from tidal_dl.constants import HIFI_API_FALLBACK_INSTANCES, HIFI_UPTIME_TRACKER_URLS, REQUESTS_TIMEOUT_SEC
from tidal_dl.dash import parse_manifest


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
    def _extension_from_mime(mime_type: str) -> str:
        mime = (mime_type or "").lower()
        if "flac" in mime:
            return ".flac"
        if "mp4" in mime or "aac" in mime:
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
            file_extension=HiFiApiClient._extension_from_mime(mime_type),
            codecs=codecs,
            mime_type=mime_type,
            audio_quality=str(data.get("audioQuality", "")),
            bit_depth=data.get("bitDepth"),
            sample_rate=data.get("sampleRate"),
            encryption_type=encryption_type,
        )

    def discover_instances(self) -> list[str]:
        for tracker in HIFI_UPTIME_TRACKER_URLS:
            try:
                response = requests.get(tracker, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                streaming = payload.get("streaming", [])
                urls = [str(item.get("url", "")).strip().rstrip("/") for item in streaming if item.get("url")]
                if urls:
                    return urls
            except requests.RequestException:
                continue
        return list(HIFI_API_FALLBACK_INSTANCES)

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
        instances = self._iter_live_instances()
        if not instances:
            raise requests.RequestException("No live Hi-Fi API instances available.")

        last_error: Exception | None = None
        for instance in instances:
            for attempt in range(3):
                try:
                    response = requests.get(f"{instance}{path}", params=params, timeout=self.timeout)
                    response.raise_for_status()
                    return response.json()
                except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(2**attempt)
                        continue
                    self._mark_instance_dead(instance)
                    break
        if last_error:
            raise requests.RequestException(str(last_error)) from last_error
        raise requests.RequestException("Hi-Fi API request failed")

    def health_check(self) -> str | None:
        for instance in self._iter_live_instances():
            try:
                response = requests.get(instance + "/", timeout=self.timeout)
                response.raise_for_status()
                return instance
            except requests.RequestException:
                self._mark_instance_dead(instance)
                continue
        return None

    def track_info(self, track_id: int) -> dict[str, Any]:
        return self._request_with_rotation("/info/", params={"id": track_id})

    def track_stream(self, track_id: int, quality: str) -> HiFiStreamResult:
        payload = self._request_with_rotation("/track/", params={"id": track_id, "quality": quality})
        return self.parse_track_payload(payload)
