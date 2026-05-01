"""GUI-owned Discord bot setup and launch endpoints."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, SecretStr
import requests

from tidal_dl.gui.bot_onboarding import TokenSource, bot_token_source, shared_token_path
from tidal_dl.helper.path import path_config_base

router = APIRouter(prefix="/bot-control", tags=["bot-control"])

BOT_ENV_FILENAME = "discord-bot.env"
BOT_PID_FILENAME = "discord-bot.pid"
STOP_TIMEOUT_SECONDS = 5
DISCORD_API = "https://discord.com/api/v10"
DISCORD_LOOKUP_TIMEOUT_SECONDS = 2
USER_FIELDS = [
    "DISCORD_TOKEN",
    "DISCORD_APPLICATION_ID",
    "ALLOWED_GUILD_ID",
    "ALLOWED_CHANNEL_ID",
    "ALLOWED_USER_ID",
]
ALL_FIELDS = [
    *USER_FIELDS,
    "MUSIC_DL_BASE_URL",
    "MUSIC_DL_BOT_TOKEN",
]
ID_FIELDS = [
    "DISCORD_APPLICATION_ID",
    "ALLOWED_GUILD_ID",
    "ALLOWED_CHANNEL_ID",
    "ALLOWED_USER_ID",
]


class BotConfigureRequest(BaseModel):
    discord_token: SecretStr
    discord_application_id: str
    allowed_guild_id: str
    allowed_channel_id: str
    allowed_user_id: str


def bot_env_path() -> Path:
    override = os.environ.get("MUSIC_DL_BOT_ENV_PATH", "").strip()
    if override:
        return Path(override)
    return Path(path_config_base()) / BOT_ENV_FILENAME


def bot_pid_path() -> Path:
    override = os.environ.get("MUSIC_DL_BOT_PID_PATH", "").strip()
    if override:
        return Path(override)
    return Path(path_config_base()) / BOT_PID_FILENAME


def bot_root_path() -> Path:
    override = os.environ.get("MUSIC_DL_BOT_PATH", "").strip()
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    return here.parents[4] / "apps" / "discord-bot"


def legacy_bot_env_paths() -> list[Path]:
    return [
        Path(path_config_base()) / ".env",
        bot_root_path() / ".env",
    ]


@router.get("/status")
def status(request: Request) -> dict:
    return _status(request)


@router.post("/configure")
def configure(payload: BotConfigureRequest, request: Request) -> dict:
    values = {
        "DISCORD_TOKEN": payload.discord_token.get_secret_value().strip(),
        "DISCORD_APPLICATION_ID": payload.discord_application_id.strip(),
        "ALLOWED_GUILD_ID": payload.allowed_guild_id.strip(),
        "ALLOWED_CHANNEL_ID": payload.allowed_channel_id.strip(),
        "ALLOWED_USER_ID": payload.allowed_user_id.strip(),
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")
    invalid = _invalid_id_fields(values)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid Discord IDs: {', '.join(invalid)}")

    token = _ensure_shared_token()
    values["MUSIC_DL_BASE_URL"] = request.app.state.daemon_meta.base_url
    values["MUSIC_DL_BOT_TOKEN"] = token
    _write_private_file_atomic(bot_env_path(), _serialize_env(values))
    return _status(request)


@router.post("/start")
def start(request: Request) -> dict:
    return _start_bot_for_app(request.app)


@router.post("/stop")
def stop(request: Request) -> dict:
    _stop_bot_for_app(request.app)
    return _status(request)


@router.post("/restart")
def restart(request: Request) -> dict:
    _stop_bot_for_app(request.app)
    return _start_bot_for_app(request.app)


def start_configured_bot(app) -> None:
    """Best-effort app startup hook. Startup must not fail because bot cannot start."""
    env_values = _active_env()[1]
    if not _config_values_usable(env_values) or not _token_ready():
        return
    try:
        _start_bot_for_app(app)
    except HTTPException:
        return


def stop_running_bot(app) -> None:
    _stop_bot_for_app(app)


def _start_bot_for_app(app) -> dict:
    running = _running_process_for_app(app)
    if running is not None:
        return _status_for_app(app)

    env_path, env_values = _active_env()
    missing = _missing_user_fields(env_values)
    invalid = _invalid_id_fields(env_values)
    if missing or invalid or not _token_ready():
        raise HTTPException(status_code=400, detail="Discord bot is not configured")

    root = bot_root_path()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="Discord bot sources not found")

    bun = shutil.which("bun")
    if bun is None:
        raise HTTPException(status_code=400, detail="Bun is required to start the Discord bot")

    try:
        proc = subprocess.Popen(
            [bun, "run", "start"],
            cwd=str(root),
            env={**os.environ, "MUSIC_DL_BOT_ENV_PATH": str(env_path)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not start Discord bot: {exc}") from exc

    app.state.discord_bot_process = proc
    app.state.discord_bot_pid = proc.pid
    _write_private_file_atomic(bot_pid_path(), f"{proc.pid}\n")
    return _status_for_app(app)


def _status(request: Request) -> dict:
    return _status_for_app(request.app)


def _status_for_app(app) -> dict:
    env_path, env_values = _active_env()
    missing = _missing_user_fields(env_values)
    invalid = _invalid_id_fields(env_values)
    token_ready = _token_ready()
    return {
        "configured": not missing and not invalid and token_ready,
        "running": _running_process_for_app(app) is not None,
        "backend_url": env_values.get("MUSIC_DL_BASE_URL", "").strip() or app.state.daemon_meta.base_url,
        "missing_fields": missing,
        "invalid_fields": invalid,
        "configured_fields": [key for key in USER_FIELDS if key not in missing and key not in invalid],
        "saved_ids": _saved_ids(env_values),
        "saved_labels": _saved_labels(env_values),
        "config_file_present": bool(env_values),
        "shared_token_present": token_ready,
        "env_path": str(env_path),
        "env_source": _env_source(env_path),
        "token_source": bot_token_source().value,
        "bot_root": str(bot_root_path()),
    }


def _running_process(request: Request):
    return _running_process_for_app(request.app)


def _running_process_for_app(app):
    proc = getattr(app.state, "discord_bot_process", None)
    if proc is None:
        pid = getattr(app.state, "discord_bot_pid", None) or _read_recorded_pid()
        if pid is None:
            return None
        if _pid_alive(pid):
            app.state.discord_bot_pid = pid
            return pid
        _forget_recorded_pid(app)
        return None
    if proc.poll() is None:
        return proc
    _forget_recorded_pid(app)
    return None


def _stop_bot(request: Request) -> None:
    _stop_bot_for_app(request.app)


def _stop_bot_for_app(app) -> None:
    proc = _running_process_for_app(app)
    if proc is None:
        _forget_recorded_pid(app)
        return

    pid = proc if isinstance(proc, int) else proc.pid
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        if isinstance(proc, int):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            proc.terminate()

    try:
        if isinstance(proc, int):
            _wait_for_pid_exit(pid, STOP_TIMEOUT_SECONDS)
        else:
            proc.wait(timeout=STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            if isinstance(proc, int):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
        if not isinstance(proc, int):
            proc.wait(timeout=STOP_TIMEOUT_SECONDS)
    finally:
        _forget_recorded_pid(app)


def _missing_user_fields(values: dict[str, str]) -> list[str]:
    return [key for key in USER_FIELDS if not values.get(key, "").strip()]


def _read_recorded_pid() -> int | None:
    path = bot_pid_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        pid = int(raw)
    except ValueError:
        _remove_pid_file()
        return None
    if pid <= 0:
        _remove_pid_file()
        return None
    return pid


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _wait_for_pid_exit(pid: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    raise subprocess.TimeoutExpired(str(pid), timeout)


def _forget_recorded_pid(app) -> None:
    app.state.discord_bot_process = None
    app.state.discord_bot_pid = None
    _remove_pid_file()


def _remove_pid_file() -> None:
    try:
        bot_pid_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _active_env() -> tuple[Path, dict[str, str]]:
    canonical = bot_env_path()
    canonical_values = _load_env(canonical)
    if _config_values_usable(canonical_values):
        return canonical, canonical_values

    for path in legacy_bot_env_paths():
        values = _load_env(path)
        if _config_values_usable(values):
            return path, values
    return canonical, canonical_values


def _config_values_usable(values: dict[str, str]) -> bool:
    return bool(values) and not _missing_user_fields(values) and not _invalid_id_fields(values)


def _env_source(path: Path) -> str:
    try:
        if path == bot_env_path():
            return "canonical"
        if path in legacy_bot_env_paths():
            return "legacy"
    except OSError:
        pass
    return "custom"


def _invalid_id_fields(values: dict[str, str]) -> list[str]:
    return [
        key for key in ID_FIELDS
        if values.get(key, "").strip() and not _is_discord_snowflake(values[key].strip())
    ]


def _is_discord_snowflake(value: str) -> bool:
    return value.isdigit() and 17 <= len(value) <= 20


def _saved_ids(values: dict[str, str]) -> dict[str, str]:
    return {
        "discord_application_id": values.get("DISCORD_APPLICATION_ID", "").strip(),
        "allowed_guild_id": values.get("ALLOWED_GUILD_ID", "").strip(),
        "allowed_channel_id": values.get("ALLOWED_CHANNEL_ID", "").strip(),
        "allowed_user_id": values.get("ALLOWED_USER_ID", "").strip(),
    }


def _saved_labels(values: dict[str, str]) -> dict[str, str]:
    saved_ids = _saved_ids(values)
    labels = {
        "discord_application_id": _id_label("Application", saved_ids["discord_application_id"]),
        "allowed_guild_id": _id_label("Server", saved_ids["allowed_guild_id"]),
        "allowed_channel_id": _channel_label(saved_ids["allowed_channel_id"]),
        "allowed_user_id": _id_label("User", saved_ids["allowed_user_id"]),
    }

    token = values.get("DISCORD_TOKEN", "").strip()
    if not _looks_like_discord_token(token) or not all(value.isdigit() for value in saved_ids.values() if value):
        return labels

    headers = {"Authorization": f"Bot {token}", "User-Agent": "music-dl-gui/1.0"}
    app = _discord_get_json("/oauth2/applications/@me", headers)
    guild = _discord_get_json(f"/guilds/{saved_ids['allowed_guild_id']}", headers)
    channel = _discord_get_json(f"/channels/{saved_ids['allowed_channel_id']}", headers)
    member = _discord_get_json(
        f"/guilds/{saved_ids['allowed_guild_id']}/members/{saved_ids['allowed_user_id']}",
        headers,
    )

    if app.get("name"):
        labels["discord_application_id"] = f"{app['name']} app"
    if guild.get("name"):
        labels["allowed_guild_id"] = str(guild["name"])
    if channel.get("name"):
        labels["allowed_channel_id"] = f"#{channel['name']}"
    user = member.get("user") if isinstance(member.get("user"), dict) else {}
    user_label = member.get("nick") or user.get("global_name") or user.get("username")
    if user_label:
        labels["allowed_user_id"] = str(user_label)
    return labels


def _id_label(prefix: str, value: str) -> str:
    if not value:
        return ""
    return f"{prefix} {value}" if value.isdigit() else f"{prefix} saved"


def _channel_label(value: str) -> str:
    if not value:
        return ""
    return f"Channel {value}" if value.isdigit() else "Channel saved"


def _looks_like_discord_token(value: str) -> bool:
    return value.count(".") >= 2


def _discord_get_json(path: str, headers: dict[str, str]) -> dict:
    try:
        resp = requests.get(
            DISCORD_API + path,
            headers=headers,
            timeout=DISCORD_LOOKUP_TIMEOUT_SECONDS,
        )
        if not resp.ok:
            return {}
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except (requests.RequestException, ValueError):
        return {}


def _token_ready() -> bool:
    if bot_token_source() is TokenSource.ENV:
        return True
    try:
        return bool(shared_token_path().read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _ensure_shared_token() -> str:
    try:
        existing = shared_token_path().read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    token = secrets.token_urlsafe(32)
    _write_private_file_atomic(shared_token_path(), token + "\n")
    return token


def _serialize_env(values: dict[str, str]) -> str:
    lines = [
        "# music-dl Discord bot configuration.",
        "# Written by the GUI setup flow.",
    ]
    for key in ALL_FIELDS:
        lines.append(f"{key}={_quote_env(values[key])}")
    return "\n".join(lines) + "\n"


def _quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _load_env(path: Path) -> dict[str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    out: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = _unquote_env(value.strip())
    return out


def _unquote_env(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _write_private_file_atomic(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{secrets.token_hex(8)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
