"""Redact Tidal tokens and login material from logs and bug text."""

from __future__ import annotations

import logging
import re

_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-~+/=]+")
_JSON_SECRET = re.compile(
    r'(?i)("(?:access_token|refresh_token|token|user_code|verification_uri(?:_complete)?)"\s*:\s*")([^"]+)(")'
)
_ASSIGNED_SECRET = re.compile(
    r"(?i)\b(access_token|refresh_token|user_code|verification_uri(?:_complete)?)\s*[:=]\s*\S+"
)


def redact_secrets(text: str | None) -> str:
    """Return ``text`` with tokens, refresh tokens, and device codes removed."""
    if not text:
        return ""
    redacted = _BEARER.sub("Bearer [REDACTED]", text)
    redacted = _JSON_SECRET.sub(r"\1[REDACTED]\3", redacted)
    redacted = _ASSIGNED_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return redacted


class RedactingFilter:
    """Logging filter that redacts secrets on every record."""

    def filter(self, record) -> bool:
        try:
            formatted = record.getMessage()
            record.msg = redact_secrets(formatted)
            record.args = None
        except Exception:
            return True
        return True


def install_redacting_logging() -> None:
    """Attach a redacting filter to the root logger and existing handlers."""
    redactor = RedactingFilter()
    root = logging.getLogger()
    root.addFilter(redactor)
    for handler in root.handlers:
        handler.addFilter(redactor)
    logging.getLogger("music-dl").addFilter(redactor)
