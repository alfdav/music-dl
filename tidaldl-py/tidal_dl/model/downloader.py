from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from enum import StrEnum

from requests import HTTPError
from tidalapi.media import Stream, StreamManifest


class DownloadOutcome(StrEnum):
    """Result of a single item download."""

    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"
    FAILED = "failed"
    COPIED = "copied"
    UNAVAILABLE = "unavailable"


@dataclass
class DownloadSummary:
    """Aggregate outcome counters for a collection download."""

    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    copied: int = 0
    unavailable: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    unavailable_items: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.downloaded + self.skipped + self.failed + self.copied + self.unavailable

    def record(self, outcome: DownloadOutcome, *, label: str = "", reason: str = "") -> None:
        if outcome == DownloadOutcome.DOWNLOADED:
            self.downloaded += 1
        elif outcome == DownloadOutcome.SKIPPED:
            self.skipped += 1
        elif outcome == DownloadOutcome.COPIED:
            self.copied += 1
        elif outcome == DownloadOutcome.UNAVAILABLE:
            self.unavailable += 1
            if label or reason:
                self.unavailable_items.append((label, reason))
        else:
            self.failed += 1
            if label or reason:
                self.failures.append((label, reason))


@dataclass
class DownloadSegmentResult:
    result: bool
    url: str
    path_segment: pathlib.Path
    id_segment: int
    error: HTTPError | None = None


@dataclass
class TrackStreamInfo:
    """Container for track stream information."""

    stream_manifest: StreamManifest | HiFiStreamManifest | None
    file_extension: str
    requires_flac_extraction: bool
    media_stream: Stream | None


@dataclass
class HiFiStreamManifest:
    urls: list[str]
    file_extension: str
    codecs: str
    is_encrypted: bool = False
    encryption_key: str | None = None
    audio_quality: str | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None
    asset_presentation: str = ""

    def get_urls(self) -> list[str]:
        return self.urls
