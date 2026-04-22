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
#
# These tests use dependency injection (env_getter / path_resolver kwargs)
# rather than pytest's monkeypatch fixture. The resolver's own contract
# is "consult these two sources" — injection lets each test express that
# contract directly without mutating process-global state.


def _env_map(mapping: dict[str, str]):
    return lambda key, default: mapping.get(key, default)


def test_token_source_env_when_env_set(tmp_path: Path) -> None:
    file_token = tmp_path / "bot-shared-token"
    file_token.write_text("file-token")  # present but env should win
    src = bot_token_source(
        env_getter=_env_map({"MUSIC_DL_BOT_TOKEN": "env-wins"}),
        path_resolver=lambda: file_token,
    )
    assert src is TokenSource.ENV


def test_token_source_file_when_env_blank(tmp_path: Path) -> None:
    file_token = tmp_path / "bot-shared-token"
    file_token.write_text("from-file\n")
    src = bot_token_source(
        env_getter=_env_map({"MUSIC_DL_BOT_TOKEN": "   "}),  # whitespace-only
        path_resolver=lambda: file_token,
    )
    assert src is TokenSource.FILE


def test_token_source_none_when_nothing_configured(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-file"
    src = bot_token_source(
        env_getter=_env_map({}),  # env unset
        path_resolver=lambda: missing,
    )
    assert src is TokenSource.NONE


def test_token_source_none_when_file_empty(tmp_path: Path) -> None:
    empty = tmp_path / "bot-shared-token"
    empty.write_text("   \n")  # whitespace-only
    src = bot_token_source(
        env_getter=_env_map({}),
        path_resolver=lambda: empty,
    )
    assert src is TokenSource.NONE
