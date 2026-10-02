"""The Apple sign-in sheet's extra routes: status, cancel, and "Text me instead".

Purpose    : Make Apple sign-in one clean state machine for the dashboard sheet
             (spec in-app-login.md §5): start (POST /api/auth/apple/start) ->
             status -> code (POST /api/auth/apple/code), with cancel and SMS at
             any point. The older start/code/progress routes are unchanged.
Inputs     : `job_id` (query or body); an optional `phone_id` for SMS.
Outputs    : providers/apple_findmy/signin_sheet.py's dicts; `{detail}` errors.
Constraints: Cancel and text carry routes_auth's Origin/Sec-Fetch-Site guard like
             every sign-in POST; all three are behind the app lock. Nothing here
             ever returns the password or a session object.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel

from findplus.config import get_settings
from findplus.providers.apple_findmy import signin_sheet


class AppleJobBody(BaseModel):
    job_id: str = ""


class AppleTextBody(BaseModel):
    job_id: str = ""
    phone_id: int | None = None


def apple_status(job_id: str | None = Query(default=None)) -> dict[str, Any]:
    """The sheet's phase for one job, or for the newest job when none is named."""
    from findplus.providers.apple_findmy import is_available

    try:
        status = signin_sheet.sheet_status(get_settings(), job_id)
    except signin_sheet.SheetError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    available, hint = is_available()
    return {**status, "available": available, "install_hint": None if available else hint}


def apple_cancel(body: AppleJobBody, request: Request) -> dict[str, Any]:
    """Cancel an Apple sign-in that is running or waiting for a code; nothing is saved."""
    from findplus.api.routes_auth import _require_origin_signal

    _require_origin_signal(request)
    if not signin_sheet.cancel(body.job_id):
        raise HTTPException(status_code=404, detail="unknown or already-finished job_id")
    return {"phase": "cancelled", "message": signin_sheet.MSG_CANCELLED}


def apple_text(body: AppleTextBody, request: Request) -> dict[str, Any]:
    """Text me instead: Apple sends the code by text message to a number it offered."""
    from findplus.api.routes_auth import _require_apple_provider, _require_origin_signal

    _require_origin_signal(request)
    _require_apple_provider()
    try:
        return signin_sheet.text_me(body.job_id, body.phone_id)
    except signin_sheet.SheetError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


def register(router) -> None:
    """Register on routes_auth's "/api" router."""
    router.add_api_route("/auth/apple/status", apple_status, methods=["GET"])
    router.add_api_route("/auth/apple/cancel", apple_cancel, methods=["POST"])
    router.add_api_route("/auth/apple/text", apple_text, methods=["POST"])
