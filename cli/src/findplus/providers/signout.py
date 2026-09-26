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
             Never touches the devices table, sightings, places, groups or
             alert rules: sign-out is a credential operation, not a data one.
"""

from __future__ import annotations

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


def sign_out(provider: str, settings) -> bool:
    """Remove `provider`'s saved sign-in credential, if any.

    Raises UnknownProviderError for anything other than the two registered
    provider ids -- the caller (the API route, the CLI) turns that into a
    404 / a plain error message rather than silently doing nothing.
    """
    path = _credential_path(provider, settings)
    existed = path.exists()
    if existed:
        path.unlink()
    return existed
