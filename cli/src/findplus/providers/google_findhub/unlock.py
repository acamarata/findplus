"""Unlock a Google account's Find Hub encryption key, in Find+'s own Chrome.

Purpose    : Google encrypts Find Hub locations end to end and releases the key
             only to a browser page that has passed the account's Android
             screen-lock check. This runs the shared-key
             page flow (unlock_flow.py, same steps as the vendored one) through
             Find+'s OWN isolated Chrome window (never the user's), stores the
             resulting key 0600, and exposes a job-id progress machine the API
             polls -- the same shape as browser.py's sign-in.
Inputs     : a `Settings` (for `chrome_profile_dir`), and a job id minted here.
Outputs    : `start_google_unlock()` -> job id; `get_google_unlock_progress()`
             -> `{"state", "message"}` or None; `cancel_google_unlock()` -> bool.
Constraints: `cli/vendor/GoogleFindMyTools/` is never edited (PRI hard rule 8).
             The vendored flow reaches the encryption key through a browser and
             a JavaScript bridge the page itself calls; Find+ pastes nothing and
             shows no console snippet. It runs only in a window the user started
             here, in a profile of its own. The shared key is never logged.
             The flow loop (unlock_flow.py) takes the Chrome factory directly and
             stops on cancel, deadline or any browser error.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
import uuid
from typing import Any

from .bootstrap import ensure_gfmt_importable, restore_create_driver_guard, stored_account_email

__all__ = [
    "MSG_CANCELLED",
    "GoogleUnlockAlreadyRunningError",
    "cancel_google_unlock",
    "get_google_unlock_progress",
    "start_google_unlock",
]

MSG_LAUNCHING = "Starting the Find+ Chrome window..."
MSG_WAITING = (
    "In the Find+ Chrome window, sign in with the same Google account first if Google asks, "
    "then enter your Android phone's screen lock."
)
MSG_SAVING = "Saving the key..."
MSG_DONE = "Encrypted locations unlocked."
MSG_CANCELLED = "Unlock cancelled."
MSG_FAILED = "The unlock did not finish. Try again."
MSG_TIMEOUT = "The unlock window was open too long. Start the unlock again."
MSG_NO_KEY = "That page did not return an encryption key. Try again."
MSG_NO_VAULT_KEY = (
    "No usable encryption key was found. Enter your Android screen lock and try again."
)


class SharedKeyParseError(Exception):
    """The vault keys held no usable finder_hw key; message is safe to show."""


_JOB_TTL_SECONDS = 600
_STALLED_SECONDS = 600
_TERMINAL = ("done", "failed")

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_active_job_id: str | None = None


class GoogleUnlockAlreadyRunningError(Exception):
    """One unlock is already in flight; its job id is on the exception."""

    def __init__(self, job_id: str) -> None:
        super().__init__("A Google unlock is already in progress.")
        self.job_id = job_id


def _sweep_expired_jobs() -> None:
    """Drop finished jobs past the TTL, and stalled ones. Caller holds `_lock`."""
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
    """Record a state transition. Ignores a swept or cancelled job."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.get("cancelled"):
            return
        job["state"] = state
        job["message"] = message
        job["last_progress_monotonic"] = time.monotonic()
        if state in _TERMINAL:
            job["finished_monotonic"] = time.monotonic()


def _make_isolated_driver(settings: Any, job_id: str) -> Any:
    """Return a factory for Find+'s own Chrome profile, recorded on the job.

    The flow in unlock_flow.py receives it directly, so no vendor module has its
    `create_driver` rebound for an unlock and the blocked guard stays in place.
    """
    ensure_gfmt_importable()
    import chrome_driver

    def _isolated_create_driver() -> Any:
        import undetected_chromedriver as uc

        from .chrome_path import chrome_kwargs

        profile = settings.chrome_profile_dir
        profile.mkdir(parents=True, exist_ok=True)
        os.chmod(profile, 0o700)  # mkdir(mode=) is umask-masked; PRI rule 9
        driver = uc.Chrome(
            options=chrome_driver.get_options(),
            version_main=None,
            user_data_dir=str(profile),
            **chrome_kwargs(),
        )
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["driver"] = driver
        _set_progress(job_id, "waiting_for_user", MSG_WAITING)
        return driver

    return _isolated_create_driver


def _is_cancelled(job_id: str) -> bool:
    """True once the job was cancelled or swept; the flow loop stops on it."""
    with _lock:
        job = _jobs.get(job_id)
        return job is None or bool(job.get("cancelled"))


