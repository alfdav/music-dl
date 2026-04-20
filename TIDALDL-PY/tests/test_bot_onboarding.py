"""R1 acceptance tests — onboarding state detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from tidal_dl.gui.bot_onboarding import (
    SHARED_TOKEN_FILENAME,
    OnboardingState,
    TokenSource,
    bot_token_source,
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


# ── bot_token_source (startup canary replacing wizard R10 probe) ──────────────


def test_token_source_env_when_env_set(
    token: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", "env-wins")
    # Even if the file exists, env takes precedence.
    token.write_text("file-token")
    assert bot_token_source() is TokenSource.ENV


def test_token_source_file_when_env_blank(
    token: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", "   ")
    token.write_text("from-file\n")
    assert bot_token_source() is TokenSource.FILE


def test_token_source_none_when_nothing_configured(
    token: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MUSIC_DL_BOT_TOKEN", raising=False)
    # token file intentionally not written
    assert bot_token_source() is TokenSource.NONE


def test_token_source_none_when_file_empty(
    token: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MUSIC_DL_BOT_TOKEN", raising=False)
    token.write_text("")
    assert bot_token_source() is TokenSource.NONE
