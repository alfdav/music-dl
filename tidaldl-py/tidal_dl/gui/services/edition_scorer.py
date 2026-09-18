"""Sidecar subprocess wrapper for typesafe-music-edition."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

_DEFAULT_BIN = "typesafe-music-edition"
_WELL_KNOWN = (
    "/home/box/bin/typesafe-music-edition",
    os.path.expanduser("~/bin/typesafe-music-edition"),
)


class EditionScorerError(Exception):
    """Scorer ran but failed (timeout, parse, nonzero exit)."""


class EditionScorerUnavailable(EditionScorerError):
    """Binary missing; chips should show n/a."""


def _settings_bin() -> str | None:
    try:
        from tidal_dl.config import Settings

        path = getattr(Settings().data, "edition_scorer_path", "") or ""
        path = str(path).strip()
        return path or None
    except Exception:
        return None


def _resolve_binary() -> str | None:
    configured = _settings_bin()
    if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
        return configured
    found = shutil.which(_DEFAULT_BIN)
    if found:
        return found
    for candidate in _WELL_KNOWN:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def scorer_available() -> bool:
    return _resolve_binary() is not None


def scorer_status() -> str:
    """Binary probe only: ready / missing / n/a. Never mentions the API key."""
    try:
        return "ready" if _resolve_binary() else "missing"
    except Exception:
        return "n/a"


def score_pair(item_a: dict, item_b: dict, *, timeout_s: float = 60) -> dict[str, Any]:
    """Run the sidecar CLI and return a parsed edition-advice payload."""
    binary = _resolve_binary()
    if not binary:
        raise EditionScorerUnavailable("typesafe-music-edition not found")

    cmd = [
        binary,
        "--a",
        json.dumps(item_a, ensure_ascii=False),
        "--b",
        json.dumps(item_b, ensure_ascii=False),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=os.environ,
        )
    except subprocess.TimeoutExpired as exc:
        raise EditionScorerError("scorer timed out") from exc
    except OSError as exc:
        raise EditionScorerError("scorer failed to start") from exc

    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "scorer failed").strip()
        # Never log env; stderr from the CLI must not include the API key.
        raise EditionScorerError(err[:500] or "scorer failed")

    try:
        payload = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise EditionScorerError("scorer returned invalid JSON") from exc
    if not isinstance(payload, dict) or "relation" not in payload:
        raise EditionScorerError("scorer JSON missing relation")
    return {
        "relation": payload.get("relation"),
        "confidence": payload.get("confidence"),
        "probabilities": payload.get("probabilities"),
        "same_isrc_misleading": payload.get("same_isrc_misleading"),
        "clarity": payload.get("clarity"),
        "model": payload.get("model"),
        "usage": payload.get("usage"),
    }
