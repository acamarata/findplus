"""Apple Find My sign-in as a background job, for the dashboard rather than a TTY.

Purpose    : the same findmy calls `auth.py:sign_in_interactive()` makes
             (`login`, `get_2fa_methods`, a method's `request`/`submit`),
             driven by two HTTP requests instead of `click.prompt`, which
             blocks on real stdin and cannot run in a thread spawned from a
             request.
Inputs     : a `Settings`, an Apple ID and password, then a 2FA code.
Outputs    : `start_apple_auth()` -> job id; `submit_apple_code()` -> the Apple
             ID; `get_apple_auth_progress()` -> `{"state", "message"}` or None.
             States: signing_in -> needs_2fa -> done, or failed.
Constraints: `make_account()`/`save_account()` are reused from auth.py
             unmodified; only the prompting is not. The password is a local of
             the thread that calls `login()` and is never written to the job
             dict, a log line or a response body (specs/auth-ui.md §3, §8).
             FindMy.py keeps it inside the live account object until the 2FA
             code is accepted (it re-authenticates with it), so the job's
             AppleSession is closed and dropped on every terminal state and on
             sweep. Structurally parallel to google_findhub/browser.py but
             shares no code with it.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from findplus.providers.apple_findmy.auth import make_account, save_account
from findplus.providers.apple_findmy.session import AppleSession, prepare_anisette

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
MSG_NEEDS_SMS = "Enter the code Apple sent by text message to {number}."

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
            _close_quietly(_jobs.pop(job_id).get("session"))


def _close_quietly(session: AppleSession | None) -> None:
    """Close a job's account session; a failure here is never the user's problem."""
    if session is not None:
        session.close()


def _set_progress(job_id: str, state: str, message: str) -> None:
    """Record a state transition. Silently ignores an already-swept job.

    A terminal state releases the live account (and the password FindMy.py
    keeps inside it) at once rather than when the job is swept.
    """
    session = None
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["state"] = state
        job["message"] = message
        job["last_progress_monotonic"] = time.monotonic()
        if state in _TERMINAL:
            job["finished_monotonic"] = time.monotonic()
            session, job["session"], job["method"] = job.get("session"), None, None
    _close_quietly(session)


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
            "session": None,
            "finished_monotonic": None,
            "last_progress_monotonic": time.monotonic(),
        }

    threading.Thread(
        target=_run_apple_auth, args=(job_id, settings, apple_id, password), daemon=True
    ).start()
    return job_id


def _pick_method(methods: list) -> Any:
    """The trusted device when Apple offers one (the CLI's default), else SMS."""
    for method in methods:
        if getattr(method, "phone_number", None) is None:
            return method
    return methods[0]


def _needs_2fa_message(method: Any) -> str:
    number = getattr(method, "phone_number", None)
    return MSG_NEEDS_SMS.format(number=number) if number else MSG_NEEDS_2FA


def _run_apple_auth(job_id: str, settings: Any, apple_id: str, password: str) -> None:
    """Thread body: log in, ask for a 2FA code if Apple wants one, record it."""
    import findmy

    session = None
    try:
        session = AppleSession(make_account(settings))
        prepare_anisette(session, settings)
        state = session.run(session.account.login(apple_id, password))
        if state == findmy.LoginState.REQUIRE_2FA:
            methods = list(session.run(session.account.get_2fa_methods()))
            if not methods:
                raise RuntimeError("Apple asked for a second factor but offered no usable method.")
            method = _pick_method(methods)
            session.run(method.request())
            with _lock:
                job = _jobs.get(job_id)
                if job is not None:
                    job["method"], job["session"] = method, session
            if job is None:  # swept while Apple was answering: nobody will submit
                _close_quietly(session)
                return
            _set_progress(job_id, "needs_2fa", _needs_2fa_message(method))
            return
        if state != findmy.LoginState.LOGGED_IN:
            raise RuntimeError(f"Apple sign-in did not finish (state {state}).")
        save_account(session.account, settings)
    except Exception as exc:
        _close_quietly(session)
        _set_progress(job_id, "failed", str(exc)[:300])
    else:
        _close_quietly(session)
        _set_progress(job_id, "done", f"Authenticated as {apple_id}.")


def submit_apple_code(job_id: str, code: str, settings: Any) -> str:
    """Finish a needs_2fa job with the code from the trusted device or SMS.

    A refused code leaves the job at `needs_2fa` so the dashboard can re-prompt
    without starting the whole sign-in again.
    """
    import findmy

    with _lock:
        _sweep_expired_jobs()
        job = _jobs.get(job_id)
        if job is None:
            raise UnknownAppleJobError(job_id)
        if job["state"] != "needs_2fa":
            raise InvalidAppleCodeError("job is not awaiting a 2FA code")

        job["attempts"] = job.get("attempts", 0) + 1
        if job["attempts"] > 5:
            job["state"] = "failed"
            job["message"] = "Too many invalid code attempts. Please sign in again."
            job["last_progress_monotonic"] = time.monotonic()
            job["finished_monotonic"] = time.monotonic()
            _close_quietly(job.get("session"))
            job["session"], job["method"] = None, None
            raise InvalidAppleCodeError("Too many invalid code attempts")

        method, session, apple_id = job["method"], job["session"], job["apple_id"]

    try:
        state = session.run(method.submit(code))
    except Exception as exc:
        raise InvalidAppleCodeError(str(exc)) from exc
    if state != findmy.LoginState.LOGGED_IN:
        raise InvalidAppleCodeError(f"Apple did not accept the code (state {state}).")

    save_account(session.account, settings)

    _set_progress(job_id, "done", f"Authenticated as {apple_id}.")
    return apple_id


def get_apple_auth_progress(job_id: str) -> dict[str, Any] | None:
    """`{"state", "message"}`, or None for an unknown or expired job id.

    Deliberately narrow: the job dict also holds a live AppleSession and 2FA
    method object, neither of which belongs in a response body.
    """
    with _lock:
        _sweep_expired_jobs()
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {"state": job["state"], "message": job["message"]}
