from __future__ import annotations

import os
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
                'DISCORD_APPLICATION_ID="123456789012345678"',
                'ALLOWED_GUILD_ID="223456789012345678"',
                'ALLOWED_CHANNEL_ID="323456789012345678"',
                'ALLOWED_USER_ID="423456789012345678"',
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


def _write_env(path: Path, *, app_id: str, guild_id: str, channel_id: str, user_id: str) -> None:
    path.write_text(
        "\n".join(
            [
                'DISCORD_TOKEN="discord-secret"',
                f'DISCORD_APPLICATION_ID="{app_id}"',
                f'ALLOWED_GUILD_ID="{guild_id}"',
                f'ALLOWED_CHANNEL_ID="{channel_id}"',
                f'ALLOWED_USER_ID="{user_id}"',
                'MUSIC_DL_BASE_URL="http://127.0.0.1:8765"',
                'MUSIC_DL_BOT_TOKEN="shared"',
            ]
        ),
        encoding="utf-8",
    )


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
    assert data["configured_fields"] == []
    assert data["saved_ids"] == {
        "discord_application_id": "",
        "allowed_guild_id": "",
        "allowed_channel_id": "",
        "allowed_user_id": "",
    }
    assert data["saved_labels"] == {
        "discord_application_id": "",
        "allowed_guild_id": "",
        "allowed_channel_id": "",
        "allowed_user_id": "",
    }
    assert data["config_file_present"] is False
    assert data["shared_token_present"] is False
    assert data["env_source"] == "canonical"
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
            "discord_application_id": "123456789012345678",
            "allowed_guild_id": "223456789012345678",
            "allowed_channel_id": "323456789012345678",
            "allowed_user_id": "423456789012345678",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["configured_fields"] == [
        "DISCORD_TOKEN",
        "DISCORD_APPLICATION_ID",
        "ALLOWED_GUILD_ID",
        "ALLOWED_CHANNEL_ID",
        "ALLOWED_USER_ID",
    ]
    assert data["saved_ids"] == {
        "discord_application_id": "123456789012345678",
        "allowed_guild_id": "223456789012345678",
        "allowed_channel_id": "323456789012345678",
        "allowed_user_id": "423456789012345678",
    }
    assert data["saved_labels"] == {
        "discord_application_id": "Application 123456789012345678",
        "allowed_guild_id": "Server 223456789012345678",
        "allowed_channel_id": "Channel 323456789012345678",
        "allowed_user_id": "User 423456789012345678",
    }
    assert data["config_file_present"] is True
    assert data["shared_token_present"] is True
    assert data["env_source"] == "canonical"
    assert "discord-secret" not in resp.text

    env_text = env_path.read_text(encoding="utf-8")
    assert 'DISCORD_TOKEN="discord-secret"' in env_text
    assert 'DISCORD_APPLICATION_ID="123456789012345678"' in env_text
    assert 'ALLOWED_GUILD_ID="223456789012345678"' in env_text
    assert 'ALLOWED_CHANNEL_ID="323456789012345678"' in env_text
    assert 'ALLOWED_USER_ID="423456789012345678"' in env_text
    assert 'MUSIC_DL_BASE_URL="http://127.0.0.1:8765"' in env_text
    assert "MUSIC_DL_BOT_TOKEN=" in env_text
    shared_token = token_path.read_text(encoding="utf-8").strip()
    assert shared_token
    assert shared_token not in resp.text
    assert (token_path.stat().st_mode & 0o777) == 0o600
    assert (env_path.stat().st_mode & 0o777) == 0o600


def test_bot_control_status_uses_valid_legacy_env_when_canonical_has_placeholders(
    tmp_path: Path, monkeypatch
) -> None:
    canonical = tmp_path / "discord-bot.env"
    legacy_dir = tmp_path / "discord-bot"
    legacy_dir.mkdir()
    legacy = legacy_dir / ".env"
    token_path = tmp_path / "bot-shared-token"
    _write_env(
        canonical,
        app_id="app-1",
        guild_id="guild-1",
        channel_id="channel-1",
        user_id="user-1",
    )
    _write_env(
        legacy,
        app_id="123456789012345678",
        guild_id="223456789012345678",
        channel_id="323456789012345678",
        user_id="423456789012345678",
    )
    token_path.write_text("shared\n", encoding="utf-8")
    monkeypatch.setenv("MUSIC_DL_BOT_ENV_PATH", str(canonical))
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(token_path))
    monkeypatch.setenv("MUSIC_DL_BOT_PATH", str(legacy_dir))

    app, client = _client()
    resp = client.get("/api/bot-control/status", headers=HOST_HEADER)

    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["env_path"] == str(legacy)
    assert data["env_source"] == "legacy"
    assert data["saved_ids"]["allowed_guild_id"] == "223456789012345678"


def test_bot_control_saved_labels_resolve_discord_names(monkeypatch) -> None:
    from tidal_dl.gui.api import bot_control

    class FakeResponse:
        ok = True

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    def fake_get(url, **kwargs):
        assert "Authorization" in kwargs["headers"]
        assert "real.token.value" in kwargs["headers"]["Authorization"]
        if url.endswith("/oauth2/applications/@me"):
            return FakeResponse({"name": "Living Room DJ"})
        if url.endswith("/guilds/223456789012345678"):
            return FakeResponse({"name": "Alfredo's House"})
        if url.endswith("/channels/323456789012345678"):
            return FakeResponse({"name": "music-requests"})
        if url.endswith("/guilds/223456789012345678/members/423456789012345678"):
            return FakeResponse({"nick": "Alfredo"})
        return FakeResponse({})

    monkeypatch.setattr(bot_control.requests, "get", fake_get)

    labels = bot_control._saved_labels(
        {
            "DISCORD_TOKEN": "real.token.value",
            "DISCORD_APPLICATION_ID": "123456789012345678",
            "ALLOWED_GUILD_ID": "223456789012345678",
            "ALLOWED_CHANNEL_ID": "323456789012345678",
            "ALLOWED_USER_ID": "423456789012345678",
        }
    )

    assert labels == {
        "discord_application_id": "Living Room DJ app",
        "allowed_guild_id": "Alfredo's House",
        "allowed_channel_id": "#music-requests",
        "allowed_user_id": "Alfredo",
    }


