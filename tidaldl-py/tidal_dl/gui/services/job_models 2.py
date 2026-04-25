from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class JobKind(StrEnum):
    DOWNLOAD = "download"
    UPGRADE = "upgrade"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class DownloadJob:
    id: int
    kind: JobKind
    status: JobStatus
    track_id: int
    name: str
    artist: str
    album: str
    cover_url: str
    quality: str
    progress: float
    error: str | None
    old_path: str | None
    new_path: str | None
    metadata_json: str | None
    created_at: float
    started_at: float | None
    finished_at: float | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DownloadJob":
        return cls(
            id=int(row["id"]),
            kind=JobKind(row["kind"]),
            status=JobStatus(row["status"]),
            track_id=int(row["track_id"]),
            name=row.get("name") or f"Track {row['track_id']}",
            artist=row.get("artist") or "",
            album=row.get("album") or "",
            cover_url=row.get("cover_url") or "",
            quality=row.get("quality") or "",
            progress=float(row.get("progress") or 0),
            error=row.get("error"),
            old_path=row.get("old_path"),
            new_path=row.get("new_path"),
            metadata_json=row.get("metadata_json"),
            created_at=float(row["created_at"]),
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        )


@dataclass(frozen=True)
class UpgradeJobInput:
    track_id: int
    old_path: str
    quality: str | None = None
    metadata: dict[str, Any] | None = None
