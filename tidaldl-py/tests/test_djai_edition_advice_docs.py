"""User guide must match the 2026-09-18 verified TypeSafe note."""

from pathlib import Path

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "djai-edition-advice.md"


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


def test_guide_does_not_invent_waitlist_or_key_buttons():
    text = GUIDE.read_text(encoding="utf-8")
    assert "join-the-waitlist" not in text
    assert "typesafe.ai/waitlist" not in text
    assert "Create key" not in text
    assert "Join Waitlist" in text
    assert "jobs" in text.lower()
