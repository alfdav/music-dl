"""R2 (non-blocking hint) + R3 (force-run wizard) acceptance tests."""

from __future__ import annotations

import io

import pytest

from tidal_dl.gui.bot_first_run import (
    HINT_TEXT,
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
    assert "--setup-bot" in HINT_TEXT


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
