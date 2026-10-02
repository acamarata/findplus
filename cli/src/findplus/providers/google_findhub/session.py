"""Save a Google Find Hub session and announce it, for every sign-in path.

Purpose    : The one place that finishes a Google sign-in. Both the automatic
             flow (client.FindHubClient.authenticate, which lets the vendored
             `get_aas_token()` write the token itself) and the main-Chrome
             token flow (token_signin.py, which exchanges a pasted
             `oauth_token`) end in `finish_sign_in()`, so "signed in" is logged
             and reported the same way whichever path produced it.
Inputs     : An AAS token and the account email (save_session only).
Outputs    : The account email. secrets.json gains `aas_token` and `username`.
Constraints: Writes go through the vendored `Auth.token_cache.set_cached_value`,
             which `bootstrap.ensure_gfmt_importable()` rebinds to the 0600
             `_set_and_harden` wrapper, so there is one write path and one file
             mode. The token value is never logged or returned. No vendored
             file is edited (PRI hard rule 8).
"""

from __future__ import annotations

import contextlib
import json
import os

from findplus.config import get_settings
from findplus.logging_setup import get_logger

from .bootstrap import ensure_gfmt_importable

log = get_logger(__name__)

#: Keys the vendored code caches per ACCOUNT, not per machine: the E2EE shared
#: key and the owner key derived from it. `fcm_credentials` (the Android id and
#: push registration) belong to this install and are kept.
_ACCOUNT_BOUND_KEYS = ("owner_key", "shared_key")


def _drop_account_bound_keys() -> None:
    """Remove the previous account's keys before a different account is saved.

    Without this, switching accounts kept the old account's owner key, and the
    first poll failed to decrypt with a "the account was reset" error.
    """
    path = get_settings().secrets_file
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict) or not any(k in data for k in _ACCOUNT_BOUND_KEYS):
        return
    for key in _ACCOUNT_BOUND_KEYS:
        data.pop(key, None)
    path.write_text(json.dumps(data))
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def finish_sign_in(email: str) -> str:
    """Log the finished sign-in (the account, never a token) and return the email."""
    from .revoked import clear_revoked

    clear_revoked()
    log.info("auth_complete", account=email, secrets_path=str(get_settings().secrets_file))
    return email


def save_session(aas_token: str, email: str) -> str:
    """Store `aas_token` + `username` 0600 and finish the sign-in.

    A different account than the one stored drops that account's E2EE keys
    first, so the new account's are fetched fresh on the first poll.
    """
    ensure_gfmt_importable()
    import Auth.token_cache as token_cache

    previous = token_cache.get_cached_value("username")
    if previous and str(previous).lower() != email.lower():
        _drop_account_bound_keys()
    token_cache.set_cached_value("aas_token", aas_token)
    token_cache.set_cached_value("username", email)
    return finish_sign_in(email)
