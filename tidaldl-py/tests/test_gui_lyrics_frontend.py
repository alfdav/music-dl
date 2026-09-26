from pathlib import Path

from tests.gui_js_source import read_gui_js

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "index.html"
STYLE_CSS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "style.css"


def test_index_contains_direct_body_child_lyrics_overlay_mount():
    html = INDEX_HTML.read_text()

    assert 'id="lyrics-panel"' in html
    assert 'id="lyrics-close"' in html
    assert 'id="lyrics-body"' in html
    assert 'id="lyrics-save"' in html
    assert "Save lyrics" in html
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
    assert '.lyrics-save' in css


def test_style_contains_reduced_motion_without_hiding_player_actions():
    css = STYLE_CSS.read_text()

    assert '@media (prefers-reduced-motion: reduce)' in css
    # Player-bar invariance: lyrics-open must not hide heart/download.
    # Locked by tidaldl-py/tests/lyrics-sync.test.js.
    assert '.lyrics-open #now-heart' not in css
    assert '.lyrics-open #now-download' not in css


def test_app_has_lyrics_state_contract():
    source = read_gui_js()

    assert 'lyricsPanelState' in source
    assert 'lyricsCanonicalTrackPath' in source
    assert 'lyricsRequestToken' in source
    assert 'lyricsCache' in source
    assert 'lyricsError' in source


def test_app_has_payload_validation_and_cache_key_hooks():
    source = read_gui_js()

    assert 'function validateLyricsPayload(payload)' in source
    assert 'payload.track_path' in source
    assert 'lyricsState.lyricsCache[payload.track_path]' in source
    assert 'lyricsState.lyricsCanonicalTrackPath = null' in source
    assert 'end_ms <= line.start_ms' in source


def test_app_wires_album_art_toggle_close_button_queue_and_escape():
    source = read_gui_js()

    assert 'function toggleLyricsPanel()' in source
    assert 'document.getElementById(\'lyrics-close\')' in source
    assert "e.code === 'Escape'" in source
    assert 'btn-queue' in source
    assert 'closeLyricsPanel(' in source


def test_app_has_synced_rendering_and_artwork_motion_hooks():
    source = read_gui_js()

    assert 'function renderSyncedLyrics(payload)' in source
    assert 'function syncActiveLyricLine()' in source
    assert 'function applyLyricsArtworkBackground(track)' in source
    assert 'requestAnimationFrame(syncActiveLyricLine)' in source
    assert "window.matchMedia('(prefers-reduced-motion: reduce)')" in source
    assert "viewport.addEventListener('wheel'" in source
    assert "lyricsBody.addEventListener('wheel'" not in source


def test_app_enables_lyrics_for_tidal_only_now_playing():
    source = read_gui_js()

    assert "function _lyricsRequestKey(track)" in source
    assert "function _lyricsTrackOpenable(track)" in source
    assert "btnLyrics.disabled = !_lyricsTrackOpenable(track)" in source
    assert "btnLyrics.disabled = !(track.is_local && (track.local_path || track.path))" not in source
    assert "/lyrics?" in source
    assert "params.set('title'" in source
    assert "params.set('artist'" in source


def test_app_accepts_tidal_lyrics_sources_and_honest_empty_copy():
    source = read_gui_js()

    assert "'tidal-synced'" in source
    assert "'tidal-unsynced'" in source
    assert "No lyrics available for this track." in source
    assert "This local track does not have synced, embedded, or sidecar lyrics yet." not in source


def test_app_opens_lyrics_without_is_local_gate():
    source = read_gui_js()

    assert "if (!track || !track.is_local || !localPath) return;" not in source
    assert "_lyricsTrackOpenable(track)" in source
    assert "tidal_track_id" in source


def test_app_can_save_tidal_lyrics_to_local_sidecar():
    source = read_gui_js()

    assert "function _lyricsCanSave(" in source
    assert "function saveLyricsForCurrentTrack(" in source
    assert "/lyrics/save" in source
    assert "tidal-synced" in source
    assert "lrc-synced" in source
