"""Discord bot onboarding surface on the backend side
(onboarding-backend R2 + R3).

Two entry points:

* ``print_setup_hint`` — one-line non-blocking hint when state is
  needs-setup (R2). Called unconditionally on ``music-dl gui``; prints
  nothing when bot is already configured or when stdout is not a TTY.
* ``run_setup_force`` — launches the bot-side wizard as a child process
  with inherited stdio (R3). Called only when the user passes
  ``--setup-bot``. Blocks until the wizard exits; never aborts server
  startup on failure.

The previous interactive TTY prompt (prior-revision R2 + R3 + R4) was
removed: it hijacked ``music-dl gui`` with a terminal questionnaire and
alienated normal users. The only wizard-launch path from the backend is
now explicit via ``--setup-bot``.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, TextIO

from tidal_dl.gui.bot_onboarding import OnboardingState, detect_state

HINT_TEXT = (
    "Discord bot not configured — "
    "run `music-dl gui --setup-bot` to set it up.\n"
)


def print_setup_hint(
    is_tty_fn: Callable[[], bool] = lambda: sys.stdout.isatty(),
    detect_fn: Callable[[], OnboardingState] = detect_state,
    output: TextIO | None = None,
) -> None:
    """R2: one-line hint on startup when state is needs-setup. No-op on
    non-TTY startups or when state is configured."""
    if not is_tty_fn():
        return
    if detect_fn() is OnboardingState.CONFIGURED:
        return
    out: TextIO = output if output is not None else sys.stdout
    out.write(HINT_TEXT)
    out.flush()


def dispatch_wizard(out: TextIO | None = None) -> int:
    """R3 AC1+AC2: spawn the bot-side wizard as a child process with
    inherited stdio and block until it exits. Returns the wizard's exit
    code. Returns 127 when the runtime is unavailable. Never raises —
    the caller always continues startup regardless of result (R3 AC6).

    When ``out`` is provided the resolved ``bot_root`` is logged to it
    before dispatch so the user can see which directory the wizard was
    attempted from (aids diagnosing missing-script failures)."""
    import shutil
    import subprocess
    from pathlib import Path

    try:
        bot_root_env = os.environ.get("MUSIC_DL_BOT_PATH", "").strip()
        if bot_root_env:
            bot_root = Path(bot_root_env)
        else:
            # Repo-relative fallback:
            # …/TIDALDL-PY/tidal_dl/gui/ → …/apps/discord-bot
            here = Path(__file__).resolve()
            bot_root = here.parents[3] / "apps" / "discord-bot"

        try:
            if not bot_root.is_dir():
                return 127
        except OSError:
            # Unreadable parent directories, permission errors, etc.
            # Treat as "cannot locate wizard" — retry hint, not crash.
            return 127

        if out is not None:
            out.write(f"Launching Discord bot wizard from {bot_root}...\n")
            out.flush()

        bun = shutil.which("bun")
        if bun is not None:
            cmd = [bun, "run", "wizard"]
        else:
            node = shutil.which("node")
            if node is None:
                return 127
            # `node --import tsx` requires tsx to be resolvable from
            # bot_root's node_modules. On a bare Node install it is not.
            # Probe for it first; if missing, surface the runtime-missing
            # branch instead of a cryptic "Cannot find module 'tsx'".
            probe = subprocess.run(
                [node, "-e", "require.resolve('tsx')"],
                cwd=str(bot_root),
                check=False,
                capture_output=True,
            )
            if probe.returncode != 0:
                return 127
            cmd = [
                node,
                "--import",
                "tsx",
                str(bot_root / "src" / "wizard" / "cli.ts"),
            ]

        try:
            proc = subprocess.run(cmd, cwd=str(bot_root), check=False)
        except (OSError, subprocess.SubprocessError):
            return 127
        return proc.returncode
    except OSError:
        # Belt-and-suspenders: any filesystem hazard anywhere in the
        # dispatch pipeline becomes a retry hint, not a crash.
        return 127


def run_setup_force(
    dispatch_fn: "Callable[[], int] | None" = None,
    output: TextIO | None = None,
) -> int:
    """R3: `--setup-bot` path. Launches the wizard directly (no prompt,
    no state check — the user already said yes by passing the flag).
    Always returns 0 so server startup is never aborted (R3 AC6)."""
    out: TextIO = output if output is not None else sys.stdout
    # When the caller relies on the default dispatcher, hand it ``out``
    # so it can log the resolved ``bot_root`` before spawning the child.
    # Custom ``dispatch_fn`` callers (tests) keep the zero-arg contract.
    if dispatch_fn is None:
        rc = dispatch_wizard(out=out)
    else:
        rc = dispatch_fn()
    if rc == 0:
        out.write("\nBot setup complete.\n")
    elif rc == 127:
        out.write(
            "\nBot wizard runtime not available. Install bun (recommended) "
            "or ensure tsx is installed in apps/discord-bot "
            "(run `bun install` / `npm install`), then retry with "
            "`music-dl gui --setup-bot`.\n"
        )
    else:
        out.write(
            "\nBot setup did not complete. Retry later with "
            "`music-dl gui --setup-bot`.\n"
        )
    out.flush()
    return 0
