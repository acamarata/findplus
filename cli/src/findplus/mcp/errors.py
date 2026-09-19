"""The MCP error shape pinned by specs/mcp-tools.md, built from daemon replies.

Purpose    : One place that turns a daemon HTTP status (or a transport failure)
             into `{"error": {"code", "message", "hint"}}`, so every tool
             reports the same five codes instead of leaking FastAPI's raw
             `{"detail": ...}` bodies to MCP clients.
Inputs     : A status code and the response body text.
Outputs    : An error dict, or None when the response is a success the caller
             should parse itself.
Constraints: Every call returns a FRESH dict. Returning a shared module-level
             constant let `_with_notice` mutate it process-wide.
"""

from __future__ import annotations

import json
from typing import Any

#: Daemon status -> (code, hint). Anything else non-2xx becomes "upstream".
_BY_STATUS: dict[int, tuple[str, str]] = {
    400: ("validation", "check the argument values"),
    401: ("locked", "call unlock(pin)"),
    404: ("not_found", "list the entity first to get a valid id"),
    409: ("validation", "an entity with that name already exists"),
    422: ("validation", "check the argument types and ranges"),
    429: ("upstream", "the daemon is rate limiting; wait and retry"),
}


def error(code: str, message: str, hint: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "hint": hint}}


def locked() -> dict[str, Any]:
    return error("locked", "Find+ is locked", "call unlock(pin)")


def daemon_down() -> dict[str, Any]:
    return error("daemon_down", "daemon not running", "run findplus start")


def _detail(body: str) -> str:
    """The daemon's `detail` field as a sentence, or the raw body if absent."""
    try:
        parsed = json.loads(body)
    except ValueError:
        return body.strip()[:200]
    detail = parsed.get("detail") if isinstance(parsed, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):  # 422 validation list
        return "; ".join(
            f"{'.'.join(str(p) for p in item.get('loc', []))}: {item.get('msg', '')}"
            for item in detail
            if isinstance(item, dict)
        )[:400]
    return body.strip()[:200]


def from_status(status: int, body: str) -> dict[str, Any] | None:
    """Map a daemon response to the documented error, or None if it succeeded."""
    if 200 <= status < 300:
        return None
    if status == 401:
        return locked()
    code, hint = _BY_STATUS.get(status, ("upstream", "check the daemon logs"))
    return error(code, _detail(body) or f"daemon returned HTTP {status}", hint)
