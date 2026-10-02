"""Decide whether Google blocked the in-app sign-in window, from host, path and a title class.

Purpose    : The desktop shell reports where its sign-in window landed so the
             daemon can tell "Google refused this window" apart from an ordinary
             page (spec in-app-login.md §3.4) and steer the card to the next
             rung of the fallback ladder. The shell sends ONLY a host, a path
             (no query, no fragment) and a coarse title class; never page text,
             never a URL with parameters, never a cookie.
Inputs     : `classify(host, path, title_class)`.
Outputs    : `Verdict(blocked, reason)`; `clean_report()` validates the input.
Constraints: Pure: no I/O, no HTTP. The rejection paths are a best guess until
             the owner's spike records the real ones (spec §3.4, [Guessing]).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Hosts the sign-in window may load (spec §9.1). The shell enforces this list
#: with its own copy; the daemon uses it to classify a report. `accounts.google.<cc>`
#: is matched by ALLOWED_HOST_PATTERN.
ALLOWED_HOSTS = frozenset(
    {
        "accounts.google.com",
        "accounts.youtube.com",
        "myaccount.google.com",
        "www.google.com",
        "ssl.gstatic.com",
    }
)
ALLOWED_HOST_PATTERN = re.compile(r"^accounts\.google\.(?:[a-z]{2,3}|co\.[a-z]{2}|com\.[a-z]{2})$")

#: Coarse classes the shell may derive from the page title. Anything else is refused.
TITLE_CLASSES = frozenset({"normal", "couldnt_sign_in", "browser_not_secure", "unknown"})

_REJECTED_PATHS = ("/signin/rejected", "/v3/signin/rejected")
_HOST_RE = re.compile(r"^[a-z0-9.-]{1,253}$")
_MAX_PATH = 512


class ReportError(ValueError):
    """The shell's report is malformed (or carries more than host and path)."""


@dataclass(frozen=True)
class Verdict:
    blocked: bool
    reason: str | None


def is_allowed_host(host: str) -> bool:
    """True for a host the sign-in window may show (https only, enforced by the shell)."""
    return host in ALLOWED_HOSTS or bool(ALLOWED_HOST_PATTERN.match(host))


def clean_report(host: object, path: object, title_class: object) -> tuple[str, str, str]:
    """Validate a report. Refuses a query, a fragment, or anything that is not a short string."""
    if not isinstance(host, str) or not _HOST_RE.match(host.lower()):
        raise ReportError("host must be a bare host name")
    if not isinstance(path, str) or not path.startswith("/") or len(path) > _MAX_PATH:
        raise ReportError("path must start with / and be at most 512 characters")
    if "?" in path or "#" in path:
        raise ReportError("path must not carry a query or a fragment")
    title = title_class if isinstance(title_class, str) and title_class else "unknown"
    if title not in TITLE_CLASSES:
        raise ReportError("title_class is not one of the known classes")
    return host.lower(), path, title


def classify(host: str, path: str, title_class: str = "unknown") -> Verdict:
    """Blocked or not, and why, for one validated report."""
    lowered = path.lower()
    if "disallowed_useragent" in lowered:
        return Verdict(True, "disallowed_useragent")
    if host.startswith("accounts.google.") and lowered.startswith(_REJECTED_PATHS):
        return Verdict(True, "rejected_page")
    if title_class == "browser_not_secure":
        return Verdict(True, "rejected_page")
    if not is_allowed_host(host):
        # Workspace SSO to a third-party identity provider, or a stray link:
        # the window refuses it, so the person needs their own Chrome (Q3).
        return Verdict(True, "outside_google")
    return Verdict(False, None)
