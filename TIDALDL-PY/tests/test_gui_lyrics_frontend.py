from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "index.html"
STYLE_CSS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "style.css"


def test_index_contains_direct_body_child_lyrics_overlay_mount():
    html = INDEX_HTML.read_text()

    assert 'id="lyrics-panel"' in html
    assert 'id="lyrics-close"' in html
    assert 'id="lyrics-body"' in html
    assert html.index('id="queue-panel"') < html.index('id="lyrics-panel"') < html.index('<footer class="player"')


def test_style_contains_lyrics_panel_shells_and_player_height_variable():
    css = STYLE_CSS.read_text()

    assert '--player-height:' in css
    assert '.lyrics-panel' in css
    assert '.lyrics-panel.open' in css
    assert '.lyrics-shell-loading' in css
    assert '.lyrics-shell-empty' in css
    assert '.lyrics-shell-error' in css
    assert '.lyrics-shell-unsynced' in css
    assert '.lyrics-shell-synced' in css
    assert '.lyrics-artwork-bg' in css


def test_style_contains_reduced_motion_and_open_state_action_hiding_rules():
    css = STYLE_CSS.read_text()

    assert '@media (prefers-reduced-motion: reduce)' in css
    assert '.lyrics-open #now-heart' in css
    assert '.lyrics-open #now-download' in css
