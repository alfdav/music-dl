"""GUI-owned Discord bot setup and launch endpoints."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, SecretStr

from tidal_dl.gui.bot_onboarding import TokenSource, bot_token_source, shared_token_path
from tidal_dl.helper.path import path_config_base

router = APIRouter(prefix="/bot-control", tags=["bot-control"])

BOT_ENV_FILENAME = "discord-bot.env"
STOP_TIMEOUT_SECONDS = 5
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


def bot_root_path() -> Path:
    override = os.environ.get("MUSIC_DL_BOT_PATH", "").strip()
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    return here.parents[4] / "apps" / "discord-bot"


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

    token = _ensure_shared_token()
    values["MUSIC_DL_BASE_URL"] = request.app.state.daemon_meta.base_url
    values["MUSIC_DL_BOT_TOKEN"] = token
    _write_private_file_atomic(bot_env_path(), _serialize_env(values))
    return _status(request)


@router.post("/start")
def start(request: Request) -> dict:
    return _start_bot(request)


@router.post("/stop")
def stop(request: Request) -> dict:
    _stop_bot(request)
    return _status(request)


@router.post("/restart")
def restart(request: Request) -> dict:
    _stop_bot(request)
    return _start_bot(request)


def _start_bot(request: Request) -> dict:
    running = _running_process(request)
    if running is not None:
        return _status(request)

    env_values = _load_env(bot_env_path())
    missing = _missing_user_fields(env_values)
    if missing or not _token_ready():
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not start Discord bot: {exc}") from exc

    request.app.state.discord_bot_process = proc
    return _status(request)


def _status(request: Request) -> dict:
    env_values = _load_env(bot_env_path())
    missing = _missing_user_fields(env_values)
    return {
        "configured": not missing and _token_ready(),
        "running": _running_process(request) is not None,
        "backend_url": request.app.state.daemon_meta.base_url,
        "missing_fields": missing,
        "env_path": str(bot_env_path()),
        "token_source": bot_token_source().value,
        "bot_root": str(bot_root_path()),
    }


def _running_process(request: Request):
    proc = getattr(request.app.state, "discord_bot_process", None)
    if proc is None:
        return None
    if proc.poll() is None:
        return proc
    request.app.state.discord_bot_process = None
    return None


def _stop_bot(request: Request) -> None:
    proc = _running_process(request)
    if proc is None:
        request.app.state.discord_bot_process = None
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        proc.terminate()

    try:
        proc.wait(timeout=STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            proc.kill()
        proc.wait(timeout=STOP_TIMEOUT_SECONDS)
    finally:
        request.app.state.discord_bot_process = None


def _missing_user_fields(values: dict[str, str]) -> list[str]:
    return [key for key in USER_FIELDS if not values.get(key, "").strip()]


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
