from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "app.js"


def test_stream_playback_errors_do_not_auto_skip_entire_queue():
    source = APP_JS.read_text()

    assert "const canAutoSkip = current && current.is_local && state.queueIndex < state.queue.length - 1;" in source
    assert "toast(label + ' unavailable', 'error');" in source
    assert "if (canAutoSkip) {" in source
