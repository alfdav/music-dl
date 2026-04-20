"""R2 (non-blocking hint) + R3 (force-run wizard) acceptance tests."""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from tidal_dl.gui import bot_first_run as bot_first_run_module
from tidal_dl.gui.bot_first_run import (
    HINT_TEXT,
    dispatch_wizard,
    print_setup_hint,
    run_setup_force,
)
from tidal_dl.gui.bot_onboarding import OnboardingState


# --------------------------------------------------------------------------
# R2: print_setup_hint — one line, non-blocking, no prompts
# --------------------------------------------------------------------------


def test_r2_ac1_needs_setup_on_tty_prints_hint() -> None:
    out = io.StringIO()
    print_setup_hint(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        output=out,
    )
    assert out.getvalue() == HINT_TEXT
    # GAP-2: hint must contain the full runnable command, not just the
    # flag — truncating to "--setup-bot" alone would silently regress UX.
    assert "music-dl gui --setup-bot" in out.getvalue()


def test_r2_ac2_configured_prints_nothing() -> None:
    out = io.StringIO()
    print_setup_hint(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.CONFIGURED,
        output=out,
    )
    assert out.getvalue() == ""


def test_r2_ac4_no_prompt_no_blocking() -> None:
    # Function must complete synchronously without reading stdin.
    # If it did try to read, an empty StringIO stdin would simply EOF —
    # the test still proves absence of a prompt because the function
    # takes no stdin argument.
    out = io.StringIO()
    print_setup_hint(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        output=out,
    )
    # Exactly one line — not an interactive multi-line prompt.
    assert out.getvalue().count("\n") == 1


def test_r2_ac5_non_tty_suppresses_hint() -> None:
    out = io.StringIO()
    print_setup_hint(
        is_tty_fn=lambda: False,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        output=out,
    )
    assert out.getvalue() == ""


# --------------------------------------------------------------------------
# R3: run_setup_force — explicit opt-in wizard launch
# --------------------------------------------------------------------------


def test_r3_force_dispatches_wizard_unconditionally() -> None:
    out = io.StringIO()
    calls: list[str] = []

    def fake_dispatch() -> int:
        calls.append("wizard")
        return 0

    rc = run_setup_force(dispatch_fn=fake_dispatch, output=out)
    assert rc == 0
    assert calls == ["wizard"]
    assert "complete" in out.getvalue().lower()


def test_r3_ac6_wizard_failure_does_not_abort_server() -> None:
    out = io.StringIO()
    rc = run_setup_force(dispatch_fn=lambda: 42, output=out)
    assert rc == 0  # never propagates wizard failure
    assert "retry" in out.getvalue().lower()


def test_r3_runtime_missing_prints_install_hint() -> None:
    out = io.StringIO()
    rc = run_setup_force(dispatch_fn=lambda: 127, output=out)
    assert rc == 0
    assert "bun" in out.getvalue().lower() or "node" in out.getvalue().lower()


# --------------------------------------------------------------------------
# CODEX-P2: --setup-bot with no TTY must not dispatch (wizard child would
# block forever on piped/closed stdin, preventing server startup).
# --------------------------------------------------------------------------


def test_codex_p2_force_without_tty_skips_dispatch_and_prints_hint() -> None:
    out = io.StringIO()
    calls: list[str] = []

    def fake_dispatch() -> int:
        calls.append("wizard")
        return 0

    rc = run_setup_force(
        dispatch_fn=fake_dispatch,
        output=out,
        is_tty_fn=lambda: False,
    )
    assert rc == 0
    assert calls == [], (
        "Wizard must NOT be dispatched on non-TTY startup — it would "
        "block on prompts and never let the server start."
    )
    assert "interactive terminal" in out.getvalue().lower()


def test_codex_p2_force_with_tty_still_dispatches() -> None:
    out = io.StringIO()
    calls: list[str] = []

    def fake_dispatch() -> int:
        calls.append("wizard")
        return 0

    rc = run_setup_force(
        dispatch_fn=fake_dispatch,
        output=out,
        is_tty_fn=lambda: True,
    )
    assert rc == 0
    assert calls == ["wizard"]
    assert "complete" in out.getvalue().lower()


# --------------------------------------------------------------------------
# CODEX-P3: exit-code split — 126 = "bot sources missing" (MUSIC_DL_BOT_PATH
# hint), 127 = "runtime missing" (install bun / tsx hint). Conflating the
# two sent users down the wrong remediation path.
# --------------------------------------------------------------------------


def test_run_setup_force_126_prints_bot_root_hint_not_runtime_hint() -> None:
    out = io.StringIO()
    rc = run_setup_force(dispatch_fn=lambda: 126, output=out)
    assert rc == 0
    text = out.getvalue()
    assert "MUSIC_DL_BOT_PATH" in text
    assert "install bun" not in text.lower()


# --------------------------------------------------------------------------
# Regression: the deleted interactive path stays deleted
# --------------------------------------------------------------------------


