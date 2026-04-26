from types import SimpleNamespace

import sidecar_entry


def test_ignore_shutdown_signals_skips_missing_signals():
    calls = []
    fake_ignore = object()

    def fake_signal(sig, handler):
        calls.append((sig, handler))

    fake_signal_module = SimpleNamespace(SIGINT=2, SIG_IGN=fake_ignore, signal=fake_signal)

    sidecar_entry._ignore_shutdown_signals(fake_signal_module)

    assert calls == [(2, fake_ignore)]


def test_ignore_shutdown_signals_ignores_unsupported_signal():
    calls = []
    fake_ignore = object()

    def fake_signal(sig, handler):
        calls.append((sig, handler))
        if sig == 1:
            raise ValueError("unsupported signal")

    fake_signal_module = SimpleNamespace(SIGINT=2, SIGHUP=1, SIG_IGN=fake_ignore, signal=fake_signal)

    sidecar_entry._ignore_shutdown_signals(fake_signal_module)

    assert calls == [(2, fake_ignore), (1, fake_ignore)]