def _store_shared_key(shared_key_hex: str) -> None:
    """Persist the key 0600 via the vendored, hardened token store. Never logged.

    The key is tagged with the account Find+ is signed in as, so a key unlocked
    for another account is never mistaken for this one's (has_shared_key()).
    """
    ensure_gfmt_importable()
    import Auth.token_cache as token_cache

    account = str(token_cache.get_cached_value("username") or "").lower()
    previous = token_cache.get_cached_value("shared_key_account")
    if previous and previous != account:
        token_cache.set_cached_value("owner_key", "")  # derived from the other account's key
    token_cache.set_cached_value("shared_key", shared_key_hex)
    token_cache.set_cached_value("shared_key_account", account)


def store_vault_keys(vault_keys: object) -> None:
    """Parse the vault keys the unlock page produced and store the shared key 0600.

    The Chrome-helper path (api/_routes_auth_google_helper.py) calls this with
    the value the extension relayed. Accepts a JSON string or an already-parsed
    object. The key is never logged. Raises SharedKeyParseError (a friendly
    message, no vendor traceback) when no finder_hw key is present.
    """
    import json

    ensure_gfmt_importable()
    from KeyBackup.response_parser import get_fmdn_shared_key

    payload = vault_keys if isinstance(vault_keys, str) else json.dumps(vault_keys)
    try:
        key = get_fmdn_shared_key(payload)
    except Exception:
        raise SharedKeyParseError(MSG_NO_VAULT_KEY) from None
    _store_shared_key(bytes(key).hex())
    _wake_poller()


def _wake_poller() -> None:
    """Poll now: the locked-account failures that put the poller in backoff are over."""
    from findplus.poller_service import wake_poller

    wake_poller()


def _run_google_unlock(job_id: str, settings: Any) -> None:
    """Thread body: run the key flow in Find+'s Chrome, store the key."""
    from . import unlock_flow
    from .bootstrap import install_vendor_guards

    try:
        shared_key_hex = unlock_flow.run_shared_key_flow(
            _make_isolated_driver(settings, job_id),
            lambda: _is_cancelled(job_id),
            expected_account=stored_account_email(),
        )
        if not shared_key_hex:
            _set_progress(job_id, "failed", MSG_NO_KEY)
            return
        _set_progress(job_id, "capturing", MSG_SAVING)
        _store_shared_key(shared_key_hex)
    except unlock_flow.FlowCancelledError:
        return  # cancel_google_unlock() already recorded the outcome
    except unlock_flow.AccountMismatchError as exc:
        _set_progress(job_id, "failed", str(exc))
    except unlock_flow.FlowTimeoutError:
        _set_progress(job_id, "failed", MSG_TIMEOUT)
    except Exception as exc:
        from findplus.redaction import redact_text

        safe = redact_text(str(exc)) or "Unknown error"
        _set_progress(job_id, "failed", MSG_FAILED if not safe else safe[:200])
    else:
        _wake_poller()
        _set_progress(job_id, "done", MSG_DONE)
    finally:
        # Belt and braces: a job never rebinds create_driver now, but a leftover
        # real launcher on any vendor module must not outlive the job.
        restore_create_driver_guard()
        install_vendor_guards()


def start_google_unlock(settings: Any) -> str:
    """Start an unlock and return its job id.

    Raises GoogleUnlockAlreadyRunningError when one is already in flight.
    """
    global _active_job_id
    with _lock:
        _sweep_expired_jobs()
        active = _jobs.get(_active_job_id) if _active_job_id else None
        if active is not None and active["state"] not in _TERMINAL:
            raise GoogleUnlockAlreadyRunningError(_active_job_id)
        job_id = uuid.uuid4().hex
        _jobs[job_id] = {
            "state": "launching",
            "message": MSG_LAUNCHING,
            "finished_monotonic": None,
            "last_progress_monotonic": time.monotonic(),
            "cancelled": False,
            "driver": None,
        }
        _active_job_id = job_id

    threading.Thread(target=_run_google_unlock, args=(job_id, settings), daemon=True).start()
    return job_id


def get_google_unlock_progress(job_id: str) -> dict[str, Any] | None:
    """`{"state", "message"}`, or None for an unknown or expired job id."""
    with _lock:
        _sweep_expired_jobs()
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {"state": job["state"], "message": job["message"]}


def cancel_google_unlock(job_id: str) -> bool:
    """Best-effort cancel: quit the Chrome window, unblocking the vendored wait.

    Returns False for a job that never existed or already ended.
    """
    global _active_job_id
    with _lock:
        _sweep_expired_jobs()
        job = _jobs.get(job_id)
        if job is None or job["state"] in _TERMINAL:
            return False
        job["cancelled"] = True
        driver = job.get("driver")

    if driver is not None:
        with contextlib.suppress(Exception):
            driver.quit()

    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job["state"] = "failed"
            job["message"] = MSG_CANCELLED
            job["finished_monotonic"] = time.monotonic()
            job["last_progress_monotonic"] = time.monotonic()
        if _active_job_id == job_id:
            _active_job_id = None
    return True
