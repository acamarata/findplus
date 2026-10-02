"""Provider sign-out: remove Find+'s own saved sign-in credential.

Purpose    : S11/WP8 (gap-audit-2026-09-26) -- a user must be able to
             disconnect Google or Apple without a terminal and without
             leaving a stale credential on disk. `DELETE /api/auth/{provider}`
             (api/routes_auth.py) and `findplus auth --sign-out`
             (cli/cmd_auth.py) both call `sign_out()` so the two surfaces
             cannot drift, the same single-source pattern auth_status.py
             already uses for sign-in status.
Inputs     : the provider id (`"google-find-hub"` or `"apple-find-my"`) and a
             `Settings`.
Outputs    : bool -- True when a credential file existed and was removed,
             False when the provider was already signed out. Neither answer
             is an error: disconnecting an already-disconnected provider is a
             normal, idempotent request from a "Disconnect" button a user
             might click twice.
Constraints: Only the session/login credential is removed.
             - Google: `secrets.json`, the Find+ copy of GoogleFindMyTools'
               AAS/ADM tokens, FCM credentials and owner key. Both
               `client.py`'s `is_authenticated()` and `bootstrap.py`'s
               `stored_account_email()` read this file live on every call, so
               deleting it is the whole state reset -- nothing else caches
               "signed in" in memory.
             - Apple: `apple-account.json`, the saved login/session state.
               `provider.py`'s `is_authenticated()` reads it live the same
               way, so again deleting it is sufficient on its own.
             Apple's registered accessory keys (`apple/<device_id>.json`,
             accessories.py) are deliberately NEVER touched here. They are
             not a Find+-generated credential: every one of them is the
             user's own imported tracker key (a Find My pairing plist, or a
             raw private key they supplied), the same "apple's imported
             accessory plists" the gap audit named as off-limits. Deleting
             them would also silently stop location updates for devices that
             PROMPT.md invariant 12 says must keep being tracked after
             sign-out ("Tracked devices and history stay") -- an accessory's
             key is what decrypts its *future* reports, independent of
             whether an Apple ID is currently signed in.
             - Google also empties `~/.findplus/chrome-profile`, the Chrome profile
               Find+'s own window (unlock, "own window" sign-in) logs into. It holds
               Google session cookies for the whole account, so leaving it would
               make Disconnect a half measure. Only that folder, nothing else.
             Never touches the devices table, sightings, places, groups or
             alert rules: sign-out is a credential operation, not a data one.
"""

from __future__ import annotations

import contextlib
import shutil
from pathlib import Path

GOOGLE = "google-find-hub"
APPLE = "apple-find-my"


class UnknownProviderError(ValueError):
    """`provider` is neither "google-find-hub" nor "apple-find-my"."""


def _credential_path(provider: str, settings):
    if provider == GOOGLE:
        return settings.secrets_file
    if provider == APPLE:
        from findplus.providers.apple_findmy.auth import _state_path

        return _state_path(settings)
    raise UnknownProviderError(provider)


def _wipe_chrome_profile(settings) -> bool:
    """Empty Find+'s own Chrome profile: it holds a live Google login for the account.

    Only `<state_dir>/chrome-profile` is touched. A symlink, or a path that does not
    resolve to a direct child of the state dir, is left alone. The folder itself stays.
    Returns True when something was removed.
    """
    profile = Path(settings.chrome_profile_dir)
    try:
        inside = profile.parent.resolve() == Path(settings.state_dir).resolve()
    except OSError:
        return False
    if profile.is_symlink() or not profile.is_dir() or not inside:
        return False
    removed = False
    for child in profile.iterdir():
        with contextlib.suppress(OSError):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed = True
    return removed


def _cancel_google_jobs() -> None:
    """Stop any running sign-in/unlock job and kill unconsumed helper states first.

    A job that finished after Disconnect would otherwise write a fresh token or key
    for the account the user just signed out of, and Chrome would rewrite its
    cookies under the profile wipe.
    """
    from .google_findhub import browser, helper_state, job_guards, unlock

    job_guards.cancel_active(browser, browser.cancel_google_auth)
    job_guards.cancel_active(unlock, unlock.cancel_google_unlock)
    helper_state.drop_all_states()
    from .google_findhub import native_progress

    native_progress.reset()  # the in-app window's card goes back to Connect


def sign_out(provider: str, settings) -> bool:
    """Remove `provider`'s saved sign-in credential, if any.

    Raises UnknownProviderError for anything other than the two registered
    provider ids -- the caller (the API route, the CLI) turns that into a
    404 / a plain error message rather than silently doing nothing.
    """
    path = _credential_path(provider, settings)
    if provider == GOOGLE:
        _cancel_google_jobs()
    existed = path.exists()
    if existed:
        path.unlink()
    if provider == GOOGLE:
        # Disconnect must not leave a full Google browser login behind.
        existed = _wipe_chrome_profile(settings) or existed
    return existed
