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


# ------- write_dismissal_flag (backend R3 AC3) -------


def test_write_dismissal_flag_creates_empty_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tidal_dl.gui.bot_first_run import write_dismissal_flag

    flag = tmp_path / "nested" / "dismissed"
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(flag))
    write_dismissal_flag()
    assert flag.exists()
    assert flag.read_text() == ""
    # Idempotent: second call does not raise.
    write_dismissal_flag()


# ------- run_first_run_flow (backend R4 + R5) -------


def test_run_first_run_skips_when_not_tty(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tidal_dl.gui.bot_first_run import run_first_run_flow

    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(tmp_path / "t"))
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(tmp_path / "d"))
    dispatch_called = []
    rc = run_first_run_flow(
        is_tty_fn=lambda: False,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        ask_fn=lambda: PromptAnswer.YES,
        dispatch_fn=lambda: dispatch_called.append(1) or 0,
    )
    assert rc == 0
    assert dispatch_called == []


def test_run_first_run_dispatches_on_yes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tidal_dl.gui.bot_first_run import run_first_run_flow

    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(tmp_path / "t"))
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(tmp_path / "d"))
    calls = []
    rc = run_first_run_flow(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        ask_fn=lambda: PromptAnswer.YES,
        dispatch_fn=lambda: calls.append("wizard") or 0,
        output=io.StringIO(),
    )
    assert rc == 0
    assert calls == ["wizard"]


def test_run_first_run_writes_flag_on_never(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tidal_dl.gui.bot_first_run import run_first_run_flow

    flag_path = tmp_path / "dismissed"
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(tmp_path / "t"))
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(flag_path))
    dispatch_calls = []
    rc = run_first_run_flow(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        ask_fn=lambda: PromptAnswer.NEVER,
        dispatch_fn=lambda: dispatch_calls.append(1) or 0,
        output=io.StringIO(),
    )
    assert rc == 0
    assert flag_path.exists()
    # R3 AC3: wizard is NOT run when answer is "never"
    assert dispatch_calls == []


def test_run_first_run_wizard_failure_does_not_abort_server(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4 AC5: backend server startup is never aborted by wizard failure."""
    from tidal_dl.gui.bot_first_run import run_first_run_flow

    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(tmp_path / "t"))
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(tmp_path / "d"))
    out = io.StringIO()
    rc = run_first_run_flow(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        ask_fn=lambda: PromptAnswer.YES,
        dispatch_fn=lambda: 42,  # non-zero exit
        output=out,
    )
    assert rc == 0
    assert "retry" in out.getvalue().lower() or "re-run" in out.getvalue().lower()


def test_r5_force_bypasses_configured_state(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5 AC1 + AC4: force flag triggers prompt even when state is configured."""
    from tidal_dl.gui.bot_first_run import run_first_run_flow

    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(tmp_path / "t"))
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(tmp_path / "d"))
    dispatch_calls = []
    run_first_run_flow(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.CONFIGURED,  # would normally skip
        ask_fn=lambda: PromptAnswer.YES,
        dispatch_fn=lambda: dispatch_calls.append(1) or 0,
        output=io.StringIO(),
        force=True,
    )
    assert dispatch_calls == [1]


def test_r5_force_ignores_dismissal_flag_without_modifying_it(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5 AC2 + AC3: force ignores dismissal for this invocation but does
    NOT touch the flag — a previously-dismissed user is not re-enrolled
    just because they ran --setup-bot once."""
    from tidal_dl.gui.bot_first_run import run_first_run_flow

    flag_path = tmp_path / "dismissed"
    flag_path.write_text("")  # pre-existing dismissal
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(tmp_path / "t"))
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(flag_path))
    flag_mtime_before = flag_path.stat().st_mtime_ns

    dispatch_calls = []
    run_first_run_flow(
        is_tty_fn=lambda: True,
        detect_fn=lambda: OnboardingState.DISMISSED,
        ask_fn=lambda: PromptAnswer.NO,  # user chooses No on the forced prompt
        dispatch_fn=lambda: dispatch_calls.append(1) or 0,
        output=io.StringIO(),
        force=True,
    )
    # Force prompted the user → but they said "no" → no wizard, no flag change.
    assert dispatch_calls == []
    assert flag_path.exists()
    assert flag_path.stat().st_mtime_ns == flag_mtime_before


def test_r5_force_without_tty_prints_and_skips(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tidal_dl.gui.bot_first_run import run_first_run_flow

    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(tmp_path / "t"))
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(tmp_path / "d"))
    out = io.StringIO()
    dispatch_calls = []
    rc = run_first_run_flow(
        is_tty_fn=lambda: False,
        detect_fn=lambda: OnboardingState.NEEDS_SETUP,
        ask_fn=lambda: PromptAnswer.YES,
        dispatch_fn=lambda: dispatch_calls.append(1) or 0,
        output=out,
        force=True,
    )
    assert rc == 0
    assert dispatch_calls == []
    assert "interactive terminal" in out.getvalue()
