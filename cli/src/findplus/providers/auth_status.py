"""One provider sign-in summary, read by both `GET /api/auth/status` and the CLI.

Purpose    : specs/auth-ui.md §5 requires `findplus auth --status` and the
             dashboard to agree. They agree by calling the same function.
Inputs     : none (reads the process-wide provider registry).
Outputs    : `{"providers": [{id, signed_in, account, method, last_checked,
             needs}]}`. `needs` names a missing prerequisite ("chrome",
             "apple_extra") so the wizard can show it without a second call.
Constraints: never raises on a broken provider — one whose is_available() or
             is_authenticated() throws is reported as signed out, not a 500.
             Mirrors api/routes_providers.py's aggregation, which has the same
             rule for the same reason.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from findplus.providers.base import available_providers, get_provider

_GOOGLE = "google-find-hub"
_APPLE = "apple-find-my"


def _needs(name: str) -> list[str]:
    """Prerequisites this provider is missing right now, cheapest probe first."""
    missing: list[str] = []
    if name == _GOOGLE:
        from findplus.cli.doctor import check_chrome

        if not check_chrome().passed:
            missing.append("chrome")
    elif name == _APPLE:
        from findplus.providers.apple_findmy import is_available

        if not is_available()[0]:
            missing.append("apple_extra")
    return missing


def build_auth_status() -> dict[str, Any]:
    """Per-provider sign-in state for the dashboard, the wizard and the CLI."""
    providers: list[dict[str, Any]] = []
    for name in available_providers():
        try:
            provider = get_provider(name)
            avail, _reason = provider.is_available()
            signed_in = provider.is_authenticated() if avail else False
            info = provider.describe_auth() if signed_in else {}
        except Exception:
            signed_in, info = False, {}
        try:
            needs = _needs(name)
        except Exception:
            needs = []
        providers.append(
            {
                "id": name,
                "signed_in": signed_in,
                "account": info.get("account"),
                "method": "chrome" if name == _GOOGLE else "apple-2fa",
                "last_checked": datetime.now(UTC).isoformat(),
                "needs": needs,
            }
        )
    return {"providers": providers}
