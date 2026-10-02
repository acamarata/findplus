"""What the in-app Google sign-in window reports, and the card's Cancel.

Purpose    : The desktop shell tells the daemon what its window saw (opened,
             waiting, blocked, closed, failed) and asks whether a loaded page
             is Google refusing the window; the dashboard card may cancel.
             Each report moves the one progress record (native_progress.py),
             which is the single truth the card and the shell both read
             (contract in-app-login-contract.md §3.8). The phase is written before
             the state is dropped, so a reader never sees a live phase without
             one (native_progress expires that case). Split from
             native_flow.py, which mints the state and runs the exchanges.
Inputs     : record_event(state, event, reason); classify_report(state, host,
             path, title_class); cancel().
Outputs    : JSON-ready dicts; NativeFlowError(status, code, message) on refusal.
Constraints: A report needs a live native state, so it always belongs to the
             current flow (a new begin drops every older state). Never sees a
             token or a key.
"""

from __future__ import annotations

from typing import Any

from . import helper_state as hs
from . import native_messages as m
from . import native_progress as progress
from .native_classify import ReportError, classify
from .native_classify import clean_report as _clean_report
from .native_flow import NativeFlowError, forget_flow_state

EVENTS = frozenset({"opened", "waiting", "blocked", "closed", "failed"})


def _require_live(state: object) -> tuple[str, str]:
    kind = hs.state_kind(state if isinstance(state, str) else None)
    if kind not in hs.NATIVE_KINDS:
        raise NativeFlowError(403, "state_invalid", m.MSG_STATE_GONE)
    return str(state), str(kind)


def _drop(state: str) -> None:
    hs.drop_state(state)
    forget_flow_state(state)


def _block(state: str, reason: str) -> None:
    progress.remember_block(reason)
    progress.set_phase("blocked_embedded", m.BLOCKED_REASONS[reason], reason=reason)
    _drop(state)


def _waiting(kind: str) -> None:
    if kind == hs.KIND_NATIVE_SIGNIN:
        progress.set_phase("waiting", m.MSG_WAITING)
        return
    after_signin = progress.snapshot().get("mode") == "signin"
    progress.set_phase("needs_unlock", m.MSG_NEEDS_UNLOCK if after_signin else m.MSG_UNLOCK_WAITING)


def _word(reason: object, known: dict[str, str]) -> str:
    """A reason the daemon knows, else "other" (any JSON value is safe here)."""
    return reason if isinstance(reason, str) and reason in known else "other"


def _stop() -> None:
    """Closing or cancelling the window is a cancel, except after a finished sign-in: that stays
    signed in, with the locations still locked (attention then says "unlock")."""
    snap = progress.snapshot()
    if snap["phase"] in progress.TERMINAL:
        return
    if snap["phase"] == "needs_unlock" and snap.get("account"):
        account = snap["account"]
        progress.set_phase("success", m.MSG_SIGNED_IN.format(account=account), unlocked=False)
        return
    progress.set_phase("cancelled", m.MSG_CANCELLED)


def _failed(state: str, reason: object) -> None:
    word = _word(reason, m.FAILED_REASONS)
    if word != "other" or progress.current_phase() != "error":
        # A refusal the daemon already explained (wrong account, ...) keeps its words.
        progress.set_phase("error", m.FAILED_REASONS[word], reason=word)
    _drop(state)


def record_event(state: object, event: object, reason: object = None) -> dict[str, Any]:
    """What the shell saw: the window opened, is waiting, was blocked, closed or failed."""
    live, kind = _require_live(state)
    if not isinstance(event, str) or event not in EVENTS:
        raise NativeFlowError(422, "bad_event", "event is not one of the known events.")
    if event in ("opened", "waiting"):
        _waiting(kind)
    elif event == "blocked":
        _block(live, _word(reason, m.BLOCKED_REASONS))
    elif event == "closed":
        _stop()
        _drop(live)
    else:
        _failed(live, reason)
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
    """Drop every in-app state; the card says Cancelled. Safe to call twice.

    A token exchange already running finishes on its own: if Google signed the
    person in, the card says so (native_flow.submit_token)."""
    _stop()
    hs.drop_states_of(hs.NATIVE_KINDS)
    return _brief()


def _brief() -> dict[str, Any]:
    snap = progress.snapshot()
    return {"phase": snap["phase"], "message": snap["message"], "fallback": snap["fallback"]}
