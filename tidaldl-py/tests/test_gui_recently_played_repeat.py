from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "app.js"


def test_recently_played_cards_seed_queue_before_playback():
    source = APP_JS.read_text()

    assert "function startPlaybackFromList(track, tracks)" in source
    assert "startPlaybackFromList(track, recentlyPlayed);" in source
