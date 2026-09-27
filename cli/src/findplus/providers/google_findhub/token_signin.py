"""Google sign-in from an `oauth_token` the user copied out of their own Chrome.

Purpose    : The main-Chrome sign-in path. Chrome 136+ ignores remote-debugging
             switches on the default profile, so Find+ cannot automate the
             browser people actually use. Google hands the Find Hub token only
             to a browser, as the `oauth_token` cookie accounts.google.com/
             EmbeddedSetup sets after sign-in. The user copies that cookie and
             this module runs the same exchange the vendored
             `Auth/aas_token_retrieval._generate_aas_token` runs on it, without
             editing vendored code, then saves the session via session.py.
Inputs     : An email and a pasted `oauth_token` value.
Outputs    : `sign_in_with_oauth_token()` -> the signed-in account email.
             Raises a `TokenSignInError` subclass whose message is safe to show
             a person (never a traceback, never the token).
Constraints: The token is never logged, stored, echoed or chained into an
             exception (`from None`). The exchange blocks (FCM registration can
             retry forever upstream), so it runs on a daemon thread with a hard
             timeout; both the API route and the CLI call this one function.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from .bootstrap import ensure_gfmt_importable
from .session import save_session

TOKEN_PREFIX = "oauth2_4/"
EXCHANGE_TIMEOUT_SECONDS = 60.0

MSG_BAD_EMAIL = "Enter the Google email address you signed in with."
MSG_BAD_TOKEN = (
    "That does not look like the oauth_token value. Copy the Value column of the "
    "oauth_token row; it starts with oauth2_4/."
)
MSG_REJECTED = (
    "Google did not accept that token. It expires within minutes: sign in again in "
    "Chrome and copy a fresh one."
)
MSG_UNREACHABLE = "Couldn't reach Google. Check your internet connection and try again."
MSG_FAILED = "Find+ could not finish the sign-in. Copy a fresh token and try again."

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_QUOTES = "\"'`"


class TokenSignInError(Exception):
    """A sign-in that did not finish. `str(exc)` is written for a person."""


class InvalidInputError(TokenSignInError):
    """The email or token is malformed; nothing was sent to Google."""


class TokenRejectedError(TokenSignInError):
    """Google answered but issued no token (expired, reused or mistyped)."""


class GoogleUnreachableError(TokenSignInError):
    """Google could not be reached, or did not answer in time."""


def clean_email(raw: object) -> str:
    """The trimmed email, or InvalidInputError."""
    email = raw.strip() if isinstance(raw, str) else ""
    if not _EMAIL.match(email):
        raise InvalidInputError(MSG_BAD_EMAIL)
    return email


def clean_oauth_token(raw: object) -> str:
    """The pasted cookie value without whitespace or wrapping quotes, or InvalidInputError.

    DevTools copies can carry a trailing newline or surrounding quotes; a real
    token contains neither, so both are removed rather than rejected.
    """
    token = "".join(raw.split()).strip(_QUOTES) if isinstance(raw, str) else ""
    if not token.startswith(TOKEN_PREFIX) or len(token) <= len(TOKEN_PREFIX):
        raise InvalidInputError(MSG_BAD_TOKEN)
    return token


def _android_id() -> Any:
    """This install's Android id, registering with FCM first when needed.

    Upstream's `FcmReceiver.get_android_id()` returns None on a first run: it
    registers (which stores the credentials) but returns the listener's result
    instead of the id. Read the id from the fresh credentials in that case.
    """
    from Auth.fcm_receiver import FcmReceiver

    receiver = FcmReceiver()
    android_id = receiver.get_android_id()
    if android_id is None and receiver.credentials:
        android_id = receiver.credentials["gcm"]["android_id"]
    if android_id is None:
        raise GoogleUnreachableError(MSG_UNREACHABLE)
    return android_id


def _exchange(email: str, token: str) -> dict[str, Any]:
    """gpsoauth's token exchange, with every failure mapped to a typed error."""
    ensure_gfmt_importable()
    import gpsoauth
    import requests

    response: Any = None
    try:
        response = gpsoauth.exchange_token(email, token, _android_id())
    except TokenSignInError:
        raise
    except (requests.RequestException, OSError):
        pass  # raised below, outside the handler, so no context carries the token
    if response is None:
        raise GoogleUnreachableError(MSG_UNREACHABLE)
    if not isinstance(response, dict) or not response.get("Token"):
        raise TokenRejectedError(MSG_REJECTED)
    return response


def _run_with_timeout(email: str, token: str, timeout: float) -> dict[str, Any]:
    """Run `_exchange` on a daemon thread; GoogleUnreachableError past `timeout`.

    A daemon thread, not a ThreadPoolExecutor: an abandoned exchange must not
    hold the process open at exit.
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def _body() -> None:
        try:
            box["response"] = _exchange(email, token)
        except TokenSignInError as exc:
            box["error"] = exc
        except Exception:  # anything else: a person-safe message, no traceback text
            box["error"] = TokenSignInError(MSG_FAILED)
        finally:
            done.set()

    threading.Thread(target=_body, name="findplus-google-token", daemon=True).start()
    if not done.wait(timeout):
        raise GoogleUnreachableError(MSG_UNREACHABLE)
    if "error" in box:
        raise box["error"]
    return box["response"]


def sign_in_with_oauth_token(
    email: object, oauth_token: object, *, timeout: float = EXCHANGE_TIMEOUT_SECONDS
) -> str:
    """Validate, exchange and save. Returns the account email Google confirmed."""
    clean = clean_email(email)
    token = clean_oauth_token(oauth_token)
    response = _run_with_timeout(clean, token, timeout)
    account = str(response.get("Email") or clean)
    return save_session(response["Token"], account)
