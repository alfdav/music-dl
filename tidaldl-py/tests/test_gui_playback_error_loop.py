from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
from tests.gui_js_source import read_gui_js


def test_local_errors_skip_but_remote_errors_stop_without_queue_traversal():
    source = read_gui_js()

    assert "if (!current || !current.is_local) {" in source
    assert "toast('Tidal stream unavailable \\u2014 try again later', 'error');" in source
    assert "toast(label + ' unavailable', 'error');" in source
    assert "const canAutoSkip = state.queueIndex < state.queue.length - 1;" in source
    assert "setTimeout(() => { state.queueIndex++; playTrack(state.queue[state.queueIndex]); }, 800);" in source
    assert "async function _retryLocalPlaybackAfterHeal(track)" in source
    assert "if (status === 202 || status === 409)" in source
    assert "await _waitForReconcileIdle(token, track);" in source
    assert "if (_localHealAttempted === key) return false;" in source
    assert "if (token !== _localHealToken || !_sameQueueTrack(track)) return true;" in source


def test_shuffle_uses_queue_order_instead_of_random_next():
    source = read_gui_js()

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
