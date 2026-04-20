"""R1 acceptance tests — onboarding state detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from tidal_dl.gui.bot_onboarding import (
    DISMISSAL_FLAG_FILENAME,
    SHARED_TOKEN_FILENAME,
    OnboardingState,
    detect_state,
    dismissal_flag_path,
    shared_token_path,
)


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    token = tmp_path / SHARED_TOKEN_FILENAME
    flag = tmp_path / DISMISSAL_FLAG_FILENAME
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(token))
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(flag))
    return token, flag


def test_ac3_needs_setup_when_neither_present(paths: tuple[Path, Path]) -> None:
    assert detect_state() == OnboardingState.NEEDS_SETUP


def test_ac1_configured_when_token_non_empty(paths: tuple[Path, Path]) -> None:
    token, _ = paths
    token.write_text("some-token-value\n")
    assert detect_state() == OnboardingState.CONFIGURED


def test_ac2_dismissed_when_flag_present(paths: tuple[Path, Path]) -> None:
    _, flag = paths
    flag.write_text("")
    assert detect_state() == OnboardingState.DISMISSED


def test_configured_precedence_over_dismissed(paths: tuple[Path, Path]) -> None:
    token, flag = paths
    token.write_text("tkn")
    flag.write_text("")
    # A stale dismissal flag next to a real token reads as configured.
    assert detect_state() == OnboardingState.CONFIGURED


def test_empty_token_file_falls_through(paths: tuple[Path, Path]) -> None:
    token, _ = paths
    token.write_text("")
    assert detect_state() == OnboardingState.NEEDS_SETUP


def test_whitespace_only_token_falls_through(paths: tuple[Path, Path]) -> None:
    token, _ = paths
    token.write_text("   \n\n")
    assert detect_state() == OnboardingState.NEEDS_SETUP


def test_env_var_overrides_default_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alt_token = tmp_path / "alt-token"
    alt_flag = tmp_path / "alt-flag"
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(alt_token))
    monkeypatch.setenv("MUSIC_DL_BOT_DISMISSAL_PATH", str(alt_flag))
    assert shared_token_path() == alt_token
    assert dismissal_flag_path() == alt_flag


def test_explicit_paths_win_over_env(tmp_path: Path) -> None:
    token = tmp_path / "t"
    flag = tmp_path / "f"
    token.write_text("x")
    assert detect_state(token_path=token, dismissal_path=flag) == OnboardingState.CONFIGURED
