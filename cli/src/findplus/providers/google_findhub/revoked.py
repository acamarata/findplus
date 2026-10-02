"""A revoked or expired Google sign-in becomes a typed "signed out", not a mystery error.

Purpose    : The vendored token step does `auth_response['Auth']`. When Google no
             longer accepts the saved AAS token (password change, revoked app
             access) the response has an `Error` and no `Auth`, so the poll died
             with a bare `KeyError('Auth')` that the UI could only call "the last
             poll did not finish". This module spots that case and raises
             AuthRequiredError instead, and records a `auth_revoked` mark in the
             store so every surface (status, banner, widget, tray) reads
             "sign in again" and the poller stops asking Google.
Inputs     : the exception raised inside a vendored token call.
Outputs    : AuthRequiredError (with plain words), the `auth_revoked` store key.
Constraints: Only the Google error codes that mean "this login is dead" set the
             mark; a transient Google error (service unavailable, network) stays
             a retryable FindHubError. No token value is read, logged or stored.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator

from .types import AuthRequiredError, FindHubError

__all__ = ["REVOKED_MESSAGE", "install_oauth_probe", "revoked_as_auth_error"]

REVOKED_MESSAGE = (
    "Google no longer accepts Find+'s saved sign-in (it expired or was revoked, for example "
    "after a password change). Sign in again."
)

#: gpsoauth `Error` values that mean the saved login is dead for good.
_DEAD_LOGIN_ERRORS = frozenset(
    {"BadAuthentication", "NeedsBrowser", "AccountDeleted", "AccountDisabled", "Expired"}
)

_last = threading.local()


def install_oauth_probe() -> None:
    """Wrap `gpsoauth.perform_oauth` once so the last `Error` code is remembered."""
    import gpsoauth

    original = gpsoauth.perform_oauth
    if getattr(original, "_findplus_probe", False):
        return

    def probe(*args, **kwargs):
        response = original(*args, **kwargs)
        error = response.get("Error") if isinstance(response, dict) else None
        _last.error = error if isinstance(response, dict) and "Auth" not in response else None
        return response

    probe._findplus_probe = True  # type: ignore[attr-defined]
    gpsoauth.perform_oauth = probe


def _set_mark(value: str) -> None:
    from .bootstrap import ensure_gfmt_importable

    ensure_gfmt_importable()
    import Auth.token_cache as token_cache

    token_cache.set_cached_value("auth_revoked", value)


def mark_revoked() -> None:
    with contextlib.suppress(Exception):
        _set_mark("1")


def clear_revoked() -> None:
    """Called when a sign-in finishes: the new login is not the revoked one."""
    with contextlib.suppress(Exception):
        _set_mark("")


@contextlib.contextmanager
def revoked_as_auth_error() -> Iterator[None]:
    """Turn the token step's `KeyError('Auth')` into a typed, plain-words error."""
    _last.error = None
    try:
        yield
    except KeyError as exc:
        if not (exc.args and exc.args[0] == "Auth"):
            raise
        code = getattr(_last, "error", None)
        if code in _DEAD_LOGIN_ERRORS:
            mark_revoked()
            raise AuthRequiredError(REVOKED_MESSAGE) from exc
        raise FindHubError(
            "Google could not confirm Find+'s sign-in just now"
            + (f" ({code})" if code else "")
            + ". Find+ tries again."
        ) from exc
