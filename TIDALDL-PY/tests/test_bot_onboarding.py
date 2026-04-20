"""R1 acceptance tests — onboarding state detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from tidal_dl.gui.bot_onboarding import (
    SHARED_TOKEN_FILENAME,
    OnboardingState,
    detect_state,
    shared_token_path,
)


@pytest.fixture
def token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    token = tmp_path / SHARED_TOKEN_FILENAME
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(token))
    return token


def test_ac1_configured_when_token_non_empty(token: Path) -> None:
    token.write_text("some-token-value\n")
    assert detect_state() == OnboardingState.CONFIGURED


def test_ac2_needs_setup_when_absent(token: Path) -> None:
    assert detect_state() == OnboardingState.NEEDS_SETUP


def test_empty_token_file_is_needs_setup(token: Path) -> None:
    token.write_text("")
    assert detect_state() == OnboardingState.NEEDS_SETUP


def test_whitespace_only_token_is_needs_setup(token: Path) -> None:
    token.write_text("   \n\n")
    assert detect_state() == OnboardingState.NEEDS_SETUP


def test_env_var_overrides_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alt_token = tmp_path / "alt-token"
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(alt_token))
    assert shared_token_path() == alt_token


def test_explicit_path_win_over_env(tmp_path: Path) -> None:
    token = tmp_path / "t"
    token.write_text("x")
    assert detect_state(token_path=token) == OnboardingState.CONFIGURED
