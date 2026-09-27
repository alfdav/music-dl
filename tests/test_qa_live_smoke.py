import ast
import inspect
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import asdict
from pathlib import Path

import requests

from scripts import qa_live_smoke
from scripts.qa_live_smoke import ServiceResult, Track, check_discord, check_tidal

CHECK_TIDAL_COMMAND = (
    "from dataclasses import asdict; import json; "
    "from scripts.qa_live_smoke import check_tidal; "
    "print(json.dumps(asdict(check_tidal())))"
)


class FakeResponse:
    def __init__(self, status_code: int, payload: object = None) -> None:
        self.status_code = status_code
        self.payload = {"id": "123"} if payload is None else payload

    def json(self) -> object:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, *, logged_in: bool = True, search_result: object = None) -> None:
        self.logged_in = logged_in
        self.search_result = (
            {"tracks": [object()]} if search_result is None else search_result
        )
        self.request_session = requests.Session()
        self.calls: list[tuple[str, object]] = []

    def check_login(self) -> bool:
        self.calls.append(("check_login", None))
        return self.logged_in

    def search(self, query: str, *, models: list[type], limit: int) -> object:
        self.calls.append(("search", (query, models, limit)))
        return self.search_result


class FakeTidal:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.calls: list[tuple[str, object]] = []
        self.adapter_at_login: requests.adapters.HTTPAdapter | None = None

    def login_token(self, *, quiet: bool) -> bool:
        self.adapter_at_login = self.session.request_session.get_adapter(
            "https://tidal.com"
        )
        self.calls.append(("login_token", quiet))
        return True


def test_tidal_check_restores_token_checks_login_and_searches_once() -> None:
    session = FakeSession()
    tidal = FakeTidal(session)

    result = check_tidal(lambda: tidal)

    assert result.status == "pass"
    assert tidal.calls == [("login_token", True)]
    assert session.calls == [
        ("check_login", None),
        ("search", ("Daft Punk", [Track], 1)),
    ]
    adapter = session.request_session.get_adapter("https://tidal.com")
    assert isinstance(adapter, qa_live_smoke._TimeoutHTTPAdapter)
    assert tidal.adapter_at_login is adapter
    assert adapter.timeout_seconds == 10


