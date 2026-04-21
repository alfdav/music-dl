"""Backend configuration-state detection for the Discord bot onboarding
flow (onboarding-backend R1).

Two states only:

* ``configured``  — the shared-token file exists and is non-empty.
* ``needs-setup`` — otherwise.

The shared-token file is the same one the bot-side wizard
(onboarding-wizard R4) writes. We only check existence+non-empty — no
parsing or validation. Token format is the wizard's private contract.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from tidal_dl.helper.path import path_config_base

SHARED_TOKEN_FILENAME = "bot-shared-token"


class OnboardingState(str, Enum):
    CONFIGURED = "configured"
    NEEDS_SETUP = "needs-setup"


def shared_token_path() -> Path:
    """Canonical shared-token file path (same one the wizard writes)."""
    override = os.environ.get("MUSIC_DL_BOT_TOKEN_PATH", "").strip()
    if override:
        return Path(override)
    return Path(path_config_base()) / SHARED_TOKEN_FILENAME


def detect_state(token_path: Path | None = None) -> OnboardingState:
    """Resolve the current onboarding state (R1)."""
    token = token_path if token_path is not None else shared_token_path()
    if _file_non_empty(token):
        return OnboardingState.CONFIGURED
    return OnboardingState.NEEDS_SETUP


class TokenSource(str, Enum):
    """Where the backend will resolve the bot shared secret from."""
    ENV = "env"
    FILE = "file"
    NONE = "none"


def bot_token_source(
    env_getter: Optional[Callable[[str, str], str]] = None,
    path_resolver: Optional[Callable[[], Path]] = None,
) -> TokenSource:
    """Report where :func:`tidal_dl.gui.security.resolve_bot_shared_token`
    will actually pull the bot shared secret from, without disclosing the
    secret itself. Used as the startup canary that replaces the wizard's
    old R10 "backend reachable" HTTP probe.

    Priority mirrors ``resolve_bot_shared_token``: env var first, then
    the wizard-written file. The optional ``env_getter`` and
    ``path_resolver`` parameters let unit tests exercise every source
    branch via dependency injection — no ``os.environ`` or disk
    manipulation required.
    """
    get_env = env_getter or (lambda key, default: os.environ.get(key, default))
    if (get_env("MUSIC_DL_BOT_TOKEN", "") or "").strip():
        return TokenSource.ENV
    resolve_path = path_resolver or shared_token_path
    if _file_non_empty(resolve_path()):
        return TokenSource.FILE
    return TokenSource.NONE


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
