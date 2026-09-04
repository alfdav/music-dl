"""Deterministic performance probe for common LibraryDB queries."""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tidal_dl.helper.library_db import LibraryDB

# Search LIKE folds accents in a deterministic UDF (~40ms p95 on the 10k probe).
ABSOLUTE_MS = {"pagination": 20.0, "search": 100.0, "artists": 20.0}


@dataclass(frozen=True)
class ProbeResult:
    status: str
    relative_status: str
    measurements: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "relative_status": self.relative_status,
            "p95_ms": {
                name: round(value, 3) for name, value in self.measurements.items()
            },
            "ceilings_ms": ABSOLUTE_MS,
        }


def percentile_95(samples_ms: Sequence[float]) -> float:
    """Return the nearest-rank 95th percentile."""
    if not samples_ms:
        raise ValueError("samples must not be empty")
    ordered = sorted(samples_ms)
    return float(ordered[math.ceil(0.95 * len(ordered)) - 1])


def measure(operation: Callable[[], object], iterations: int = 25) -> float:
    """Warm the query once, then measure its p95 over *iterations* calls."""
    if iterations < 1:
        raise ValueError("iterations must be positive")
    operation()
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1_000)
    return percentile_95(samples)


def build_fixture(path: Path, tracks: int = 10_000) -> LibraryDB:
    """Build and return an open LibraryDB containing deterministic track data."""
    db = LibraryDB(path)
    try:
        db.open()
        for index in range(tracks):
            db.record(
                f"fixture://track/{index:05d}.flac",
                status="tagged",
                artist=f"Artist {index % 500:03d}",
                title=f"Track {index}",
                album=f"Album {index % 1_000:04d}",
                duration=180 + index % 240,
                quality="LOSSLESS",
                fmt="FLAC",
            )
        db.commit()
    except BaseException:
        db.close()
        raise
    return db


def classify(
    measurements: dict[str, float], baseline: dict[str, float] | None
) -> ProbeResult:
    """Classify absolute failures and material relative regressions."""
    absolute_failure = any(
        measurements[name] > ceiling for name, ceiling in ABSOLUTE_MS.items()
    )
    if baseline is None:
        relative_status = "calibrating"
    else:
        regressed = any(
            measurements[name] > baseline[name] * 1.25
            and measurements[name] - baseline[name] > 2.0
            for name in ABSOLUTE_MS
        )
        relative_status = "regression" if regressed else "pass"

    if absolute_failure:
        status = "fail"
    elif relative_status == "regression":
        status = "regression"
    else:
        status = "pass"
    return ProbeResult(status, relative_status, measurements)


def run_probe() -> dict[str, float]:
    """Measure p95 latency for the three PR-gate LibraryDB operations."""
    with tempfile.TemporaryDirectory(prefix="music-dl-qa-") as directory:
        db = build_fixture(Path(directory) / "library.db")
        try:
            return {
                "pagination": measure(lambda: db.tracks_page(limit=50, offset=5000)),
                "search": measure(
                    lambda: db.tracks_page(query="Track 9999", limit=50, offset=0)
                ),
                "artists": measure(lambda: db.artists_page(limit=50, offset=0)),
            }
        finally:
            db.close()


def _load_baseline(path: Path) -> dict[str, float]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError from exc
    if not isinstance(payload, dict) or set(payload) != set(ABSOLUTE_MS):
        raise ValueError
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        for value in payload.values()
    ):
        raise ValueError
    return {name: float(payload[name]) for name in ABSOLUTE_MS}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("output/qa/performance.json")
    )
    args = parser.parse_args(argv)

    try:
        baseline = _load_baseline(args.baseline) if args.baseline else None
    except ValueError:
        print("error: invalid performance baseline", file=sys.stderr)
        return 2

    result = classify(run_probe(), baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 1 if result.status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
