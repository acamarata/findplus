"""Strip credentials out of text that is about to be stored or shown.

Purpose    : CF-14 put `alert_deliveries.error` on the dashboard and on
             GET /api/alerts/deliveries, so whatever a channel put in that
             column is now displayed. httpx's status errors embed the request
             URL, and several webhook services (CallMeBot among them) carry
             their key in the query string -- so an ordinary 401 from one of
             them wrote the key into the DB in clear text. logging_setup's
             redaction covers logs only.
Inputs     : Any error string, from a channel result or an exception.
Outputs    : The same string with known token shapes, URL userinfo and
             sensitive query-string values replaced by <redacted>.
Constraints: Best effort, never raises, and never lengthens the string past
             its caller's slice. It is a second line of defence: the first is
             not putting secrets in the message.
"""

from __future__ import annotations

import re

#: Query-string keys whose value is a credential wherever it appears.
_SECRET_PARAMS = frozenset(
    {
        "apikey",
        "api_key",
        "access_token",
        "auth",
        "key",
        "password",
        "pass",
        "secret",
        "sig",
        "signature",
        "token",
    }
)

#: Token shapes worth catching even outside a URL (kept in step with
#: logging_setup._TOKEN_PATTERN, which guards the log stream).
_TOKEN_PATTERN = re.compile(
    r"\b(?:aas_et|ya29|oauth2_4|AIzaSy)[A-Za-z0-9._\-/]{10,}|\d{8,10}:[A-Za-z0-9_-]{35}\b"
)

#: `key=value` inside a query string or a form body.
_PARAM_PATTERN = re.compile(r"([?&;]\s*)([A-Za-z0-9_.\-]+)(=)([^&\s\"'#]*)")

#: `scheme://user:password@host`
_USERINFO_PATTERN = re.compile(r"(://)([^/\s:@]+):([^/\s@]+)(@)")

REDACTED = "<redacted>"


def _param(match: re.Match[str]) -> str:
    lead, name, eq, value = match.groups()
    if name.lower() in _SECRET_PARAMS and value:
        return f"{lead}{name}{eq}{REDACTED}"
    return match.group(0)


def redact_text(text: str | None) -> str | None:
    """Return `text` with credentials masked. None and "" pass through."""
    if not text:
        return text
    out = _TOKEN_PATTERN.sub(REDACTED, text)
    out = _USERINFO_PATTERN.sub(rf"\1\2:{REDACTED}\4", out)
    return _PARAM_PATTERN.sub(_param, out)
