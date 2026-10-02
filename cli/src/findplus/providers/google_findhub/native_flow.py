"""The daemon side of the in-app Google sign-in window (spec in-app-login.md §2.2).

Purpose    : The desktop shell opens a window of its own on Google's sign-in
             page, reads the `oauth_token` Google sets there and hands it over
             loopback; for the unlock step it relays the vault keys the unlock
             page produces. This module mints the single-use state for one such
             window, exchanges the token (sign_in_with_oauth_token, the same
             exchange every other path uses), stores the keys (store_vault_keys,
             which tags them with the signed-in account), tracks the card's phase
             (native_progress.py) and turns every failure into plain words.
Inputs     : begin(mode); submit_token(state, token); submit_unlock(state, keys,
             account_hint); record_event(state, event, reason);
             classify_report(state, host, path, title_class); cancel().
Outputs    : JSON-ready dicts; NativeFlowError(status, code, message) on refusal.
Constraints: No HTTP here (api/_routes_auth_google_native.py maps it). The token
             and the keys are passed straight through and never stored, logged or
             put in an error. Vendored code is imported, never edited (PRI rule 8).
"""

from __future__ import annotations

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
from .native_classify import ALLOWED_HOST_PATTERN, ALLOWED_HOSTS, ReportError, classify
from .native_classify import clean_report as _clean_report
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
EVENTS = frozenset({"opened", "waiting", "blocked", "closed", "failed"})

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

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


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


