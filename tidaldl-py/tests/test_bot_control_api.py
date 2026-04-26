from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


HOST_HEADER = {"host": "localhost:8765"}


def _client():
    from tidal_dl.gui import create_app

    app = create_app(port=8765)
    return app, TestClient(app)


def _csrf_headers(app) -> dict[str, str]:
    return {**HOST_HEADER, "X-CSRF-Token": app.state.csrf_token}


def _write_bot_config(tmp_path: Path, monkeypatch) -> Path:
    env_path = tmp_path / "discord-bot.env"
    token_path = tmp_path / "bot-shared-token"
    bot_root = tmp_path / "discord-bot"
    bot_root.mkdir()
    (bot_root / "package.json").write_text("{}", encoding="utf-8")
    env_path.write_text(
        "\n".join(
            [
                'DISCORD_TOKEN="discord-secret"',
                'DISCORD_APPLICATION_ID="123"',
                'ALLOWED_GUILD_ID="456"',
                'ALLOWED_CHANNEL_ID="789"',
                'ALLOWED_USER_ID="999"',
                'MUSIC_DL_BASE_URL="http://127.0.0.1:8765"',
                'MUSIC_DL_BOT_TOKEN="shared"',
            ]
        ),
        encoding="utf-8",
    )
    token_path.write_text("shared\n", encoding="utf-8")
    monkeypatch.setenv("MUSIC_DL_BOT_ENV_PATH", str(env_path))
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(token_path))
    monkeypatch.setenv("MUSIC_DL_BOT_PATH", str(bot_root))
    return bot_root


def test_bot_control_status_reports_missing_config(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MUSIC_DL_BOT_ENV_PATH", str(tmp_path / "discord-bot.env"))
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(tmp_path / "bot-shared-token"))
    monkeypatch.setenv("MUSIC_DL_BOT_PATH", str(tmp_path / "discord-bot"))

    app, client = _client()

    resp = client.get("/api/bot-control/status", headers=HOST_HEADER)

    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert data["running"] is False
    assert data["backend_url"] == "http://127.0.0.1:8765"
    assert data["missing_fields"] == [
        "DISCORD_TOKEN",
        "DISCORD_APPLICATION_ID",
        "ALLOWED_GUILD_ID",
        "ALLOWED_CHANNEL_ID",
        "ALLOWED_USER_ID",
    ]
    assert "token" not in data


def test_bot_control_configure_writes_env_and_shared_token(
    tmp_path: Path, monkeypatch
) -> None:
    env_path = tmp_path / "discord-bot.env"
    token_path = tmp_path / "bot-shared-token"
    monkeypatch.setenv("MUSIC_DL_BOT_ENV_PATH", str(env_path))
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(token_path))
    monkeypatch.setenv("MUSIC_DL_BOT_PATH", str(tmp_path / "discord-bot"))

    app, client = _client()

    resp = client.post(
        "/api/bot-control/configure",
        headers=_csrf_headers(app),
        json={
            "discord_token": "discord-secret",
            "discord_application_id": "123",
            "allowed_guild_id": "456",
            "allowed_channel_id": "789",
            "allowed_user_id": "999",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert "discord-secret" not in resp.text

    env_text = env_path.read_text(encoding="utf-8")
    assert 'DISCORD_TOKEN="discord-secret"' in env_text
    assert 'DISCORD_APPLICATION_ID="123"' in env_text
    assert 'ALLOWED_GUILD_ID="456"' in env_text
    assert 'ALLOWED_CHANNEL_ID="789"' in env_text
    assert 'ALLOWED_USER_ID="999"' in env_text
    assert 'MUSIC_DL_BASE_URL="http://127.0.0.1:8765"' in env_text
    assert "MUSIC_DL_BOT_TOKEN=" in env_text
    shared_token = token_path.read_text(encoding="utf-8").strip()
    assert shared_token
    assert shared_token not in resp.text
    assert (token_path.stat().st_mode & 0o777) == 0o600
    assert (env_path.stat().st_mode & 0o777) == 0o600


def test_bot_control_configure_error_does_not_echo_discord_token(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MUSIC_DL_BOT_ENV_PATH", str(tmp_path / "discord-bot.env"))
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(tmp_path / "bot-shared-token"))
    monkeypatch.setenv("MUSIC_DL_BOT_PATH", str(tmp_path / "discord-bot"))

    app, client = _client()

    resp = client.post(
        "/api/bot-control/configure",
        headers=_csrf_headers(app),
        json={
            "discord_token": "discord-secret",
            "discord_application_id": "",
            "allowed_guild_id": "456",
            "allowed_channel_id": "789",
            "allowed_user_id": "999",
        },
    )

    assert resp.status_code == 400
    assert "discord-secret" not in resp.text


def test_bot_control_start_launches_bun_from_configured_bot_root(
    tmp_path: Path, monkeypatch
) -> None:
    bot_root = _write_bot_config(tmp_path, monkeypatch)

    from tidal_dl.gui.api import bot_control

    launched = {}

    class FakeProcess:
        pid = 4321

        def poll(self):
            return None

    def fake_popen(cmd, **kwargs):
        launched["cmd"] = cmd
        launched["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(bot_control.shutil, "which", lambda name: "/usr/bin/bun" if name == "bun" else None)
    monkeypatch.setattr(bot_control.subprocess, "Popen", fake_popen)

    app, client = _client()
    resp = client.post("/api/bot-control/start", headers=_csrf_headers(app), json={})

    assert resp.status_code == 200
    assert resp.json()["running"] is True
    assert launched["cmd"] == ["/usr/bin/bun", "run", "start"]
    assert launched["kwargs"]["cwd"] == str(bot_root)
    assert launched["kwargs"]["start_new_session"] is True


def test_bot_control_stop_terminates_running_bot(tmp_path: Path, monkeypatch) -> None:
    _write_bot_config(tmp_path, monkeypatch)

    from tidal_dl.gui.api import bot_control

    killed = []

    class FakeProcess:
        pid = 4321
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def wait(self, timeout=None):
            self.stopped = True
            return 0

    proc = FakeProcess()
    monkeypatch.setattr(bot_control.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    app, client = _client()
    app.state.discord_bot_process = proc
    resp = client.post("/api/bot-control/stop", headers=_csrf_headers(app), json={})

    assert resp.status_code == 200
    assert resp.json()["running"] is False
    assert killed
    assert getattr(app.state, "discord_bot_process") is None


def test_bot_control_restart_stops_then_starts_bot(tmp_path: Path, monkeypatch) -> None:
    bot_root = _write_bot_config(tmp_path, monkeypatch)

    from tidal_dl.gui.api import bot_control

    killed = []
    launched = []

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def wait(self, timeout=None):
            self.stopped = True
            return 0

    old_proc = FakeProcess(4321)

    def fake_popen(cmd, **kwargs):
        launched.append((cmd, kwargs))
        return FakeProcess(9876)

    monkeypatch.setattr(bot_control.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(bot_control.shutil, "which", lambda name: "/usr/bin/bun" if name == "bun" else None)
    monkeypatch.setattr(bot_control.subprocess, "Popen", fake_popen)

    app, client = _client()
    app.state.discord_bot_process = old_proc
    resp = client.post("/api/bot-control/restart", headers=_csrf_headers(app), json={})

    assert resp.status_code == 200
    assert resp.json()["running"] is True
    assert killed
    assert launched[0][0] == ["/usr/bin/bun", "run", "start"]
    assert launched[0][1]["cwd"] == str(bot_root)
