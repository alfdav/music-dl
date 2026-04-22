"""Security middleware and utilities for the GUI server.

Threat model: music-dl GUI runs a local HTTP server. Any website the user
visits while the GUI is open can attempt requests to localhost. This module
provides defense-in-depth against DNS rebinding, CSRF, path traversal, and
SSRF attacks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# Type alias: a resolver returns the currently-expected bot shared secret
# (empty string when unconfigured). Exposed as a type so tests and FastAPI
# dependency overrides have a single, documented injection contract.
BotTokenResolver = Callable[[], str]

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Audio extensions allowed for local file serving
AUDIO_EXTENSIONS = frozenset({".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac", ".wma"})

# Directories that must never be used as download paths
FORBIDDEN_PATHS = frozenset(
    {
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
        "/var",
        "/boot",
        "/dev",
        "/proc",
        "/sys",
        "/Library",
        "/System",
        "/Applications",
        str(Path.home() / ".ssh"),
        str(Path.home() / ".gnupg"),
        str(Path.home() / ".config"),
    }
)

# Known Tidal CDN hostnames allowed for stream proxying
TIDAL_CDN_HOSTS = frozenset(
    {
        "sp-pr-cf.audio.tidal.com",
        "sp-ad-cf.audio.tidal.com",
        "fa-cf.audio.tidal.com",
        "listening-test.tidal.com",
    }
)


@dataclass(frozen=True)
class LocalAudioPathResolution:
    """Result of resolving a local audio path against GUI trust rules."""

    kind: str
    path: Path | None = None


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token."""
    return secrets.token_urlsafe(32)


