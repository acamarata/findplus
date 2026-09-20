"""Apple Find My sign-in as a background job, for the dashboard rather than a TTY.

Purpose    : the same three findmy.py calls `auth.py:sign_in_interactive()`
             makes (`login`, `requires_2fa`, a 2FA method), driven by two HTTP
             requests instead of `click.prompt`, which blocks on real stdin and
             cannot run in a thread spawned from a request.
Inputs     : a `Settings`, an Apple ID and password, then a 2FA code.
Outputs    : `start_apple_auth()` -> job id; `submit_apple_code()` -> the Apple
             ID; `get_apple_auth_progress()` -> `{"state", "message"}` or None.
             States: signing_in -> needs_2fa -> done, or failed.
Constraints: `make_account()`/`save_account()` are reused from auth.py
             unmodified — only the prompting is not. The password is a local of
             the thread that calls `login()` and is never written to the job
             dict, a log line or a response body (specs/auth-ui.md §3, §8).
             Structurally parallel to google_findhub/browser.py (lock, `_jobs`,
             sweep, `_set_progress`) but shares no code with it: no Chrome, no
             selenium, a different state machine.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from findplus.providers.apple_findmy.auth import make_account, save_account

__all__ = [
    "AppleAuthAlreadyRunningError",
    "InvalidAppleCodeError",
    "UnknownAppleJobError",
    "get_apple_auth_progress",
    "start_apple_auth",
    "submit_apple_code",
]

MSG_SIGNING_IN = "Signing in..."
MSG_NEEDS_2FA = "Enter the code from your trusted device."

_JOB_TTL_SECONDS = 600

#: How long a job may sit without a state transition before it counts as
#: abandoned and is swept, so one unfinished sign-in cannot block every later
#: one for the life of the daemon. Generous: reading a code off a trusted
#: device is human-paced.
_STALLED_SECONDS = 600

_TERMINAL = ("done", "failed")

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


class AppleAuthAlreadyRunningError(Exception):
    """One Apple sign-in is already in flight; its job id is on the exception."""

    def __init__(self, job_id: str) -> None:
        super().__init__("An Apple sign-in is already in progress.")
        self.job_id = job_id


class UnknownAppleJobError(Exception):
    """No job with that id: never started, or swept after the TTL."""


class InvalidAppleCodeError(Exception):
    """The submitted 2FA code was refused, or the job is not awaiting one."""


def _sweep_expired_jobs() -> None:
    """Drop finished jobs past the TTL, and stalled ones. Caller holds `_lock`.

    A job that never reaches a terminal state has no `finished_monotonic`, so a
    finished-only sweep keeps it forever — and `start_apple_auth()` refuses
    while ANY job is non-terminal. The reachable case is an abandoned 2FA
    prompt: a user who mistypes their Apple ID, gets to `needs_2fa` and closes
    the dialog would otherwise be locked out of Apple sign-in until the daemon
    restarts. `last_progress_monotonic` measures time since the last observed
    transition, so a live flow (signing in, or a code being typed) is never
    swept out from under the user.
    """
    now = time.monotonic()
    for job_id, job in list(_jobs.items()):
        finished = job.get("finished_monotonic")
        if finished is not None:
            if now - finished > _JOB_TTL_SECONDS:
                del _jobs[job_id]
        elif now - job.get("last_progress_monotonic", now) > _STALLED_SECONDS:
            del _jobs[job_id]


def _set_progress(job_id: str, state: str, message: str) -> None:
    """Record a state transition. Silently ignores an already-swept job."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["state"] = state
        job["message"] = message
        job["last_progress_monotonic"] = time.monotonic()
        if state in _TERMINAL:
            job["finished_monotonic"] = time.monotonic()


def start_apple_auth(settings: Any, apple_id: str, password: str) -> str:
    """Start a sign-in and return its job id.

    Raises AppleAuthAlreadyRunningError when another job is still running or
    still waiting for its 2FA code.
    """
    with _lock:
        _sweep_expired_jobs()
        for existing_id, job in _jobs.items():
            if job["state"] not in _TERMINAL:
                raise AppleAuthAlreadyRunningError(existing_id)
        job_id = uuid.uuid4().hex
        _jobs[job_id] = {
            "state": "signing_in",
            "message": MSG_SIGNING_IN,
            # The Apple ID is an identifier and is echoed back on success. The
            # password is not here, and never will be: it stays an argument of
            # the thread below for the length of one login() call.
            "apple_id": apple_id,
            "method": None,
            "account": None,
            "finished_monotonic": None,
            "last_progress_monotonic": time.monotonic(),
        }

    threading.Thread(
        target=_run_apple_auth, args=(job_id, settings, apple_id, password), daemon=True
    ).start()
    return job_id


def _run_apple_auth(job_id: str, settings: Any, apple_id: str, password: str) -> None:
    """Thread body: log in, ask for a 2FA method if Apple wants one, record it."""
    try:
        account = make_account(settings)
        account.login(apple_id, password)
        if account.requires_2fa():
            # methods[0] is the trusted device, the same default the CLI's
            # choice "1" picks. The user still reads the code off that device,
            # so auto-selecting simplifies the UI without weakening anything.
            method = account.get_2fa_methods()[0]
            method.request()
            with _lock:
                job = _jobs.get(job_id)
                if job is not None:
                    job["method"] = method
                    job["account"] = account
            _set_progress(job_id, "needs_2fa", MSG_NEEDS_2FA)
            return
        save_account(account, settings)
    except Exception as exc:
        _set_progress(job_id, "failed", str(exc)[:200])
    else:
        _set_progress(job_id, "done", f"Authenticated as {apple_id}.")


def submit_apple_code(job_id: str, code: str, settings: Any) -> str:
    """Finish a needs_2fa job with the code from the trusted device.

    A refused code leaves the job at `needs_2fa` so the dashboard can re-prompt
    without starting the whole sign-in again.
    """
    with _lock:
        _sweep_expired_jobs()
        job = _jobs.get(job_id)
        if job is None:
            raise UnknownAppleJobError(job_id)
        if job["state"] != "needs_2fa":
            raise InvalidAppleCodeError("job is not awaiting a 2FA code")
        method, account, apple_id = job["method"], job["account"], job["apple_id"]

    try:
        method.submit(code)
        save_account(account, settings)
    except Exception as exc:
        raise InvalidAppleCodeError(str(exc)) from exc

    _set_progress(job_id, "done", f"Authenticated as {apple_id}.")
    return apple_id


def get_apple_auth_progress(job_id: str) -> dict[str, Any] | None:
    """`{"state", "message"}`, or None for an unknown or expired job id.

    Deliberately narrow: the job dict also holds a live findmy account and 2FA
    method object, neither of which belongs in a response body.
    """
    with _lock:
        _sweep_expired_jobs()
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {"state": job["state"], "message": job["message"]}
