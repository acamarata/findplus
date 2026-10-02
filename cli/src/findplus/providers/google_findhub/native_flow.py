"""The daemon side of the in-app Google sign-in window (spec in-app-login.md §2.2).

Purpose    : The desktop shell opens a window of its own on Google's sign-in
             page, reads the `oauth_token` Google sets there and hands it over
             loopback; for the unlock step it relays the vault keys the unlock
             page produces. This module mints the single-use state for one such
             window, exchanges the token (sign_in_with_oauth_token, the same
             exchange every other path uses), stores the keys (store_vault_keys,
             which tags them with the signed-in account), tracks the card's phase
             (native_progress.py) and turns every failure into plain words.
             Window reports and the card's Cancel live in native_window.py.
Inputs     : begin(mode); submit_token(state, token); submit_unlock(state, keys,
             account_hint).
Outputs    : JSON-ready dicts; NativeFlowError(status, code, message) on refusal.
Constraints: No HTTP here (api/_routes_auth_google_native.py maps it). The token
             and the keys are passed straight through and never stored, logged or
             put in an error. Vendored code is imported, never edited (PRI rule 8).
"""

from __future__ import annotations

import secrets
from typing import Any

from . import helper_state as hs
from . import native_messages as m
from . import native_progress as progress
from .bootstrap import (
    ensure_gfmt_importable,
    has_google_session,
    has_shared_key,
    needs_shared_key,
    stored_account_email,
)
from .native_classify import ALLOWED_HOST_PATTERN, ALLOWED_HOSTS
from .open_signin import EMBEDDED_SETUP_URL
from .token_signin import (
    GoogleUnreachableError,
    InvalidInputError,
    TokenRejectedError,
    sign_in_with_oauth_token,
)
from .unlock import SharedKeyParseError, store_vault_keys

ACCOUNT_HOME_URL = "https://accounts.google.com/"
SIGNED_IN_HOST = "myaccount.google.com"
MODES = {"signin": hs.KIND_NATIVE_SIGNIN, "unlock": hs.KIND_NATIVE_UNLOCK}
#: Each live native state's flow id: progress writes after a slow exchange only
#: land while their flow is still the current one (contract §3.8).
_flows: dict[str, str] = {}
#: Unlock states that this same window just signed in with: the account is known.
#: Any other unlock state (unlock-only mode) needs the window's account hint.
_after_signin: set[str] = set()

#: What the shell needs to build the window (spec §2, §7, §9.1).
WINDOW = {
    "label": "signin-google",
    "title": "Find+ sign-in: Google (accounts.google.com)",
    "title_template": "Find+ sign-in: Google ({host})",
    "width": 480,
    "height": 720,
    "incognito": True,
    "poll_ms": 500,
    "stuck_after_seconds": 180,
    "timeout_seconds": 600,
    "cookie": {"name": "oauth_token", "value_prefix": "oauth2_4/", "domain_suffix": "google.com"},
    "bridge_host": "findplus-bridge.invalid",
}


class NativeFlowError(Exception):
    """A refused step. `message` is plain words; `code` is for the shell."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.extra = extra


def unlock_url() -> str:
    """Google's unlock page address, built by the vendored function (not edited)."""
    ensure_gfmt_importable()
    from KeyBackup.shared_key_request import get_security_domain_request_url

    return get_security_domain_request_url().strip()


def _unlock_url_or_none(mode: str) -> str | None:
    try:
        return unlock_url()
    except Exception:
        if mode == "unlock":
            raise NativeFlowError(503, "unlock_unavailable", m.MSG_UNLOCK_UNAVAILABLE) from None
        return None  # sign-in still works; the card offers the other unlock paths


def forget_flow_state(state: str) -> None:
    """A state was dropped (closed, blocked, failed): forget what we kept for it."""
    _flows.pop(state, None)
    _after_signin.discard(state)


def _refuse_if_open(if_idle: object) -> None:
    """The card asks with `if_idle`: a window that is still working is followed, not
    replaced (replacing it would kill its state mid sign-in, r12 #3)."""
    snap = progress.snapshot()  # expires a phase whose window state is gone
    if if_idle is True and snap["phase"] in progress.LIVE:
        raise NativeFlowError(
            409, "window_open", m.MSG_WINDOW_OPEN, flow=snap["flow"], mode=snap["mode"]
        )


def begin(mode: object, if_idle: object = False) -> dict[str, Any]:
    """Mint the state for one window (replacing any older one) and describe the window."""
    if not isinstance(mode, str) or mode not in MODES:
        raise NativeFlowError(422, "bad_mode", 'mode must be "signin" or "unlock".')
    _refuse_if_open(if_idle)
    if mode == "unlock" and not has_google_session():
        raise NativeFlowError(409, "not_signed_in", m.MSG_NOT_SIGNED_IN)
    url = _unlock_url_or_none(str(mode))
    hs.drop_states_of(hs.NATIVE_KINDS)
    _flows.clear()
    _after_signin.clear()
    state = hs.create_state(MODES[str(mode)])
    flow = secrets.token_hex(6)
    _flows[state] = flow
    progress.set_phase(
        "connecting", m.MSG_CONNECTING, mode=mode, account=None, unlocked=False, flow=flow
    )
    return {
        "flow": flow,
        "state": state,
        "mode": mode,
        "start_url": EMBEDDED_SETUP_URL if mode == "signin" else ACCOUNT_HOME_URL,
        "unlock_url": url,
        "unlock_after_host": SIGNED_IN_HOST if mode == "unlock" else None,
        "expires_in": int(hs._STATE_TTL_SECONDS),
        "window": WINDOW,
        "allowed_hosts": sorted(ALLOWED_HOSTS),
        "allowed_host_pattern": ALLOWED_HOST_PATTERN.pattern,
        "generation": hs.signin_generation(),
    }