def begin(mode: object) -> dict[str, Any]:
    """Mint the state for one window (replacing any older one) and describe the window."""
    if mode not in MODES:
        raise NativeFlowError(422, "bad_mode", 'mode must be "signin" or "unlock".')
    if mode == "unlock" and not has_google_session():
        raise NativeFlowError(409, "not_signed_in", m.MSG_NOT_SIGNED_IN)
    url = _unlock_url_or_none(str(mode))
    hs.drop_states_of(hs.NATIVE_KINDS)
    state = hs.create_state(MODES[str(mode)])
    progress.set_phase("connecting", m.MSG_CONNECTING, mode=mode, account=None, unlocked=False)
    return {
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


def _fail(state: str, status: int, code: str, message: str) -> NativeFlowError:
    """Keep the state for a retry, show the reason on the card, build the error."""
    hs.end_exchange(state, ok=False)
    progress.set_phase("error", message, reason=code)
    return NativeFlowError(status, code, message)


def _exchange(state: str, oauth_token: object) -> str:
    try:
        # Empty email on purpose: Google's answer supplies it (vendored flow).
        return sign_in_with_oauth_token("", oauth_token, require_email=False)
    except InvalidInputError:
        raise _fail(state, 422, "token_malformed", m.MSG_WINDOW_FAILED) from None
    except TokenRejectedError:
        raise _fail(state, 400, "token_rejected", m.MSG_REJECTED) from None
    except GoogleUnreachableError as exc:
        raise _fail(state, 502, "google_unreachable", str(exc)) from None
    except Exception:
        raise _fail(state, 500, "signin_failed", m.MSG_HANDOFF_FAILED) from None


def submit_token(state: object, oauth_token: object) -> dict[str, Any]:
    """Exchange the window's token; say whether the unlock step comes next."""
    claimed = _claim(hs.KIND_NATIVE_SIGNIN, state)
    progress.set_phase("finishing", m.MSG_FINISHING, mode="signin")
    account = _exchange(claimed, oauth_token)
    hs.bump_signin_generation()
    progress.forget_block()
    needs_unlock = needs_shared_key()
    if needs_unlock:
        hs.rekind_state(claimed, hs.KIND_NATIVE_UNLOCK)
        progress.set_phase("needs_unlock", m.MSG_NEEDS_UNLOCK, account=account)
    else:
        hs.end_exchange(claimed, ok=True)
        progress.set_phase(
            "success", m.MSG_SIGNED_IN.format(account=account), account=account, unlocked=True
        )
    return {"result": "signed_in", "account": account, "needs_unlock": needs_unlock}


def submit_unlock(state: object, vault_keys: object, account_hint: object = None) -> dict:
    """Store the unlock page's vault keys for the signed-in account."""
    claimed = _claim(hs.KIND_NATIVE_UNLOCK, state)
    expected = stored_account_email()
    if not expected:
        raise _fail(claimed, 409, "not_signed_in", m.MSG_NOT_SIGNED_IN)
    hint = account_hint.strip().lower() if isinstance(account_hint, str) else ""
    if hint and hint != expected.lower():
        message = m.MSG_ACCOUNT_MISMATCH.format(account=expected)
        raise _fail(claimed, 409, "account_mismatch", message)
    progress.set_phase("finishing", m.MSG_FINISHING, account=expected)
    try:
        store_vault_keys(vault_keys)
    except SharedKeyParseError as exc:
        raise _fail(claimed, 400, "keys_rejected", str(exc)) from None
    except Exception:
        raise _fail(claimed, 500, "unlock_failed", m.MSG_HANDOFF_FAILED) from None
    hs.end_exchange(claimed, ok=True)
    progress.forget_block()
    unlocked = has_shared_key()
    progress.set_phase(
        "success", m.MSG_UNLOCKED.format(account=expected), account=expected, unlocked=unlocked
    )
    return {"result": "unlocked", "account": expected}


def _require_live(state: object) -> tuple[str, str]:
    kind = hs.state_kind(state if isinstance(state, str) else None)
    if kind not in hs.NATIVE_KINDS:
        raise NativeFlowError(403, "state_invalid", m.MSG_STATE_GONE)
    return str(state), str(kind)


def _block(state: str, reason: str) -> None:
    hs.drop_state(state)
    progress.remember_block(reason)
    progress.set_phase("blocked_embedded", m.BLOCKED_REASONS[reason], reason=reason)


def _waiting(kind: str) -> None:
    if kind == hs.KIND_NATIVE_SIGNIN:
        progress.set_phase("waiting", m.MSG_WAITING)
        return
    after_signin = progress.snapshot().get("mode") == "signin"
    progress.set_phase("needs_unlock", m.MSG_NEEDS_UNLOCK if after_signin else m.MSG_UNLOCK_WAITING)


def record_event(state: object, event: object, reason: object = None) -> dict[str, Any]:
    """What the shell saw: the window opened, is waiting, was blocked, closed or failed."""
    live, kind = _require_live(state)
    if event not in EVENTS:
        raise NativeFlowError(422, "bad_event", "event is not one of the known events.")
    if event in ("opened", "waiting"):
        _waiting(kind)
    elif event == "blocked":
        _block(live, reason if reason in m.BLOCKED_REASONS else "other")
    elif event == "closed":
        hs.drop_state(live)
        if progress.current_phase() not in progress.TERMINAL:
            progress.set_phase("cancelled", m.MSG_CANCELLED)
    else:  # failed
        hs.drop_state(live)
        word = reason if reason in m.FAILED_REASONS else "other"
        progress.set_phase("error", m.FAILED_REASONS[str(word)], reason=word)
    return _brief()


def classify_report(state: object, host: object, path: object, title_class: object) -> dict:
    """Blocked or not, from a host, a path and a title class. A block closes the flow."""
    live, _kind = _require_live(state)
    try:
        clean_host, clean_path, title = _clean_report(host, path, title_class)
    except ReportError as exc:
        raise NativeFlowError(422, "bad_report", str(exc)) from None
    verdict = classify(clean_host, clean_path, title)
    if verdict.blocked:
        _block(live, str(verdict.reason))
    snap = progress.snapshot()
    return {
        "blocked": verdict.blocked,
        "reason": verdict.reason,
        "action": "close" if verdict.blocked else "continue",
        "fallback": snap["fallback"] if verdict.blocked else None,
    }


def cancel() -> dict[str, Any]:
    """Drop every in-app state; the card says Cancelled. Safe to call twice."""
    hs.drop_states_of(hs.NATIVE_KINDS)
    if progress.current_phase() not in progress.TERMINAL:
        progress.set_phase("cancelled", m.MSG_CANCELLED)
    return _brief()


def _brief() -> dict[str, Any]:
    snap = progress.snapshot()
    return {"phase": snap["phase"], "message": snap["message"], "fallback": snap["fallback"]}
