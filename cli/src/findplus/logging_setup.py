"""Structured, rotating logging with secret redaction.

Purpose : Configure structlog + stdlib logging for CLI, API and daemon.
Inputs  : Settings (level, rotation limits, log path).
Outputs : Console renderer for interactive use, rotating file handler for the daemon.
Constraints:
    - NEVER logs passwords, cookies, access/AAS/ADM tokens or private keys.
      `_redact` scrubs known-sensitive keys and long opaque blobs defensively.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from typing import Any

import structlog

from findplus.config import Settings

#: Event-dict keys whose values must never reach a log sink.
_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "aas_token",
    "adm_token",
    "oauth_token",
    "access_token",
    "cookie",
    "cookies",
    "authorization",
    "private_key",
    "owner_key",
    "identity_key",
    "eik",
    "credentials",
    "fcm_credentials",
    "android_id",
    "api_key",
    "bot_token",
    "chat_id",
    "webhook_url",
    # "secret" is already a member above (ruff B033 forbids a literal duplicate).
}

#: Defensive catch for tokens pasted into free-text messages.
_TOKEN_PATTERN = re.compile(
    r"\b(?:aas_et|ya29|oauth2_4|AIzaSy)[A-Za-z0-9._\-/]{10,}|\d{8,10}:[A-Za-z0-9_-]{35}\b"
)


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "<redacted>"
        elif isinstance(event_dict[key], str):
            event_dict[key] = _TOKEN_PATTERN.sub("<redacted>", event_dict[key])
    return event_dict


def configure_logging(settings: Settings, *, to_file: bool = False, console: bool = True) -> None:
    """Install logging handlers. Idempotent."""
    settings.ensure_dirs()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    fmt = logging.Formatter("%(message)s")
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        root.addHandler(stream)
    if to_file:
        rotating = logging.handlers.RotatingFileHandler(
            settings.log_file,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
        rotating.setFormatter(fmt)
        root.addHandler(rotating)

    # Third-party chatter we never want at INFO.
    for noisy in ("urllib3", "selenium", "asyncio", "httpx", "httpcore", "aiohttp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=console and sys.stderr.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "findplus") -> Any:
    return structlog.get_logger(name)
