"""Unlock a Google account's encrypted locations, in Find+'s own Chrome window.

Purpose    : HTTP over providers/google_findhub/unlock.py, so the "Unlock
             encrypted locations" step needs no terminal. Google encrypts Find
             Hub locations end to end; the key is released only to a browser
             page that has passed the Android screen-lock check, so Find+ opens
             a Chrome window of its own for it and pastes nothing.
Inputs     : No body for /start; a `job_id` query for /progress; `{job_id}` for
             /cancel.
Outputs    : 202 {job_id}; 200 {state, message}; 404 typed errors; 409 flat body.
Constraints: /start and /cancel carry routes_auth's Origin/Sec-Fetch-Site guard,
             like every other sign-in POST. No browser or key handling here.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from findplus.config import get_settings
from findplus.providers.google_findhub.unlock import (
    MSG_CANCELLED,
    GoogleUnlockAlreadyRunningError,
    cancel_google_unlock,
    get_google_unlock_progress,
    start_google_unlock,
)


class GoogleUnlockCancelBody(BaseModel):
    job_id: str


def _require_job_id(job_id: str | None) -> str:
    if job_id is None:
        raise HTTPException(status_code=422, detail="job_id is required")
    return job_id


def google_unlock_start(request: Request) -> dict[str, Any]:
    from findplus.api.routes_auth import _require_origin_signal

    _require_origin_signal(request)
    try:
        job_id = start_google_unlock(get_settings())
    except GoogleUnlockAlreadyRunningError as exc:
        return JSONResponse(
            status_code=409,
            content={"detail": "A Google unlock is already in progress.", "job_id": exc.job_id},
        )
    return {"job_id": job_id}


def google_unlock_progress(job_id: str | None = Query(default=None)) -> dict[str, Any]:
    progress = get_google_unlock_progress(_require_job_id(job_id))
    if progress is None:
        raise HTTPException(status_code=404, detail="unknown or expired job_id")
    return progress


def google_unlock_cancel(body: GoogleUnlockCancelBody, request: Request) -> dict[str, Any]:
    from findplus.api.routes_auth import _require_origin_signal

    _require_origin_signal(request)
    if not cancel_google_unlock(body.job_id):
        raise HTTPException(status_code=404, detail="unknown or already-finished job_id")
    return {"state": "failed", "message": MSG_CANCELLED}
