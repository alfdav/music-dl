"""User guide must match the 2026-09-18 verified TypeSafe note."""

from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
GUIDE = DOCS / "djai-edition-advice.md"
OVERVIEW = DOCS / "djai-modules.md"
BOT = DOCS / "bot-onboarding.md"

EDITION_DISCLAIMER = (
    "AI suggestions can be wrong. Treat edition advice as advisory. "
    "Confirm paths yourself (Reveal in Finder) before Clean Up. "
    "music-dl never promises a suggestion is safe to delete."
)
SHARED_DISCLAIMER = (
    "DJAI modules that use AI can make mistakes. "
    "Verify important actions yourself before you confirm them."
)


def test_guide_exists_and_uses_verified_facts():
    text = GUIDE.read_text(encoding="utf-8")
    assert "DJAI" in text
    assert "not a Settings toggle" in text
    assert "TYPESAFE_API_KEY" in text
    assert "typesafe-music-edition" in text
    assert "https://console.typesafe.ai/settings/keys" in text
    assert "https://console.typesafe.ai/playground" in text
    assert "https://api.typesafe.ai/v1/systemone" in text
    assert "jev-latest" in text
    assert "hello@typesafe.ai" in text
    assert "early access" in text
    assert "Score" in text
    assert "candidate" in text
    assert "keep_both" in text
    assert "0.95" in text
    assert "safe to delete" in text  # only as a prohibition
    assert "never" in text.lower()
    assert "never promises a suggestion is safe to delete" in text


def test_guide_has_ai_mistake_disclaimer():
    text = GUIDE.read_text(encoding="utf-8")
    assert EDITION_DISCLAIMER in text
    assert SHARED_DISCLAIMER in text
    how = text.split("## How to use")[1]
    assert "AI suggestions can be wrong" in how
    assert "Reveal in Finder" in how
    assert "never promises a suggestion is safe to delete" in how
    assert "Confirm Clean Up" in how


def test_overview_has_shared_disclaimer_and_links():
    text = OVERVIEW.read_text(encoding="utf-8")
    assert SHARED_DISCLAIMER in text
    assert EDITION_DISCLAIMER in text
    assert "bot-onboarding.md" in text
    assert "djai-edition-advice.md" in text
    assert "Discord Bot" in text
    assert "Edition advice" in text
    assert "join-the-waitlist" not in text
    assert "Create key" not in text


def test_bot_onboarding_disclaimer_is_light():
    text = BOT.read_text(encoding="utf-8")
    assert "DJAI hosts automation modules" in text
    assert "djai-modules.md" in text
    assert "LLM" not in text
    assert "judge" not in text.lower()


def test_guide_does_not_invent_waitlist_or_key_buttons():
    text = GUIDE.read_text(encoding="utf-8")
    assert "join-the-waitlist" not in text
    assert "typesafe.ai/waitlist" not in text
    assert "Create key" not in text
    assert "Join Waitlist" in text
    assert "jobs" in text.lower()
