from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

_CHECKPOINT_ID = re.compile(r"[^A-Za-z0-9._-]+")


def resolved_output_dir(output_dir: str) -> str:
    return str(Path(output_dir).expanduser().resolve())


def checkpoint_path_for(config_root: str | Path, collection_id: str, output_dir: str) -> Path:
    """Checkpoint file for one collection written into one output directory."""
    digest = hashlib.sha256(resolved_output_dir(output_dir).encode("utf-8")).hexdigest()[:16]
    safe = _CHECKPOINT_ID.sub("_", collection_id).strip("._") or "collection"
    return Path(config_root) / "checkpoints" / f"{safe}_{digest}.json"


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
    output_dir: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @classmethod
    def load(cls, path: Path) -> DownloadCheckpoint:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path=path,
            collection_id=str(payload.get("collection_id", "")),
            collection_type=str(payload.get("collection_type", "")),
            tracks={str(k): str(v) for k, v in (payload.get("tracks", {}) or {}).items()},
            output_dir=str(payload.get("output_dir", "") or ""),
            started_at=str(payload.get("started_at", datetime.now(UTC).isoformat())),
            updated_at=str(payload.get("updated_at", datetime.now(UTC).isoformat())),
        )

    def same_output_dir(self, output_dir: str) -> bool:
        if not self.output_dir:
            return False
        return resolved_output_dir(self.output_dir) == resolved_output_dir(output_dir)

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
                "output_dir": self.output_dir,
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
