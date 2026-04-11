from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "app.js"


def test_queue_playback_errors_advance_to_next_track_without_dead_air():
    source = APP_JS.read_text()

    assert "toast(label + ' unavailable', 'error');" in source
    assert "const canAutoSkip = current && state.queueIndex < state.queue.length - 1;" in source
    assert "setTimeout(() => { state.queueIndex++; playTrack(state.queue[state.queueIndex]); }, 800);" in source


def test_shuffle_uses_queue_order_instead_of_random_next():
    source = APP_JS.read_text()

    assert "if (state.shuffle) {\n    state.queueIndex = Math.floor(Math.random() * state.queue.length);" not in source
    assert "state.queueIndex = (state.queueIndex + 1) % state.queue.length;" in source
    assert "let _queueEntrySeq = 0;" in source
    assert "function _cloneQueueTrack(track, entryId)" in source
    assert "function _reshuffleCurrentQueue()" in source
    assert "function _restoreOriginalQueueOrder()" in source
    assert "function _findTrackIndex(list, track)" in source
    assert "if (a._queueEntryId != null && b._queueEntryId != null) {" in source
    assert "const idx = current ? _findTrackIndex(state.queueOriginal, current) : 0;" in source
    assert "state.queueOriginal = state.queueOriginal.filter(t => _trackKey(t) !== removedKey);" in source
    assert "const removedBeforeCurrent = state.queue.slice(0, state.queueIndex).filter(t => _trackKey(t) === removedKey).length;" in source
    assert "if (removedBeforeCurrent) state.queueIndex -= removedBeforeCurrent;" in source
    assert "else if (state.queueIndex >= state.queue.length) state.queueIndex = state.queue.length - 1;" in source
    assert "state.queueOriginal = (data.queueOriginal && data.queueOriginal.length > 0) ? data.queueOriginal : data.queue.slice();" in source
