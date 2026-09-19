"""Provider status route: which LocationProviders are installed, available, authenticated.

Purpose    : Let the dashboard and CLI show provider health without each one
             re-implementing the availability/auth probing dance.
Inputs     : none (reads the process-wide provider registry).
Outputs    : one summary object per installed provider.
Constraints: never raises on a broken provider — a provider whose is_available()
             or is_authenticated() throws is reported as unavailable, not a 500.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from findplus.providers.base import available_providers, get_provider

#: Used for a provider that declares no `limits` attribute of its own.
_DEFAULT_LIMITS = "standard polling limits apply"


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["providers"])

    @router.get("/providers")
    def list_providers() -> list[dict[str, Any]]:
        result = []
        for name in available_providers():
            try:
                p = get_provider(name)
                avail, reason = p.is_available()
                authed = p.is_authenticated() if avail else False
                auth_info = p.describe_auth() if authed else {}
            except Exception as exc:
                avail, reason, authed, auth_info = False, str(exc), False, {}
                p_name, p_display, limits = name, name, _DEFAULT_LIMITS
            else:
                p_name, p_display = p.name, p.display_name
                # Optional attribute: a provider that does not declare its own
                # limits (including a third-party one) keeps the generic text.
                limits = getattr(p, "limits", _DEFAULT_LIMITS)
            result.append(
                {
                    "name": p_name,
                    "display_name": p_display,
                    "available": avail,
                    "reason": reason,
                    "authenticated": authed,
                    "account": auth_info.get("account"),
                    "limits": limits,
                }
            )
        return result

    return router
