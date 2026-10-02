"""The shared-key page flow, owned by Find+ so it can always stop.

Purpose    : Same steps as the vendored `KeyBackup.shared_key_flow` (open Google
             sign-in, wait for the account, open the unlock page, catch the
             `setVaultSharedKeys` alert), but with a cancel flag, an overall
             deadline and an exit on any browser error. The vendored loop was a
             bare `while True` that swallowed every exception, so a closed window
             spun a CPU core forever (review finding, 2026-10-01).
Inputs     : a `create_driver` callable, an `is_cancelled` callable.
Outputs    : the shared key as hex, or None when the page closed without one.
Constraints: Vendor code is imported, never edited. The key is never logged.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable
from typing import Any

from .bootstrap import ensure_gfmt_importable

__all__ = ["AccountMismatchError", "FlowCancelledError", "FlowTimeoutError", "run_shared_key_flow"]

_SIGNIN_SECONDS = 300
_TOTAL_SECONDS = 900
_TICK_SECONDS = 0.5

_BRIDGE = """
window.mm = {
    setVaultSharedKeys: function(str, vaultKeys) {
        alert(JSON.stringify({ method: 'setVaultSharedKeys', str: str, vaultKeys: vaultKeys }));
    },
    closeView: function() {
        alert(JSON.stringify({ method: 'closeView' }));
    }
};
"""


class FlowCancelledError(Exception):
    """The user cancelled (or the job was swept) while the flow waited."""


class FlowTimeoutError(Exception):
    """The flow ran past its deadline without the page returning a key."""


class AccountMismatchError(Exception):
    """The Find+ Chrome window is signed in as another Google account (message is safe to show)."""


_EMAIL_SCRIPT = """
var e = document.querySelector('a[aria-label*="@"]');
return e ? e.getAttribute('aria-label') : '';
"""


def _window_account(driver: Any) -> str | None:
    """Best-effort email of the account the window is signed in as, or None."""
    import re

    try:
        label = driver.execute_script(_EMAIL_SCRIPT) or ""
    except Exception:
        return None
    found = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(label))
    return found.group(0).lower() if found else None


def _check_account(driver: Any, expected: str | None) -> bool:
    """Raise on another account. True: verified or nothing to compare. False: unreadable."""
    if not expected:
        return True
    actual = _window_account(driver)
    if actual is None:
        return False
    if actual != expected.lower():
        raise AccountMismatchError(
            f"The Find+ Chrome window is signed in as {actual}, but Find+ is signed in as "
            f"{expected}. Sign in to Google with {expected} in that window and try again."
        )
    return True


def _wait_for_signin(
    driver: Any, is_cancelled: Callable[[], bool], until: float, sleep: Any
) -> None:
    signin_by = min(until, time.monotonic() + _SIGNIN_SECONDS)
    while "https://myaccount.google.com" not in driver.current_url:
        if is_cancelled():
            raise FlowCancelledError
        if time.monotonic() > signin_by:
            raise FlowTimeoutError("Google sign-in did not finish in time.")
        sleep(_TICK_SECONDS)


def _read_alert(driver: Any) -> str | None:
    """Text of a pending alert (accepted), or None when there is none."""
    from selenium.common.exceptions import NoAlertPresentException

    try:
        alert = driver.switch_to.alert
        text = alert.text
    except NoAlertPresentException:
        return None
    alert.accept()
    return text


def _wait_for_key(
    driver: Any, is_cancelled: Callable[[], bool], until: float, sleep: Any
) -> str | None:
    from KeyBackup.response_parser import get_fmdn_shared_key

    while True:
        if is_cancelled():
            raise FlowCancelledError
        if time.monotonic() > until:
            raise FlowTimeoutError("The unlock page did not return a key in time.")
        message = _read_alert(driver)  # a browser error propagates and ends the flow
        if message is None:
            sleep(_TICK_SECONDS)
            continue
        try:
            data = json.loads(message)
        except ValueError:
            continue
        method = data.get("method") if isinstance(data, dict) else None
        if method == "setVaultSharedKeys":
            return bytes(get_fmdn_shared_key(data["vaultKeys"])).hex()
        if method == "closeView":
            return None


def run_shared_key_flow(
    create_driver: Callable[[], Any],
    is_cancelled: Callable[[], bool],
    *,
    expected_account: str | None = None,
    on_unverified: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """Drive the unlock page; raises FlowCancelledError, FlowTimeoutError or a driver error.

    `on_unverified` runs when the window's account could not be read (Google changed
    its page), so the caller can log it and tell the user instead of passing silently.
    """
    ensure_gfmt_importable()
    from KeyBackup.shared_key_request import get_security_domain_request_url

    until = time.monotonic() + _TOTAL_SECONDS
    driver = create_driver()
    try:
        driver.get("https://accounts.google.com/")
        _wait_for_signin(driver, is_cancelled, until, sleep)
        if not _check_account(driver, expected_account) and on_unverified:
            on_unverified()
        driver.get(get_security_domain_request_url())
        driver.execute_script(_BRIDGE)
        return _wait_for_key(driver, is_cancelled, until, sleep)
    finally:
        with contextlib.suppress(Exception):
            driver.quit()
