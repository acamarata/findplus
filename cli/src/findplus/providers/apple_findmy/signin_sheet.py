"""Apple sign-in as one sheet: a clean state machine over web_auth.py's job.

Purpose    : The dashboard's Apple card opens a sheet (spec in-app-login.md §5):
             Apple ID and password, a one-time "preparing" step on first run,
             then a code from a trusted device, or by text message when the
             person asks. This module reads web_auth's job and describes it in
             the sheet's own words, adds Cancel and "Text me instead", and keeps
             the older start/code/progress routes working unchanged.
Inputs     : a job id (or none: the latest job); a phone id for SMS.
Outputs    : `sheet_status()` -> `{job_id, phase, message, account,
             second_factor, attempts_left}`; `cancel()`; `text_me()`.
             Phases: idle, preparing, signing_in, needs_code, success, error,
             cancelled.
Constraints: Never returns the password, a session or a method object. Phone
             numbers are the masked form Apple itself returns. No findmy import
             at module level (the Apple extra is optional).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import web_auth
from .auth import anisette_libs_path

MSG_CODE_DEVICE = "Enter the 6-digit code shown on your iPhone, iPad or Mac."
MSG_PREPARING = "Preparing Apple sign-in (one-time download, a few MB)..."
MSG_CANCELLED = "Cancelled. Nothing changed."
MSG_SUCCESS = "Connected as {account}."
_MAX_ATTEMPTS = 5

_PHASE_OF = {"signing_in": "signing_in", "needs_2fa": "needs_code", "done": "success"}


class SheetError(Exception):
    """A refused sheet action. `str(exc)` is plain words; `status` is HTTP-ready."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _job(job_id: str | None) -> tuple[str, dict[str, Any]] | None:
    """(id, job) for `job_id`, or for the newest job when None. Caller holds the lock."""
    web_auth._sweep_expired_jobs()
    if job_id is None:
        if not web_auth._jobs:
            return None
        job_id = next(reversed(web_auth._jobs))
    job = web_auth._jobs.get(job_id)
    return (job_id, job) if job is not None else None


def _first_run(settings: Any) -> bool:
    """True when local anisette still has to download its libraries."""
    if getattr(settings, "apple_anisette_url", None):
        return False
    return not Path(anisette_libs_path(settings)).exists()


def _second_factor(job: dict[str, Any]) -> dict[str, Any] | None:
    method = job.get("method")
    if method is None:
        return None
    sms = [m for m in job.get("methods") or [] if getattr(m, "phone_number", None)]
    phone = getattr(method, "phone_number", None)
    return {
        "kind": "sms" if phone else "trusted_device",
        "phone": phone,
        "can_text": bool(sms),
        "sms_options": [
            {"id": getattr(m, "phone_number_id", i), "phone": m.phone_number}
            for i, m in enumerate(sms)
        ],
    }


def _phase(job: dict[str, Any], settings: Any) -> tuple[str, str]:
    if job.get("cancelled"):
        return "cancelled", MSG_CANCELLED
    state = job["state"]
    if state == "failed":
        return "error", job["message"]
    if state == "signing_in" and _first_run(settings):
        return "preparing", MSG_PREPARING
    if state == "needs_2fa":
        phone = getattr(job.get("method"), "phone_number", None)
        return "needs_code", job["message"] if phone else MSG_CODE_DEVICE
    if state == "done":
        return "success", MSG_SUCCESS.format(account=job["apple_id"])
    return _PHASE_OF.get(state, "signing_in"), job["message"]


def _idle() -> dict[str, Any]:
    return {
        "job_id": None,
        "phase": "idle",
        "message": "",
        "account": None,
        "second_factor": None,
        "attempts_left": _MAX_ATTEMPTS,
    }


def sheet_status(settings: Any, job_id: str | None = None) -> dict[str, Any]:
    """The sheet's view of a job (the newest when `job_id` is None)."""
    with web_auth._lock:
        found = _job(job_id)
        if found is None:
            if job_id is not None:
                raise SheetError(404, "unknown or expired job_id")
            return _idle()
        found_id, job = found
        phase, message = _phase(job, settings)
        return {
            "job_id": found_id,
            "phase": phase,
            "message": message,
            "account": job["apple_id"] if phase == "success" else None,
            "second_factor": _second_factor(job) if phase == "needs_code" else None,
            "attempts_left": max(0, _MAX_ATTEMPTS - int(job.get("attempts", 0))),
        }


def cancel(job_id: str) -> bool:
    """Stop a running or code-waiting job. False when it is unknown or already over."""
    with web_auth._lock:
        found = _job(job_id)
        if found is None or found[1]["state"] in web_auth._TERMINAL:
            return False
        job = found[1]
        job["cancelled"] = True
        job["state"], job["message"] = "failed", MSG_CANCELLED
        job["finished_monotonic"] = job["last_progress_monotonic"] = time.monotonic()
        session, job["session"], job["method"], job["methods"] = job.get("session"), None, None, []
    web_auth._close_quietly(session)
    return True


def text_me(job_id: str, phone_id: object = None) -> dict[str, Any]:
    """Ask Apple to text the code instead ("Text me instead"); the first number unless chosen."""
    with web_auth._lock:
        found = _job(job_id)
        if found is None:
            raise SheetError(404, "unknown or expired job_id")
        job = found[1]
        if job["state"] != "needs_2fa" or job.get("cancelled"):
            raise SheetError(409, "This sign-in is not waiting for a code.")
        sms = [m for m in job.get("methods") or [] if getattr(m, "phone_number", None)]
        chosen = [m for m in sms if phone_id is None or m.phone_number_id == phone_id]
        if not chosen:
            raise SheetError(422, "Apple did not offer a text message to that number.")
        method, session = chosen[0], job["session"]
    try:
        session.run(method.request())
    except Exception:
        raise SheetError(502, "Apple did not send the text. Try again in a moment.") from None
    with web_auth._lock:
        job["method"] = method
        job["message"] = web_auth.MSG_NEEDS_SMS.format(number=method.phone_number)
        job["last_progress_monotonic"] = time.monotonic()
    return {"phase": "needs_code", "message": job["message"], "phone": method.phone_number}
