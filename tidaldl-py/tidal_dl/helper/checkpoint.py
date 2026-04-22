from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock


STATUS_PENDING = "pending"
STATUS_DOWNLOADED = "downloaded"
STATUS_FAILED = "failed"
VALID_STATUS = {STATUS_PENDING, STATUS_DOWNLOADED, STATUS_FAILED}


@dataclass
class DownloadCheckpoint:
    path: Path
    collection_id: str
    collection_type: str
    tracks: dict[str, str] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @classmethod
    def load(cls, path: Path) -> "DownloadCheckpoint":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path=path,
            collection_id=str(payload.get("collection_id", "")),
            collection_type=str(payload.get("collection_type", "")),
            tracks={str(k): str(v) for k, v in (payload.get("tracks", {}) or {}).items()},
            started_at=str(payload.get("started_at", datetime.now(UTC).isoformat())),
            updated_at=str(payload.get("updated_at", datetime.now(UTC).isoformat())),
        )

    def initialize_tracks(self, track_ids: list[str]) -> None:
        with self._lock:
            for track_id in track_ids:
                self.tracks.setdefault(str(track_id), STATUS_PENDING)
            self.updated_at = datetime.now(UTC).isoformat()

    def mark(self, track_id: str, status: str) -> None:
        if status not in VALID_STATUS:
            raise ValueError(f"Invalid checkpoint status: {status}")
        with self._lock:
            self.tracks[str(track_id)] = status
            self.updated_at = datetime.now(UTC).isoformat()

    def status_of(self, track_id: str) -> str | None:
        with self._lock:
            return self.tracks.get(str(track_id))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {
                "collection_id": self.collection_id,
                "collection_type": self.collection_type,
                "tracks": self.tracks,
                "started_at": self.started_at,
                "updated_at": self.updated_at,
            }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def is_complete_success(self) -> bool:
        with self._lock:
            if not self.tracks:
                return False
            return all(status == STATUS_DOWNLOADED for status in self.tracks.values())

    def cleanup_if_complete(self) -> None:
        if self.is_complete_success():
            self.path.unlink(missing_ok=True)
