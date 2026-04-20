"""Backend first-run detection for the Discord bot onboarding flow
(onboarding-backend R1).

This module resolves three states at startup:

* ``configured``  — the shared-token file exists and is non-empty.
* ``dismissed``   — the user-set dismissal flag exists.
* ``needs-setup`` — neither of the above holds.

The shared-token file is the same one the bot-side wizard
(onboarding-wizard R4) writes. We only check existence+non-empty — no
parsing or validation. Token format is the wizard's private contract.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from tidal_dl.helper.path import path_config_base

SHARED_TOKEN_FILENAME = "bot-shared-token"
DISMISSAL_FLAG_FILENAME = "discord-bot-dismissed"


class OnboardingState(str, Enum):
    CONFIGURED = "configured"
    DISMISSED = "dismissed"
    NEEDS_SETUP = "needs-setup"


def shared_token_path() -> Path:
    """Canonical shared-token file path (same one the wizard writes)."""
    override = os.environ.get("MUSIC_DL_BOT_TOKEN_PATH", "").strip()
    if override:
        return Path(override)
    return Path(path_config_base()) / SHARED_TOKEN_FILENAME


def dismissal_flag_path() -> Path:
    """Canonical dismissal-flag file path."""
    override = os.environ.get("MUSIC_DL_BOT_DISMISSAL_PATH", "").strip()
    if override:
        return Path(override)
    return Path(path_config_base()) / DISMISSAL_FLAG_FILENAME


def detect_state(
    token_path: Path | None = None,
    dismissal_path: Path | None = None,
) -> OnboardingState:
    """Resolve the current onboarding state at startup (R1).

    Precedence: configured > dismissed > needs-setup. A configured install
    that also has a stale dismissal flag is still considered configured —
    the prompt is only for un-set-up users.
    """
    token = token_path if token_path is not None else shared_token_path()
    flag = dismissal_path if dismissal_path is not None else dismissal_flag_path()

    if _file_non_empty(token):
        return OnboardingState.CONFIGURED
    if flag.exists():
        return OnboardingState.DISMISSED
    return OnboardingState.NEEDS_SETUP


def _file_non_empty(path: Path) -> bool:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    if not stat.st_size:
        return False
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return len(content) > 0
