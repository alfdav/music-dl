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

import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Callable, TextIO

from tidal_dl.gui.bot_onboarding import (
    OnboardingState,
    detect_state,
    dismissal_flag_path,
)


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


def write_dismissal_flag() -> None:
    """Write the canonical dismissal flag file (onboarding-backend R3 AC3).

    The flag file is intentionally empty — its presence is the signal.
    Parent directories are created if missing. Idempotent: a repeat call
    succeeds even when the flag already exists.
    """
    path = dismissal_flag_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open in create-or-truncate mode so a repeat invocation is idempotent.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("")


def dispatch_wizard(
    spawn_fn: "Callable[[], int] | None" = None,
) -> int:
    """Dispatch the bot-side wizard as a child process with inherited
    stdio (onboarding-backend R4 AC1 + AC2). Returns the wizard's exit
    code. Never raises — a failure to spawn the wizard maps to a
    non-zero return so the caller prints a retry hint and proceeds.
    """
    if spawn_fn is not None:
        return spawn_fn()

    import subprocess
    from pathlib import Path

    # Resolve the wizard entry point. The bot lives at apps/discord-bot
    # relative to the repository root. In a packaged install this
    # environment variable points at the bot's repository root so the
    # backend can find the wizard without hard-coding a developer layout.
    bot_root_env = os.environ.get("MUSIC_DL_BOT_PATH", "").strip()
    if bot_root_env:
        bot_root = Path(bot_root_env)
    else:
        # Repo-relative fallback: …/TIDALDL-PY/tidal_dl/gui/ → …/apps/discord-bot
        here = Path(__file__).resolve()
        bot_root = here.parents[3] / "apps" / "discord-bot"

    if not bot_root.is_dir():
        return 127  # "command not found" — caller prints retry hint

    # Prefer `bun` (what the wizard shebang targets). Fall back to
    # node-with-tsx if bun is unavailable.
    import shutil

    bun = shutil.which("bun")
    if bun is not None:
        cmd = [bun, "run", "wizard"]
    else:
        node = shutil.which("node")
        if node is None:
            return 127
        cmd = [node, "--import", "tsx", str(bot_root / "src" / "wizard" / "cli.ts")]

    try:
        proc = subprocess.run(cmd, cwd=str(bot_root), check=False)
    except (OSError, subprocess.SubprocessError):
        return 127
    return proc.returncode


def run_first_run_flow(
    is_tty_fn: Callable[[], bool] = lambda: sys.stdout.isatty(),
    detect_fn: Callable[[], OnboardingState] = detect_state,
    ask_fn: Callable[[], PromptAnswer] = ask_user,
    dispatch_fn: "Callable[[], int] | None" = None,
    output: TextIO | None = None,
    *,
    force: bool = False,
) -> int:
    """Top-level R2+R3+R4 flow for server startup. Safe to call even on
    non-interactive or already-configured installs — returns 0 quickly
    in both cases. Returns 0 if the flow completed without fatal error,
    non-zero only if something the caller genuinely needs to know about
    happened (today: never — R4 AC5 says startup is never aborted on
    wizard failure, so we always return 0).

    The force flag (R5 AC1) triggers the prompt regardless of detected
    state and ignores the dismissal flag for that invocation (R5 AC2)
    without modifying it (R5 AC3).
    """
    out = output if output is not None else sys.stdout

    if force:
        # R5: force bypasses state detection entirely. The prompt still
        # offers yes/no/never, but since we're ignoring the dismissal
        # flag this run, a NEVER answer from a force invocation should
        # still write the flag (matches user intent).
        if not is_tty_fn():
            out.write(
                "--force requires an interactive terminal. Skipping.\n"
            )
            return 0
        answer = ask_fn()
        if answer is PromptAnswer.YES:
            decision: PromptDecision = WIZARD
        elif answer is PromptAnswer.NEVER:
            decision = DISMISS
        else:
            decision = SKIP
    else:
        decision = decide_startup_action(
            is_tty_fn=is_tty_fn,
            detect_fn=detect_fn,
            ask_fn=ask_fn,
        )

    if decision.write_dismissal:
        try:
            write_dismissal_flag()
        except OSError as exc:
            out.write(f"Could not write dismissal flag: {exc}\n")

    if not decision.run_wizard:
        return 0

    # R4: child process, inherited stdio, block until exit.
    dispatch = dispatch_fn if dispatch_fn is not None else dispatch_wizard
    rc = dispatch()
    if rc == 0:
        out.write("\nBot setup complete.\n")
    else:
        out.write(
            "\nBot setup did not complete. Re-run later with:\n"
            "  music-dl gui --setup-bot\n"
        )
    # R4 AC5: backend startup is NEVER aborted by wizard failure.
    return 0