def test_bot_control_saved_labels_hide_placeholder_ids() -> None:
    from tidal_dl.gui.api import bot_control

    labels = bot_control._saved_labels(
        {
            "DISCORD_TOKEN": "placeholder",
            "DISCORD_APPLICATION_ID": "app-1",
            "ALLOWED_GUILD_ID": "guild-1",
            "ALLOWED_CHANNEL_ID": "channel-1",
            "ALLOWED_USER_ID": "user-1",
        }
    )

    assert labels == {
        "discord_application_id": "Application saved",
        "allowed_guild_id": "Server saved",
        "allowed_channel_id": "Channel saved",
        "allowed_user_id": "User saved",
    }


def test_bot_control_status_rejects_placeholder_ids(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / "discord-bot.env"
    token_path = tmp_path / "bot-shared-token"
    env_path.write_text(
        "\n".join(
            [
                'DISCORD_TOKEN="discord-secret"',
                'DISCORD_APPLICATION_ID="app-1"',
                'ALLOWED_GUILD_ID="guild-1"',
                'ALLOWED_CHANNEL_ID="channel-1"',
                'ALLOWED_USER_ID="user-1"',
                'MUSIC_DL_BASE_URL="http://127.0.0.1:8765"',
                'MUSIC_DL_BOT_TOKEN="shared"',
            ]
        ),
        encoding="utf-8",
    )
    token_path.write_text("shared\n", encoding="utf-8")
    monkeypatch.setenv("MUSIC_DL_BOT_ENV_PATH", str(env_path))
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN_PATH", str(token_path))
    monkeypatch.setenv("MUSIC_DL_BOT_PATH", str(tmp_path / "discord-bot"))

    app, client = _client()

    resp = client.get("/api/bot-control/status", headers=HOST_HEADER)

    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert data["invalid_fields"] == [
        "DISCORD_APPLICATION_ID",
        "ALLOWED_GUILD_ID",
        "ALLOWED_CHANNEL_ID",
        "ALLOWED_USER_ID",
    ]
    assert data["saved_labels"] == {
        "discord_application_id": "Application saved",
        "allowed_guild_id": "Server saved",
        "allowed_channel_id": "Channel saved",
        "allowed_user_id": "User saved",
    }


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
            "allowed_guild_id": "223456789012345678",
            "allowed_channel_id": "323456789012345678",
            "allowed_user_id": "423456789012345678",
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
    assert launched["kwargs"]["env"]["MUSIC_DL_BOT_ENV_PATH"] == str(tmp_path / "discord-bot.env")
    assert launched["kwargs"]["start_new_session"] is True


def test_bot_control_start_reuses_live_recorded_pid_without_spawning(
    tmp_path: Path, monkeypatch
) -> None:
    _write_bot_config(tmp_path, monkeypatch)
    pid_path = tmp_path / "discord-bot.pid"
    pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    monkeypatch.setenv("MUSIC_DL_BOT_PID_PATH", str(pid_path))

    from tidal_dl.gui.api import bot_control

    def fail_popen(*args, **kwargs):
        raise AssertionError("start must not spawn when recorded bot PID is alive")

    monkeypatch.setattr(bot_control.subprocess, "Popen", fail_popen)

    app, client = _client()
    resp = client.post("/api/bot-control/start", headers=_csrf_headers(app), json={})

    assert resp.status_code == 200
    assert resp.json()["running"] is True


def test_bot_control_start_replaces_stale_recorded_pid(
    tmp_path: Path, monkeypatch
) -> None:
    bot_root = _write_bot_config(tmp_path, monkeypatch)
    pid_path = tmp_path / "discord-bot.pid"
    pid_path.write_text("999999999\n", encoding="utf-8")
    monkeypatch.setenv("MUSIC_DL_BOT_PID_PATH", str(pid_path))

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
    assert pid_path.read_text(encoding="utf-8").strip() == "4321"


def test_bot_control_lifespan_starts_and_stops_configured_bot(
    tmp_path: Path, monkeypatch
) -> None:
    _write_bot_config(tmp_path, monkeypatch)
    pid_path = tmp_path / "discord-bot.pid"
    monkeypatch.setenv("MUSIC_DL_BOT_PID_PATH", str(pid_path))

    from tidal_dl.gui import create_app
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

    def fake_popen(cmd, **kwargs):
        return proc

    monkeypatch.setattr(bot_control.shutil, "which", lambda name: "/usr/bin/bun" if name == "bun" else None)
    monkeypatch.setattr(bot_control.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(bot_control.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    app = create_app(port=8765)
    with TestClient(app) as client:
        resp = client.get("/api/bot-control/status", headers=HOST_HEADER)
        assert resp.status_code == 200
        assert resp.json()["running"] is True
        assert pid_path.read_text(encoding="utf-8").strip() == "4321"

    assert killed
    assert getattr(app.state, "discord_bot_process") is None
    assert not pid_path.exists()


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
