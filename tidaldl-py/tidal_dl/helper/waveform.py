"""Offline waveform peak extraction — no runtime audio processing.

Decodes audio to raw mono PCM via ffmpeg, computes normalised peak
amplitudes at two resolutions:

- **display** (~100 bars): static waveform shape for the progress bar.
- **hires** (~10 peaks/sec): drives per-frame animation during playback,
  giving bars a DAW-style reactive pulse without touching the audio path.

The <audio> element is never wrapped in an AudioContext.  All analysis
happens at scan/download time from the file bytes.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

NUM_BARS: int = 100
HIRES_RATE: int = 10  # peaks per second — enough for smooth animation


def _find_ffmpeg() -> str | None:
    """Locate ffmpeg, checking PATH and common install locations."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if Path(candidate).is_file():
            return candidate
    return None


def _decode_to_pcm(path: Path) -> tuple[int, ...] | None:
    """Decode *path* to mono 16-bit PCM at 8 kHz via ffmpeg."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None
    if not path.is_file():
        return None
    try:
        proc = subprocess.run(
            [
                ffmpeg, "-v", "quiet",
                "-i", str(path),
                "-ac", "1",
                "-ar", "8000",
                "-f", "s16le",
                "-",
            ],
            capture_output=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    raw = proc.stdout
    if not raw:
        return None
    n = len(raw) // 2
    if n < NUM_BARS:
        return None
    return struct.unpack(f"<{n}h", raw[: n * 2])


def _bin_peaks(samples: tuple[int, ...], num_bins: int) -> list[float]:
    """Split *samples* into *num_bins* equal chunks and return normalised peaks."""
    n = len(samples)
    bin_size = max(1, n // num_bins)
    peaks: list[int] = []
    for i in range(num_bins):
        start = i * bin_size
        end = min(start + bin_size, n)
        if start >= n:
            break
        peaks.append(max(abs(s) for s in samples[start:end]))
    mx = max(peaks) if peaks else 1
    if mx == 0:
        mx = 1
    return [round(p / mx, 3) for p in peaks]


def extract_peaks(path: Path, num_bars: int = NUM_BARS) -> list[float] | None:
    """Return *num_bars* normalised peak amplitudes (display resolution)."""
    samples = _decode_to_pcm(path)
    if samples is None:
        return None
    return _bin_peaks(samples, num_bars)


def extract_hires(path: Path) -> list[float] | None:
    """Return high-resolution peaks (~10/sec) for playback animation."""
    samples = _decode_to_pcm(path)
    if samples is None:
        return None
    duration_sec = len(samples) / 8000  # decoded at 8 kHz
    num_bins = max(NUM_BARS, int(duration_sec * HIRES_RATE))
    return _bin_peaks(samples, num_bins)


def extract_both(path: Path) -> tuple[list[float], list[float]] | None:
    """Return (display_peaks, hires_peaks) in a single ffmpeg decode pass."""
    samples = _decode_to_pcm(path)
    if samples is None:
        return None
    display = _bin_peaks(samples, NUM_BARS)
    duration_sec = len(samples) / 8000
    num_hires = max(NUM_BARS, int(duration_sec * HIRES_RATE))
    hires = _bin_peaks(samples, num_hires)
    return display, hires


def peaks_to_json(peaks: list[float]) -> str:
    """Compact JSON serialisation — no spaces, minimal size."""
    return json.dumps(peaks, separators=(",", ":"))


def peaks_from_json(data: str) -> list[float] | None:
    """Deserialise peaks from a JSON string, or None on failure."""
    try:
        parsed = json.loads(data)
        if isinstance(parsed, list) and all(isinstance(v, (int, float)) for v in parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None
