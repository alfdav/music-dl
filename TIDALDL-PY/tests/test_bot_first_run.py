"""R2 + R3 acceptance tests — TTY prompt + Y/n/never handling."""

from __future__ import annotations

import io

import pytest

from tidal_dl.gui.bot_first_run import (
    DISMISS,
    SKIP,
    WIZARD,
    PromptAnswer,
    ask_user,
    classify_answer,
    decide_startup_action,
    should_prompt,
)
from tidal_dl.gui.bot_onboarding import OnboardingState


def test_r2_ac1_tty_plus_needs_setup_shows_prompt() -> None:
    assert should_prompt(OnboardingState.NEEDS_SETUP, is_tty=True) is True


def test_r2_ac2_no_tty_skips() -> None:
    assert should_prompt(OnboardingState.NEEDS_SETUP, is_tty=False) is False


def test_r2_ac3_configured_skips_prompt() -> None:
    assert should_prompt(OnboardingState.CONFIGURED, is_tty=True) is False


def test_r2_ac3_dismissed_skips_prompt() -> None:
    assert should_prompt(OnboardingState.DISMISSED, is_tty=True) is False


# ------- classify_answer -------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", PromptAnswer.YES),
        ("y", PromptAnswer.YES),
        ("Y", PromptAnswer.YES),
        ("yes", PromptAnswer.YES),
        ("YES", PromptAnswer.YES),
        ("n", PromptAnswer.NO),
        ("NO", PromptAnswer.NO),
        ("never", PromptAnswer.NEVER),
        ("NEVER", PromptAnswer.NEVER),
        ("  y  ", PromptAnswer.YES),
    ],
)
def test_r3_classify_known(raw: str, expected: PromptAnswer) -> None:
    assert classify_answer(raw) is expected


@pytest.mark.parametrize("raw", ["maybe", "1", "nope", "?"])
def test_r3_classify_unknown(raw: str) -> None:
    assert classify_answer(raw) is None


# ------- ask_user retry path -------


def _ask_with(lines: list[str]):
    stdin = io.StringIO("\n".join(lines) + ("\n" if lines else ""))
    stdout = io.StringIO()
    stderr = io.StringIO()
    return ask_user(stdin=stdin, stderr=stderr, stdout=stdout), stdout, stderr


def test_r3_ac4_invalid_reprompts_then_treats_as_no() -> None:
    result, stdout, stderr = _ask_with(["foo", "bar", "baz", "nope"])
    assert result is PromptAnswer.NO
    # Three failed attempts → three guidance lines.
    assert stderr.getvalue().count("Please answer") == 3


def test_r3_valid_answer_short_circuits() -> None:
    result, _, _ = _ask_with(["n"])
    assert result is PromptAnswer.NO


def test_r3_never_recognized() -> None:
    result, _, _ = _ask_with(["never"])
    assert result is PromptAnswer.NEVER


def test_r3_empty_enter_is_yes() -> None:
    result, _, _ = _ask_with([""])
    assert result is PromptAnswer.YES


def test_r3_eof_treats_as_no() -> None:
    stdin = io.StringIO("")
    stdout = io.StringIO()
    stderr = io.StringIO()
    result = ask_user(stdin=stdin, stderr=stderr, stdout=stdout)
    assert result is PromptAnswer.NO


# ------- decide_startup_action integration -------


def test_decide_skip_when_not_tty() -> None:
    result = decide_startup_action(
        is_tty_fn=lambda: False,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        ask_fn=lambda: PromptAnswer.YES,  # should not be called
    )
    assert result is SKIP


def test_decide_skip_when_configured() -> None:
    result = decide_startup_action(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.CONFIGURED,
        ask_fn=lambda: PromptAnswer.YES,
    )
    assert result is SKIP


def test_decide_wizard_on_yes() -> None:
    result = decide_startup_action(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        ask_fn=lambda: PromptAnswer.YES,
    )
    assert result is WIZARD


def test_decide_dismiss_on_never() -> None:
    result = decide_startup_action(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        ask_fn=lambda: PromptAnswer.NEVER,
    )
    assert result is DISMISS


def test_decide_skip_on_no() -> None:
    result = decide_startup_action(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        ask_fn=lambda: PromptAnswer.NO,
    )
    assert result is SKIP
