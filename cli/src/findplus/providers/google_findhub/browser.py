"""Google Find Hub sign-in driven from the dashboard, in an isolated Chrome.

Purpose    : Run the vendored GoogleFindMyTools Chrome sign-in from a background
             thread and expose a job-id-keyed progress state machine the API
             (api/routes_auth.py) polls, so the browser flow needs no terminal.
Inputs     : a `Settings` (for `chrome_profile_dir`), and a job id minted here.
Outputs    : `start_google_auth()` -> job id; `get_google_auth_progress()` ->
             `{"state", "message"}` or None for an unknown/expired job.
Constraints: `cli/vendor/GoogleFindMyTools/` is never edited (PRI hard rule 8).
             Two vendor attributes are rebound at runtime instead, the same
             surgical pattern `google_findhub/bootstrap.py` uses on
             `Auth.token_cache._get_secrets_file`:

             - `chrome_driver.create_driver`, whose original runs
               `pkill -f chrome` and then opens the user's DEFAULT Chrome
               profile. Killing the user's browser was only ever a workaround
               for not passing a profile directory, and
               `undetected_chromedriver.Chrome` takes `user_data_dir` directly,
               so the replacement points Chrome at `~/.findplus/chrome-profile`
               (0700) and kills nothing.
             - `Auth.auth_flow.input`, a blocking stdin read no daemon thread
               can answer.

             Import order is the whole trick: `Auth/auth_flow.py:7` does
             `from chrome_driver import create_driver`, which binds the name
             once, at that module's FIRST import. `chrome_driver` must
             therefore be imported and patched BEFORE `Auth.auth_flow` is
             imported anywhere in the process.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

from findplus.honesty import CHROME_REQUIRED as MSG_CHROME_MISSING

from .bootstrap import ensure_gfmt_importable

__all__ = [
    "MSG_CHROME_MISSING",
    "ChromeNotFoundError",
    "GoogleAuthAlreadyRunningError",
    "get_google_auth_progress",
    "start_google_auth",
]

MSG_LAUNCHING = "Starting Chrome..."
MSG_WAITING = "Sign in inside the Chrome window that just opened."
MSG_CAPTURING = "Finishing up..."
#: `Auth/auth_flow.py:30` caps the cookie wait at 300 s. Say what that means in
#: minutes rather than surfacing a selenium traceback.
MSG_TIMEOUT = "No sign-in was completed within 5 minutes. Try again."

#: How long a finished job stays readable before a lazy sweep drops it. A
#: background timer would be a second thread to own for no gain.
_JOB_TTL_SECONDS = 600

#: How long a job may sit without a state transition before it counts as
#: abandoned. `uc.Chrome()` has no timeout of its own (it can block fetching a
#: matching chromedriver), and the vendor's 300 s cookie wait only starts once
#: that returns, so a hung launch would otherwise pin `_active_job_id` and 409
#: every later sign-in for the life of the daemon. 300 s past the vendor's own
#: cap, so a live flow is never swept out from under the user.
_STALLED_SECONDS = 600

#: States a job never leaves.
_TERMINAL = ("done", "failed")

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_active_job_id: str | None = None


class ChromeNotFoundError(Exception):
    """Chrome is not installed, so the flow cannot start at all."""


class GoogleAuthAlreadyRunningError(Exception):
    """One sign-in is already in flight; its job id is on the exception."""

    def __init__(self, job_id: str) -> None:
        super().__init__("A Google sign-in is already in progress.")
        self.job_id = job_id


class _CookieWatchProxy:
    """The real driver, with one observed method: `get_cookie("oauth_token")`.

    `Auth/auth_flow.py:30`'s `WebDriverWait` polls exactly this method until the
    cookie appears, so noticing it here is a real signal rather than a guess,
    and it still touches zero vendor lines. Everything else delegates, including
    the `quit()` the vendor's own `finally` calls.
    """

    def __init__(self, driver: Any, job_id: str) -> None:
        self._driver = driver
        self._job_id = job_id
        self._seen = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._driver, name)

    def get_cookie(self, name: str) -> Any:
        value = self._driver.get_cookie(name)
        if name == "oauth_token" and value is not None and not self._seen:
            self._seen = True
            _set_progress(self._job_id, "capturing", MSG_CAPTURING)
        return value


def _sweep_expired_jobs() -> None:
    """Drop finished jobs past the TTL, and stalled ones. Caller holds `_lock`.

    A job that never reaches a terminal state has no `finished_monotonic`, so a
    finished-only sweep keeps it — and with it `_active_job_id`, which is what
    `start_google_auth()` refuses on. `last_progress_monotonic` measures time
    since the last observed transition, so only a genuinely stuck launch is
    dropped, never a sign-in the user is still working through.
    """
    global _active_job_id
    now = time.monotonic()
    for job_id, job in list(_jobs.items()):
        finished = job.get("finished_monotonic")
        stalled = now - job.get("last_progress_monotonic", now) > _STALLED_SECONDS
        if (finished is not None and now - finished > _JOB_TTL_SECONDS) or (
            finished is None and stalled
        ):
            del _jobs[job_id]
            if _active_job_id == job_id:
                _active_job_id = None


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


def _patch_vendor_chrome(settings: Any, job_id: str) -> None:
    """Rebind the two vendor attributes described in this module's docstring.

    Safe to call again: the second call replaces the first call's closure with
    one carrying the new job id, which is what a second sign-in wants anyway.
    """
    ensure_gfmt_importable()
    import chrome_driver  # vendor top-level module; first import happens here

    def _isolated_create_driver() -> _CookieWatchProxy:
        import undetected_chromedriver as uc

        profile = settings.chrome_profile_dir
        profile.mkdir(parents=True, exist_ok=True)
        # `mode=` on mkdir() is masked by the process umask (022 turns 0o700
        # into 0o755) and does nothing at all when the directory already
        # exists, so the mode is set as its own call. PRI hard rule 9.
        os.chmod(profile, 0o700)
        driver = uc.Chrome(
            options=chrome_driver.get_options(),
            version_main=None,
            user_data_dir=str(profile),
        )
        _set_progress(job_id, "waiting_for_user", MSG_WAITING)
        return _CookieWatchProxy(driver, job_id)

    chrome_driver.create_driver = _isolated_create_driver

    # Imported only AFTER create_driver is replaced: auth_flow binds the name
    # into its own namespace at import time and never looks it up again.
    import Auth.auth_flow as auth_flow

    auth_flow.input = lambda _prompt="": ""


def _run_google_auth(job_id: str, settings: Any) -> None:
    """Thread body: patch the vendor, run the real sign-in, record the outcome."""
    from selenium.common.exceptions import TimeoutException

    from .client import FindHubClient

    try:
        _patch_vendor_chrome(settings, job_id)
        email = FindHubClient(settings).authenticate()
    except TimeoutException:
        _set_progress(job_id, "failed", MSG_TIMEOUT)
    except Exception as exc:
        # F8: Selenium error messages can embed the current URL, which might
        # carry an OAuth token. Scrub before truncating.
        from findplus.redaction import redact_text

        safe_msg = redact_text(str(exc)) or "Unknown error"
        _set_progress(job_id, "failed", safe_msg[:200])
    else:
        _set_progress(job_id, "done", f"Authenticated as {email}.")


def start_google_auth(settings: Any) -> str:
    """Start a sign-in and return its job id.

    Raises ChromeNotFoundError when Chrome is absent (checked before a job id
    is minted or a thread started) and GoogleAuthAlreadyRunningError when one
    is already in flight.
    """
    global _active_job_id
    from findplus.cli.doctor import check_chrome

    if not check_chrome().passed:
        raise ChromeNotFoundError(MSG_CHROME_MISSING)

    with _lock:
        _sweep_expired_jobs()
        active = _jobs.get(_active_job_id) if _active_job_id else None
        if active is not None and active["state"] not in _TERMINAL:
            raise GoogleAuthAlreadyRunningError(_active_job_id)
        job_id = uuid.uuid4().hex
        _jobs[job_id] = {
            "state": "launching",
            "message": MSG_LAUNCHING,
            "finished_monotonic": None,
            "last_progress_monotonic": time.monotonic(),
        }
        _active_job_id = job_id

    threading.Thread(target=_run_google_auth, args=(job_id, settings), daemon=True).start()
    return job_id


def get_google_auth_progress(job_id: str) -> dict[str, Any] | None:
    """`{"state", "message"}`, or None for an unknown or expired job id."""
    with _lock:
        _sweep_expired_jobs()
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {"state": job["state"], "message": job["message"]}
