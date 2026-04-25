from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "index.html"
STYLE_CSS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "style.css"
APP_JS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "app.js"


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
    assert '.lyrics-synced-line' in css
    assert '.lyrics-synced-line.active' in css
    assert '.lyrics-unsynced-copy' in css


def test_style_contains_reduced_motion_and_open_state_action_hiding_rules():
    css = STYLE_CSS.read_text()

    assert '@media (prefers-reduced-motion: reduce)' in css
    assert '.lyrics-open #now-heart' in css
    assert '.lyrics-open #now-download' in css


def test_app_has_lyrics_state_contract():
    source = APP_JS.read_text()

    assert 'lyricsPanelState' in source
    assert 'lyricsCanonicalTrackPath' in source
    assert 'lyricsRequestToken' in source
    assert 'lyricsCache' in source
    assert 'lyricsError' in source


def test_app_has_payload_validation_and_cache_key_hooks():
    source = APP_JS.read_text()

    assert 'function validateLyricsPayload(payload)' in source
    assert 'payload.track_path' in source
    assert 'lyricsState.lyricsCache[payload.track_path]' in source
    assert 'lyricsState.lyricsCanonicalTrackPath = null' in source
    assert 'end_ms <= line.start_ms' in source


def test_app_wires_album_art_toggle_close_button_queue_and_escape():
    source = APP_JS.read_text()

    assert 'function toggleLyricsPanel()' in source
    assert 'document.getElementById(\'lyrics-close\')' in source
    assert "e.code === 'Escape'" in source
    assert 'btn-queue' in source
    assert 'closeLyricsPanel(' in source


def test_app_has_synced_rendering_and_artwork_motion_hooks():
    source = APP_JS.read_text()

    assert 'function renderSyncedLyrics(payload)' in source
    assert 'function syncActiveLyricLine()' in source
    assert 'function applyLyricsArtworkBackground(track)' in source
    assert 'requestAnimationFrame(syncActiveLyricLine)' in source
    assert "window.matchMedia('(prefers-reduced-motion: reduce)')" in source
    assert "lyricsBody.addEventListener('wheel'" in source