def test_default_tidal_requires_ephemeral_config_before_constructor(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.pop("RUNNER_TEMP", None)
    env.pop("MUSIC_DL_CONFIG_DIR", None)
    env["HOME"] = str(home)
    env.pop("XDG_CONFIG_HOME", None)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            CHECK_TIDAL_COMMAND,
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["detail"] == (
        "ephemeral credential directory required"
    )
    assert list(home.iterdir()) == []


def test_default_tidal_writes_only_inside_runner_temp_without_network(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "runner"
    config = runner / "music-dl"
    outside = tmp_path / "outside"
    config.mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("unchanged")
    before = {
        path.relative_to(outside): path.stat().st_mtime_ns
        for path in outside.rglob("*")
    }
    env = os.environ.copy()
    env["RUNNER_TEMP"] = str(runner)
    env["MUSIC_DL_CONFIG_DIR"] = str(config)
    env["HOME"] = str(outside)
    env["XDG_CONFIG_HOME"] = str(outside)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            CHECK_TIDAL_COMMAND,
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    after = {
        path.relative_to(outside): path.stat().st_mtime_ns
        for path in outside.rglob("*")
    }
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["detail"] == "login failed"
    assert before == after
    # Phase 0/1 never writes an empty token.json. A failed restore must
    # leave the ephemeral dir without a token file and never touch HOME.
    assert not (config / "token.json").exists()
    assert all(path.is_relative_to(runner) for path in config.rglob("*"))


def test_default_tidal_rejects_resolved_config_escape(tmp_path: Path) -> None:
    runner = tmp_path / "runner"
    outside = tmp_path / "outside"
    runner.mkdir()
    outside.mkdir()
    config_link = runner / "config"
    config_link.symlink_to(outside, target_is_directory=True)
    env = os.environ.copy()
    env["RUNNER_TEMP"] = str(runner)
    env["MUSIC_DL_CONFIG_DIR"] = str(config_link)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            CHECK_TIDAL_COMMAND,
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["detail"] == (
        "ephemeral credential directory required"
    )
    assert list(outside.iterdir()) == []


def test_default_tidal_rejects_token_symlink_escape(tmp_path: Path) -> None:
    runner = tmp_path / "runner"
    config = runner / "music-dl"
    outside = tmp_path / "outside"
    config.mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"do not replace")
    token_link = config / "token.json"
    token_link.symlink_to(sentinel)
    env = os.environ.copy()
    env["RUNNER_TEMP"] = str(runner)
    env["MUSIC_DL_CONFIG_DIR"] = str(config)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            CHECK_TIDAL_COMMAND,
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["detail"] == (
        "ephemeral credential directory required"
    )
    assert sentinel.read_bytes() == b"do not replace"
    assert token_link.is_symlink()


def test_tidal_failed_login_and_empty_search_are_concise() -> None:
    failed_login = check_tidal(lambda: FakeTidal(FakeSession(logged_in=False)))
    empty_search = check_tidal(lambda: FakeTidal(FakeSession(search_result={})))

    assert asdict(failed_login) | {"latency_ms": 0.0} == {
        "service": "tidal",
        "status": "fail",
        "latency_ms": 0.0,
        "detail": "login failed",
    }
    assert empty_search.status == "fail"
    assert empty_search.detail == "search returned no results"


def test_tidal_exception_does_not_leak_exception_text() -> None:
    secret = "tidal-secret-in-error"

    def fail_factory() -> object:
        raise RuntimeError(secret)

    result = check_tidal(fail_factory)

    assert result.status == "fail"
    assert result.detail == "request failed"
    assert secret not in json.dumps(asdict(result))


def test_discord_check_is_read_only_and_secret_safe() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    token = "do-not-print-me"

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        calls.append((url, kwargs))
        return FakeResponse(200, {"id": "123", "username": "music-dl"})

    result = check_discord(token, get=fake_get)

    assert result.status == "pass"
    assert calls == [
        (
            "https://discord.com/api/v10/users/@me",
            {
                "headers": {"Authorization": f"Bot {token}"},
                "timeout": 10,
                "allow_redirects": False,
            },
        )
    ]
    serialized = json.dumps(asdict(result))
    assert token not in serialized
    assert "music-dl" not in serialized


def test_discord_missing_token_timeout_and_non_200_are_concise() -> None:
    missing = check_discord("")

    def timeout(*args: object, **kwargs: object) -> object:
        raise requests.Timeout("secret response body")

    timed_out = check_discord("token", get=timeout)
    rejected = check_discord(
        "token",
        get=lambda *args, **kwargs: FakeResponse(401, "secret response body"),
    )

    assert (missing.status, missing.detail) == ("fail", "missing DISCORD_TOKEN")
    assert (timed_out.status, timed_out.detail) == ("fail", "request timed out")
    assert (rejected.status, rejected.detail) == ("fail", "HTTP 401")
    assert "secret response body" not in json.dumps(
        [asdict(missing), asdict(timed_out), asdict(rejected)]
    )


def test_discord_redirect_and_invalid_200_payloads_fail_closed() -> None:
    redirected = check_discord("token", get=lambda *args, **kwargs: FakeResponse(302))
    malformed = check_discord(
        "token",
        get=lambda *args, **kwargs: FakeResponse(
            200, ValueError("secret malformed HTML body")
        ),
    )
    html = check_discord(
        "token", get=lambda *args, **kwargs: FakeResponse(200, "<html>")
    )
    missing_id = check_discord(
        "token", get=lambda *args, **kwargs: FakeResponse(200, {})
    )
    empty_id = check_discord(
        "token", get=lambda *args, **kwargs: FakeResponse(200, {"id": ""})
    )

    assert (redirected.status, redirected.detail) == ("fail", "HTTP 302")
    for result in (malformed, html, missing_id, empty_id):
        assert (result.status, result.detail) == ("fail", "invalid identity response")
    assert "secret malformed HTML body" not in json.dumps(asdict(malformed))


def test_module_exposes_no_mutating_http_helpers() -> None:
    for method in ("post", "put", "patch", "delete"):
        assert not hasattr(qa_live_smoke, method)


def test_main_always_collects_both_service_results() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(qa_live_smoke.main)))
    results_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "results"
            for target in node.targets
        )
    ]

    assert len(results_assignments) == 1
    value = results_assignments[0].value
    assert isinstance(value, ast.List)
    assert [ast.unparse(item) for item in value.elts] == [
        "check_tidal()",
        "check_discord(token)",
    ]
    assert not any(isinstance(node, ast.If) for node in ast.walk(tree))


def test_write_results_serializes_both_safe_service_entries(tmp_path: Path) -> None:
    output = tmp_path / "live.json"
    results = [
        ServiceResult("tidal", "pass", 1.25, "authenticated search succeeded"),
        ServiceResult("discord", "fail", 0.1, "missing DISCORD_TOKEN"),
    ]

    qa_live_smoke._write_results(output, results)

    payload = json.loads(output.read_text())
    assert set(payload) == {"services"}
    assert [item["service"] for item in payload["services"]] == ["tidal", "discord"]
    assert all(
        set(item) == {"service", "status", "latency_ms", "detail"}
        for item in payload["services"]
    )
