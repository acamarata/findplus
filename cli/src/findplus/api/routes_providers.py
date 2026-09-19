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


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api")

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
                p_name, p_display = name, name
            else:
                p_name, p_display = p.name, p.display_name
            result.append(
                {
                    "name": p_name,
                    "display_name": p_display,
                    "available": avail,
                    "reason": reason,
                    "authenticated": authed,
                    "account": auth_info.get("account"),
                    "limits": "standard polling limits apply",
                }
            )
        return result

    return router