def test_regression_no_exported_interactive_prompt() -> None:
    """The prior-revision interactive TTY prompt is deleted. These symbols
    should no longer exist on the module — guard against a reintroduction
    that would re-hijack `music-dl gui`."""
    from tidal_dl.gui import bot_first_run

    for name in (
        "ask_user",
        "classify_answer",
        "decide_startup_action",
        "should_prompt",
        "write_dismissal_flag",
        "run_first_run_flow",
        "PromptAnswer",
        "PromptDecision",
    ):
        assert not hasattr(bot_first_run, name), (
            f"{name} was removed in the 2026-04-20 kit revision; normal "
            "`music-dl gui` must not hijack the terminal. Do not re-add "
            "without revising cavekit-onboarding-backend.md first."
        )


# --------------------------------------------------------------------------
# OnboardingState simplified to two values
# --------------------------------------------------------------------------


def test_onboarding_state_has_two_values_only() -> None:
    # Dismissed state was removed — there is no prompt to dismiss anymore.
    values = {s.value for s in OnboardingState}
    assert values == {"configured", "needs-setup"}


@pytest.mark.parametrize(
    "state,expected_hint",
    [
        (OnboardingState.CONFIGURED, False),
        (OnboardingState.NEEDS_SETUP, True),
    ],
)
def test_hint_visibility_matrix(
    state: OnboardingState, expected_hint: bool
) -> None:
    out = io.StringIO()
    print_setup_hint(
        is_tty_fn=lambda: True, detect_fn=lambda: state, output=out
    )
    assert bool(out.getvalue()) is expected_hint


# --------------------------------------------------------------------------
# GAP-3: R3 AC5 — force triggers regardless of current state
# --------------------------------------------------------------------------


def test_r3_ac5_force_does_not_consult_detect_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_setup_force must not branch on the current onboarding state.
    The user already said yes by passing --setup-bot. Monkeypatch
    detect_state to blow up if anyone calls it; run_setup_force should
    still dispatch cleanly."""

    def explode(*_args: object, **_kwargs: object) -> OnboardingState:
        raise AssertionError(
            "run_setup_force must not consult detect_state (R3 AC5)"
        )

    # Patch on bot_onboarding (source of truth) and bot_first_run (re-
    # exported symbol) so a future refactor can't route around the guard.
    from tidal_dl.gui import bot_onboarding

    monkeypatch.setattr(bot_onboarding, "detect_state", explode)
    monkeypatch.setattr(bot_first_run_module, "detect_state", explode)

    out = io.StringIO()
    calls: list[str] = []

    def fake_dispatch() -> int:
        calls.append("wizard")
        return 0

    rc = run_setup_force(dispatch_fn=fake_dispatch, output=out)
    assert rc == 0
    assert calls == ["wizard"]


# --------------------------------------------------------------------------
# RISK-3: real subprocess.run dispatch path — regression guard on
# stdio inheritance and on bot_root resolution via MUSIC_DL_BOT_PATH.
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    shutil.which("bun") is None,
    reason="bun not available — real-dispatch smoke test requires bun",
)
def test_dispatch_wizard_real_subprocess_with_fake_bot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stand up a throwaway ``bot_root`` with a no-op ``wizard`` script
    and invoke the REAL dispatch_wizard. Proves the subprocess.run wiring
    actually runs the script (stdio inheritance + cwd + bun resolution)
    instead of just trusting the mocks."""
    bot_root = tmp_path / "fake-bot"
    bot_root.mkdir()

    # Minimal package.json with a wizard script that exits 0.
    pkg = {
        "name": "fake-bot",
        "private": True,
        "scripts": {"wizard": 'printf "stdio-proof\\n"'},
    }
    (bot_root / "package.json").write_text(json.dumps(pkg), encoding="utf-8")

    monkeypatch.setenv("MUSIC_DL_BOT_PATH", str(bot_root))

    rc = dispatch_wizard()
    assert rc == 0, "wizard script should exit 0 under real subprocess.run"


def test_dispatch_wizard_returns_126_when_bot_root_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CODEX-P3: a non-existent bot_root resolves to 126 (bot sources
    missing), not 127 (runtime missing) — the user should be pointed at
    MUSIC_DL_BOT_PATH, not told to install bun."""
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("MUSIC_DL_BOT_PATH", str(missing))
    assert dispatch_wizard() == 126


def test_dispatch_wizard_returns_126_on_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CODEX-P3: PermissionError from ``bot_root.is_dir()`` is still a
    bot-sources-unreachable condition (not a runtime problem), so it
    must return 126 and route the user to the MUSIC_DL_BOT_PATH hint."""
    inaccessible_parent = tmp_path / "locked"
    inaccessible_parent.mkdir()
    bot_root = inaccessible_parent / "discord-bot"
    bot_root.mkdir()

    original_mode = stat.S_IMODE(inaccessible_parent.stat().st_mode)
    # Strip execute bit so traversal into ``bot_root`` raises
    # PermissionError on is_dir().
    os.chmod(inaccessible_parent, 0)
    try:
        # Running as root defeats chmod — skip if the guard is bypassed.
        if os.geteuid() == 0:
            pytest.skip("root bypasses chmod; cannot exercise PermissionError")
        monkeypatch.setenv("MUSIC_DL_BOT_PATH", str(bot_root))
        rc = dispatch_wizard()
        assert rc == 126
    finally:
        os.chmod(inaccessible_parent, original_mode)
