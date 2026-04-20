"""TTY-aware first-run prompt for the Discord bot integration
(onboarding-backend R2 + R3).

R2: when state is needs-setup AND stdout is attached to an interactive
terminal, the backend prompts the user before the HTTP server begins
accepting requests. Daemonized / piped / GUI-launched startups skip the
prompt entirely.

R3: the prompt accepts yes (default), no, or never. Anything else
re-prompts up to 3 times before treating the answer as "n".
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from typing import Callable, TextIO

from tidal_dl.gui.bot_onboarding import OnboardingState, detect_state


class PromptAnswer(str, Enum):
    YES = "yes"
    NO = "no"
    NEVER = "never"


@dataclass
class PromptDecision:
    """Result of the first-run prompt — what the startup code should do."""

    run_wizard: bool
    write_dismissal: bool


SKIP: PromptDecision = PromptDecision(run_wizard=False, write_dismissal=False)
DISMISS: PromptDecision = PromptDecision(run_wizard=False, write_dismissal=True)
WIZARD: PromptDecision = PromptDecision(run_wizard=True, write_dismissal=False)

PROMPT_TEXT = (
    "\nDiscord music bot is not yet configured.\n"
    "Run the setup wizard now? [Y]es / [n]o / [never]: "
)


def should_prompt(state: OnboardingState, is_tty: bool) -> bool:
    """R2: decide whether to prompt at startup.

    Only the combination of needs-setup + interactive terminal triggers
    the prompt. Configured, dismissed, or any non-TTY startup (daemon,
    piped, GUI launcher) skips it.
    """
    return state is OnboardingState.NEEDS_SETUP and is_tty


def classify_answer(raw: str) -> PromptAnswer | None:
    """R3: map user input to yes/no/never. None for unrecognized input."""
    v = raw.strip().lower()
    if v == "" or v in {"y", "yes"}:
        return PromptAnswer.YES
    if v in {"n", "no"}:
        return PromptAnswer.NO
    if v == "never":
        return PromptAnswer.NEVER
    return None


def ask_user(
    stdin: TextIO | None = None,
    stderr: TextIO | None = None,
    stdout: TextIO | None = None,
    prompt_text: str = PROMPT_TEXT,
    max_retries: int = 3,
) -> PromptAnswer:
    """Run the R3 prompt loop. Re-prompts up to max_retries on unrecognized
    input, then falls back to NO. Injection parameters default to the
    real stdio streams so production use stays simple.
    """
    _in: TextIO = stdin if stdin is not None else sys.stdin
    _err: TextIO = stderr if stderr is not None else sys.stderr
    _out: TextIO = stdout if stdout is not None else sys.stdout

    for attempt in range(max_retries + 1):
        _out.write(prompt_text)
        _out.flush()
        raw = _in.readline()
        if raw == "":
            # EOF — treat as no (safe: no dismissal flag is written).
            return PromptAnswer.NO
        classified = classify_answer(raw.rstrip("\n\r"))
        if classified is not None:
            return classified
        if attempt < max_retries:
            _err.write("Please answer Y (yes, default), n (no), or never.\n")
            _err.flush()
    return PromptAnswer.NO


def decide_startup_action(
    is_tty_fn: Callable[[], bool] = lambda: sys.stdout.isatty(),
    detect_fn: Callable[[], OnboardingState] = detect_state,
    ask_fn: Callable[[], PromptAnswer] = ask_user,
) -> PromptDecision:
    """Top-level R2 + R3 flow. Called from server startup before the
    HTTP server begins accepting requests."""
    state = detect_fn()
    if not should_prompt(state, is_tty_fn()):
        return SKIP

    answer = ask_fn()
    if answer is PromptAnswer.YES:
        return WIZARD
    if answer is PromptAnswer.NEVER:
        return DISMISS
    return SKIP
