from tidal_dl.gui import daemon
from tidal_dl.gui.daemon import DaemonMetadata, metadata_path, read_metadata, remove_metadata, write_metadata


def test_metadata_round_trip(tmp_path):
    meta = DaemonMetadata.for_current_process(port=8765, mode="browser", status="starting")

    write_metadata(meta, config_dir=tmp_path)

    assert metadata_path(config_dir=tmp_path) == tmp_path / "daemon.json"
    assert read_metadata(config_dir=tmp_path) == meta

    remove_metadata(meta, config_dir=tmp_path)
    assert not metadata_path(config_dir=tmp_path).exists()


def test_cleanup_removes_dead_pid_metadata(tmp_path):
    meta = DaemonMetadata.for_current_process(port=8765, mode="browser")
    stale = DaemonMetadata(**{**meta.__dict__, "pid": 99999999})
    write_metadata(stale, config_dir=tmp_path)

    assert daemon.clean_stale_metadata(
        config_dir=tmp_path,
        pid_checker=lambda pid: False,
        ready_checker=lambda meta: False,
    ) is True
    assert read_metadata(config_dir=tmp_path) is None


def test_cleanup_preserves_live_starting_metadata(tmp_path):
    meta = DaemonMetadata.for_current_process(port=8765, mode="browser")
    starting = DaemonMetadata(**{**meta.__dict__, "pid": 12345, "status": "starting"})
    write_metadata(starting, config_dir=tmp_path)

    assert daemon.clean_stale_metadata(
        config_dir=tmp_path,
        pid_checker=lambda pid: True,
        ready_checker=lambda meta: False,
    ) is True
    assert read_metadata(config_dir=tmp_path) == starting


def test_select_port_prefers_default():
    def free(host, port):
        return True

    assert daemon.select_port(8765, port_checker=free) == 8765


def test_select_port_falls_back_when_requested_busy():
    ports = iter([False, True])

    def fake_free(host, port):
        return next(ports)

    assert daemon.select_port(
        8765,
        port_checker=fake_free,
        candidates=lambda start: iter([8765, 8766]),
    ) == 8766


def test_discover_ready_daemon_requires_live_pid_and_ready_health(tmp_path):
    meta = DaemonMetadata.for_current_process(port=8765, mode="browser", status="ready")
    write_metadata(meta, config_dir=tmp_path)

    assert daemon.discover_ready_daemon(
        config_dir=tmp_path,
        pid_checker=lambda pid: True,
        ready_checker=lambda meta: True,
    ) == meta


def test_discover_ready_daemon_cleans_dead_pid_even_if_health_responds(tmp_path):
    meta = DaemonMetadata.for_current_process(port=8765, mode="browser", status="ready")
    write_metadata(DaemonMetadata(**{**meta.__dict__, "pid": 99999999}), config_dir=tmp_path)

    assert daemon.discover_ready_daemon(
        config_dir=tmp_path,
        pid_checker=lambda pid: False,
        ready_checker=lambda meta: True,
    ) is None
    assert read_metadata(config_dir=tmp_path) is None
