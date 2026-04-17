"""Security middleware and utilities for the GUI server.

Threat model: music-dl GUI runs a local HTTP server. Any website the user
visits while the GUI is open can attempt requests to localhost. This module
provides defense-in-depth against DNS rebinding, CSRF, path traversal, and
SSRF attacks.
"""

from __future__ import annotations

import secrets
from pathlib import Path

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
    try:
        file_path = Path(path_str).resolve(strict=True)  # strict=True: file must exist
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


def resolve_library_audio_path(
    path_str: str,
    allowed_dirs: list[str],
    trusted_library_path: Path | None = None,
) -> Path | None:
    """Resolve an audio path from either configured dirs or the scanned library DB."""
    validated = validate_audio_path(path_str, allowed_dirs)
    if validated is not None:
        return validated
    if trusted_library_path is None:
        return None
    trusted = trusted_library_path
    if trusted.suffix.lower() not in AUDIO_EXTENSIONS:
        return None
    return trusted


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