class HostValidationMiddleware(BaseHTTPMiddleware):
    """Reject requests with unexpected Host headers to prevent DNS rebinding.

    Only allows requests where the Host header exactly matches an allowed value.
    This prevents an attacker-controlled domain from resolving to 127.0.0.1
    and making cross-origin requests that bypass browser same-origin policy.
    """

    def __init__(self, app, allowed_hosts: list[str]) -> None:
        super().__init__(app)
        self.allowed_hosts = set(allowed_hosts)

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "")
        host_no_port = host.split(":")[0] if ":" in host else host

        if host not in self.allowed_hosts and host_no_port not in {"localhost", "127.0.0.1"}:
            return JSONResponse({"detail": "Forbidden: invalid Host header"}, status_code=403)
        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Require a CSRF token on all state-mutating requests (POST/PATCH/PUT/DELETE).

    The token is generated at server startup, embedded in index.html, and must
    be sent as the X-CSRF-Token header. Cross-origin pages cannot read the
    token from our HTML, so they cannot forge valid mutating requests.

    GET/HEAD/OPTIONS are exempt (safe methods per HTTP spec).
    """

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(self, app, csrf_token: str) -> None:
        super().__init__(app)
        self.csrf_token = csrf_token

    async def dispatch(self, request: Request, call_next):
        if request.method in self.SAFE_METHODS:
            return await call_next(request)

        # Bot API uses bearer tokens, not CSRF — skip CSRF check
        if request.url.path.startswith("/api/bot/"):
            return await call_next(request)

        token = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(token, self.csrf_token):
            return JSONResponse({"detail": "Forbidden: invalid or missing CSRF token"}, status_code=403)
        return await call_next(request)


def validate_audio_path(path_str: str, allowed_dirs: list[str]) -> Path | None:
    """Validate that a file path is a real audio file inside an allowed directory.

    Returns the resolved Path if valid, None if rejected.

    Defenses:
    - Resolves symlinks before checking containment (prevents symlink escape)
    - Uses is_relative_to() instead of string prefix matching
    - Checks file actually exists (no speculative path access)
    - Whitelists audio extensions only
    """
    # CodeQL false-positive: user input is intentionally resolved so we can
    # enforce is_relative_to() containment against allowed_dirs below. That
    # containment check IS the path-injection defense.
    try:
        file_path = Path(path_str).resolve(strict=True)  # lgtm[py/path-injection]
    except (OSError, ValueError):
        return None

    # Extension whitelist
    if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
        return None

    # Must be inside at least one allowed directory
    for allowed in allowed_dirs:
        allowed_resolved = Path(allowed).resolve()
        if file_path.is_relative_to(allowed_resolved):
            return file_path

    return None


def resolve_local_audio_path(
    raw_path: str | None,
    allowed_dirs: list[str],
    *,
    library_trusts_raw_path: bool = False,
    library_resolved_path: Path | None = None,
) -> LocalAudioPathResolution:
    """Resolve a local audio path using GUI trust rules.

    Caller owns the library DB lookup so security.py stays import-clean
    (CodeQL hardening from PR #38). The two library_* args together cover
    the spec's 4-step DB fallback (see local-lyrics-v1 spec §5):

    - library_trusts_raw_path: True iff raw_path is present in the library DB
    - library_resolved_path: result of strict-resolving raw_path, or None
      if either the path is not trusted OR strict resolve failed
    """
    if raw_path is None or not raw_path.strip():
        return LocalAudioPathResolution("bad_request")

    validated = validate_audio_path(raw_path, allowed_dirs)
    if validated is not None:
        return LocalAudioPathResolution("ok", validated)

    if not library_trusts_raw_path:
        return LocalAudioPathResolution("forbidden")

    if library_resolved_path is None:
        return LocalAudioPathResolution("not_found")

    # Belt-and-suspenders: even if DB trusts this path, reject when the raw
    # caller-supplied path is itself a symlink — scan-time checks may have
    # been bypassed (race, migration, or manual DB edit).
    # CodeQL false-positive: is_symlink() only performs lstat(), does not
    # open or leak file contents; this check IS the path-traversal defense.
    try:
        if Path(raw_path).is_symlink():  # lgtm[py/path-injection]
            return LocalAudioPathResolution("forbidden")
    except (OSError, ValueError):
        return LocalAudioPathResolution("forbidden")

    if library_resolved_path.suffix.lower() not in AUDIO_EXTENSIONS:
        return LocalAudioPathResolution("not_audio")

    return LocalAudioPathResolution("ok", library_resolved_path)


def resolve_library_audio_path(
    path_str: str,
    allowed_dirs: list[str],
    trusted_library_path: Path | None = None,
) -> Path | None:
    """Compatibility shim: thin Path|None wrapper for callers that don't need rich kinds.

    Prefer resolve_local_audio_path for new code.
    """
    resolution = resolve_local_audio_path(
        path_str,
        allowed_dirs,
        library_trusts_raw_path=trusted_library_path is not None,
        library_resolved_path=trusted_library_path,
    )
    return resolution.path if resolution.kind == "ok" else None


def validate_download_path(path_str: str) -> bool:
    """Validate that a path is safe to use as a download directory.

    Rejects system directories, non-existent paths, and paths the user
    likely doesn't intend to fill with music files.
    """
    if not path_str or not path_str.strip():
        return False
    try:
        resolved = Path(path_str).resolve()
    except (OSError, ValueError):
        return False

    if not resolved.is_dir():
        return False

    resolved_str = str(resolved)
    for forbidden in FORBIDDEN_PATHS:
        # Resolve the forbidden path too (e.g. /etc → /private/etc on macOS)
        try:
            forbidden_resolved = str(Path(forbidden).resolve())
        except (OSError, ValueError):
            forbidden_resolved = forbidden
        if resolved_str == forbidden_resolved or resolved_str.startswith(forbidden_resolved + "/"):
            return False

    return True


def validate_stream_url(url: str) -> bool:
    """Validate that a stream URL points to Tidal infrastructure.

    Prevents SSRF by ensuring we only proxy requests to *.tidal.com hosts.
    Tidal uses many CDN subdomains (sp-pr-cf, fa-cf, etc.) so we match the
    parent domain rather than maintaining an exhaustive whitelist.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme != "https":
        return False

    host = parsed.hostname or ""
    return host.endswith(".tidal.com") or host == "tidal.com"


# ---------------------------------------------------------------------------
# Bot bearer-token authentication (R1)
# ---------------------------------------------------------------------------


def resolve_bot_shared_token(
    env_getter: Optional[Callable[[str, str], str]] = None,
    path_resolver: Optional[Callable[[], Path]] = None,
) -> str:
    """Resolve the expected bot shared secret.

    Priority:
    1. ``MUSIC_DL_BOT_TOKEN`` env var — takes precedence so Docker/CI
       deployments can inject the secret without relying on a disk file.
    2. Shared-token file the onboarding wizard writes (per
       ``tidal_dl.gui.bot_onboarding.shared_token_path()``). This closes
       the loop: wizard writes → backend reads → bot authenticates.

    Returns an empty string when neither source yields a non-empty value;
    callers fail-closed on empty.

    Exposed as a FastAPI-compatible dependency (zero required args) so
    ``api/bot.require_bot_auth`` can ``Depends(resolve_bot_shared_token)``
    and tests can override it with ``app.dependency_overrides``. The
    optional ``env_getter`` / ``path_resolver`` parameters let unit tests
    exercise both branches without touching ``os.environ`` or disk.
    """
    get_env = env_getter or (lambda key, default: os.environ.get(key, default))
    env_token = (get_env("MUSIC_DL_BOT_TOKEN", "") or "").strip()
    if env_token:
        return env_token

    if path_resolver is None:
        # Deferred import avoids a circular dependency on module load.
        from tidal_dl.gui.bot_onboarding import shared_token_path

        resolve_path = shared_token_path
    else:
        resolve_path = path_resolver

    try:
        return resolve_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def bearer_matches(expected_token: str, authorization: str | None) -> bool:
    """Pure comparator for a bearer header against an expected secret.

    No environment, no disk, no resolution — separable so tests can
    verify comparator semantics without also exercising resolution, and
    so ``api/bot.require_bot_auth`` can combine a ``Depends``-resolved
    token with the comparator. Uses constant-time comparison to prevent
    timing attacks. Returns False for any missing/mis-shaped input.
    """
    if not expected_token or not authorization:
        return False
    scheme, _, supplied = authorization.partition(" ")
    if scheme.lower() != "bearer" or not supplied.strip():
        return False
    return secrets.compare_digest(supplied.strip(), expected_token)


def validate_bot_bearer(
    authorization: str | None, resolver: BotTokenResolver | None = None
) -> bool:
    """Resolve + compare in one call. Retained for callers that want a
    drop-in boolean check; ``api/bot.require_bot_auth`` prefers splitting
    ``Depends(resolve_bot_shared_token)`` + :func:`bearer_matches` so the
    resolver is overridable per-test."""
    expected = (resolver or resolve_bot_shared_token)()
    return bearer_matches(expected, authorization)


# ---------------------------------------------------------------------------
# Stream token signing / verification (R4)
# ---------------------------------------------------------------------------

class _StreamKeyError(Exception):
    """Raised when the stream-token key cannot be derived (bot token blank)."""


def _get_stream_key(resolver: BotTokenResolver | None = None) -> bytes:
    """Derive a deterministic AES-256 key from the bot shared secret.

    The key is stable across process restarts (no random per-process
    component), so tokens issued before a restart remain verifiable
    after. F-015: fail closed when no shared secret is available — a
    fallback constant would let anyone with the source code mint valid
    stream tokens in misconfigured deployments.

    Resolution: env var first, then the wizard's shared-token file (see
    :func:`resolve_bot_shared_token`). The ``resolver`` kwarg exists so
    tests can exercise both happy-path and fail-closed paths by passing
    a stub, without touching ``os.environ`` or disk.
    """
    bot_token = (resolver or resolve_bot_shared_token)()
    if not bot_token:
        raise _StreamKeyError("bot shared token is not configured")
    domain = b"music-dl/bot/stream-token/v1"
    return hashlib.sha256(bot_token.encode() + b"\x00" + domain).digest()


def sign_bot_stream_token(
    payload: dict[str, str],
    ttl_seconds: int = 120,
    *,
    resolver: BotTokenResolver | None = None,
) -> str:
    """Create an AES-GCM encrypted stream token.

    The token is self-contained (restart-safe) and encrypted, so the
    URL itself does not expose the payload (e.g. filesystem paths).
    AES-GCM provides both confidentiality and authentication — tampered
    tokens fail the auth tag check.

    Raises _StreamKeyError when no shared secret is available. The
    ``resolver`` kwarg is plumbed through to :func:`_get_stream_key`
    so tests can inject a stub.

    Returns URL-safe base64 of: nonce(12) || ciphertext || tag(16)
    """
    from Crypto.Cipher import AES  # pycryptodome

    key = _get_stream_key(resolver=resolver)  # fail-closed if blank

    data = {**payload, "exp": int(time.time()) + ttl_seconds}
    raw = json.dumps(data, separators=(",", ":")).encode()

    nonce = secrets.token_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(raw)

    return base64.urlsafe_b64encode(nonce + ciphertext + tag).decode()


def verify_bot_stream_token(
    token: str, *, resolver: BotTokenResolver | None = None
) -> dict[str, str] | None:
    """Verify and decrypt a stream token. Returns payload dict or None on failure."""
    from Crypto.Cipher import AES

    try:
        key = _get_stream_key(resolver=resolver)  # fail-closed: None for everyone
    except _StreamKeyError:
        return None

    try:
        blob = base64.urlsafe_b64decode(token)
    except Exception:
        return None

    # Minimum length: 12-byte nonce + 16-byte tag + 1 byte ciphertext
    if len(blob) < 29:
        return None

    nonce = blob[:12]
    tag = blob[-16:]
    ciphertext = blob[12:-16]

    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    try:
        raw = cipher.decrypt_and_verify(ciphertext, tag)
    except Exception:
        return None

    try:
        data = json.loads(raw)
    except Exception:
        return None

    # F-025: reject non-dict payloads (e.g. arrays, null) before accessing keys
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("exp"), (int, float)) or time.time() > data["exp"]:
        return None
    return data