def _claim(kind: str, state: object) -> str:
    if not isinstance(state, str) or not hs.begin_exchange(kind, state):
        raise NativeFlowError(403, "state_invalid", m.MSG_STATE_GONE)
    return state


#: Refusals the shell retries itself (contract §3.2): the window is still
#: working, so the card keeps following it instead of showing an error.
_RETRY_PHASE = {
    "token_malformed": ("waiting", m.MSG_WAITING),
    "google_unreachable": ("finishing", m.MSG_GOOGLE_SLOW),
}


def _fail(state: str, flow: str, status: int, code: str, message: str) -> NativeFlowError:
    """Keep the state for a retry, show the reason on the card, build the error."""
    hs.end_exchange(state, ok=False)
    if code in _RETRY_PHASE:
        phase, words = _RETRY_PHASE[code]
        progress.set_phase_for(flow, phase, words)
    else:
        progress.set_phase_for(flow, "error", message, reason=code)
    return NativeFlowError(status, code, message)


def _exchange(state: str, flow: str, oauth_token: object) -> str:
    try:
        # Empty email on purpose: Google's answer supplies it (vendored flow).
        return sign_in_with_oauth_token("", oauth_token, require_email=False)
    except InvalidInputError:
        raise _fail(state, flow, 422, "token_malformed", m.MSG_WINDOW_FAILED) from None
    except TokenRejectedError:
        raise _fail(state, flow, 400, "token_rejected", m.MSG_REJECTED) from None
    except GoogleUnreachableError as exc:
        raise _fail(state, flow, 502, "google_unreachable", str(exc)) from None
    except Exception:
        raise _fail(state, flow, 500, "signin_failed", m.MSG_HANDOFF_FAILED) from None


def _signed_in(flow: str, account: str, unlocked: bool) -> None:
    words = m.MSG_SIGNED_IN.format(account=account)
    progress.set_phase_for(flow, "success", words, account=account, unlocked=unlocked)


def submit_token(state: object, oauth_token: object) -> dict[str, Any]:
    """Exchange the window's token; say whether the unlock step comes next.

    Cancelled (or replaced by a new begin) while Google answered: the sign-in
    still happened, so the card says so (only for its own flow) and nothing is
    re-kinded. A newer flow's progress is never touched (r12 #4).
    """
    claimed = _claim(hs.KIND_NATIVE_SIGNIN, state)
    flow = _flows.get(claimed, "")
    progress.set_phase_for(flow, "finishing", m.MSG_FINISHING, mode="signin")
    account = _exchange(claimed, flow, oauth_token)
    hs.bump_signin_generation()
    progress.forget_block()
    needs_unlock = needs_shared_key()
    if hs.state_kind(claimed) is None:
        _signed_in(flow, account, unlocked=not needs_unlock)
    elif needs_unlock:
        hs.rekind_state(claimed, hs.KIND_NATIVE_UNLOCK)
        _after_signin.add(claimed)
        progress.set_phase_for(flow, "needs_unlock", m.MSG_NEEDS_UNLOCK, account=account)
    else:
        _signed_in(flow, account, unlocked=True)
        hs.end_exchange(claimed, ok=True)
    return {"result": "signed_in", "account": account, "needs_unlock": needs_unlock}


def submit_unlock(state: object, vault_keys: object, account_hint: object = None) -> dict:
    """Store the unlock page's vault keys for the signed-in account."""
    claimed = _claim(hs.KIND_NATIVE_UNLOCK, state)
    flow = _flows.get(claimed, "")
    expected = stored_account_email()
    if not expected:
        raise _fail(claimed, flow, 409, "not_signed_in", m.MSG_NOT_SIGNED_IN)
    hint = account_hint.strip().lower() if isinstance(account_hint, str) else ""
    if not hint and claimed not in _after_signin:
        # Unlock-only: the keys must never be tagged with a guessed account.
        raise _fail(claimed, flow, 409, "account_unknown", m.MSG_ACCOUNT_UNKNOWN)
    if hint and hint != expected.lower():
        message = m.MSG_ACCOUNT_MISMATCH.format(account=expected)
        raise _fail(claimed, flow, 409, "account_mismatch", message)
    progress.set_phase_for(flow, "finishing", m.MSG_FINISHING, account=expected)
    try:
        store_vault_keys(vault_keys)
    except SharedKeyParseError as exc:
        raise _fail(claimed, flow, 400, "keys_rejected", str(exc)) from None
    except Exception:
        raise _fail(claimed, flow, 500, "unlock_failed", m.MSG_HANDOFF_FAILED) from None
    progress.forget_block()
    words = m.MSG_UNLOCKED.format(account=expected)
    progress.set_phase_for(flow, "success", words, account=expected, unlocked=has_shared_key())
    hs.end_exchange(claimed, ok=True)
    forget_flow_state(claimed)
    return {"result": "unlocked", "account": expected}
