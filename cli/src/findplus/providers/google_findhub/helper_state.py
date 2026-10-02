"""Single-use state for the Find+ Chrome helper, and the origins it may post from.

Purpose    : The helper (browser-helper/) posts the Google sign-in token and the
             end-to-end vault keys back to the daemon. Each flow is opened with a
             random single-use `state` (10-minute TTL); the ingest endpoints
             accept a post only from the pinned extension origin AND with a valid
             unused state. This module holds that state store and the origin
             allow-list, with no HTTP or vendor imports so it is trivial to test.
             The desktop shell's in-app sign-in window (native_flow.py) uses the
             same store with its own two kinds, so a helper state can never drive
             the window's routes or the other way round.
Inputs     : `create_state(kind)`, `consume_state(kind, state)`, `mark_seen()`.
Outputs    : opaque state strings; booleans.
Constraints: In-memory and process-wide (the daemon is one process). A state is
             valid once: `consume_state` removes it, so a replay is refused.
"""

from __future__ import annotations

import secrets
import threading
import time

#: The unpacked extension's fixed id, derived from the public key committed in
#: browser-helper/manifest.json. The daemon trusts helper posts only from this
#: origin (exact match).
EXTENSION_ID = "gegkceilnmbifdpmipcikkgnmdhpkedo"

#: The Chrome Web Store assigns its own id on first upload. Filled in after that
#: (see .github/docs/chrome-web-store/PUBLISHING.md) and shipped in a patch;
#: None until then. Both ids are accepted so the store build and a local
#: unpacked build both work.
CHROME_WEB_STORE_HELPER_ID: str | None = None

KIND_SIGNIN = "signin"
KIND_UNLOCK = "unlock"
#: The desktop shell's in-app sign-in window (native_flow.py). One state covers
#: the sign-in and the unlock that follows it: it is re-kinded, not burned,
#: when the sign-in needs an unlock next.
KIND_NATIVE_SIGNIN = "native_signin"
KIND_NATIVE_UNLOCK = "native_unlock"
NATIVE_KINDS = frozenset({KIND_NATIVE_SIGNIN, KIND_NATIVE_UNLOCK})

HELPER_TOKEN_PATH = "/api/auth/google/helper/token"
HELPER_UNLOCK_PATH = "/api/auth/google/helper/unlock"
#: The two ingest endpoints the extension worker (not a page) posts to. Only
#: these are exempted from the same-origin guard for the extension origin.
HELPER_INGEST_PATHS = frozenset({HELPER_TOKEN_PATH, HELPER_UNLOCK_PATH})

_STATE_TTL_SECONDS = 600.0
_SEEN_TTL_SECONDS = 3600.0

_lock = threading.Lock()
_states: dict[str, tuple[str, float]] = {}
_seen_monotonic: float | None = None
_signin_generation = 0
_inflight: set[str] = set()
_outcome: dict[str, object] | None = None


def allowed_extension_ids() -> list[str]:
    """Every extension id the daemon trusts: the unpacked one, plus the store id
    once it is known."""
    ids = [EXTENSION_ID]
    if CHROME_WEB_STORE_HELPER_ID:
        ids.append(CHROME_WEB_STORE_HELPER_ID)
    return ids


def allowed_extension_origins() -> frozenset[str]:
    return frozenset(f"chrome-extension://{i}" for i in allowed_extension_ids())


def is_allowed_extension_origin(origin: str | None) -> bool:
    return bool(origin) and origin in allowed_extension_origins()


def _sweep(now: float) -> None:
    for state, (_kind, expiry) in list(_states.items()):
        if expiry <= now:
            del _states[state]
            _inflight.discard(state)


def create_state(kind: str) -> str:
    """Mint a single-use state for `kind` ("signin" or "unlock")."""
    global _outcome
    now = time.monotonic()
    with _lock:
        _sweep(now)
        state = secrets.token_urlsafe(32)
        _states[state] = (kind, now + _STATE_TTL_SECONDS)
        _outcome = None
        return state


def consume_state(kind: str, state: str | None) -> bool:
    """True once for a valid, unexpired state of `kind`; removes it (single use)."""
    if not state:
        return False
    now = time.monotonic()
    with _lock:
        _sweep(now)
        entry = _states.get(state)
        if entry is None:
            return False
        stored_kind, expiry = entry
        if stored_kind != kind or expiry <= now:
            return False
        del _states[state]
        return True


def begin_exchange(kind: str, state: str | None) -> bool:
    """Claim `state` for one exchange attempt without burning it.

    True for a valid, unexpired, not-already-running state of `kind`. Unlike
    `consume_state` the state stays valid until `end_exchange(..., ok=True)`, so
    a transient failure (Google slow, 502) can be retried within the TTL. A
    second concurrent attempt on the same state is refused.
    """
    if not state:
        return False
    now = time.monotonic()
    with _lock:
        _sweep(now)
        entry = _states.get(state)
        if entry is None or entry[0] != kind or entry[1] <= now or state in _inflight:
            return False
        _inflight.add(state)
        return True


def end_exchange(state: str, ok: bool) -> None:
    """Finish the attempt: success burns the state (single use), failure keeps it."""
    with _lock:
        _inflight.discard(state)
        if ok:
            _states.pop(state, None)


def state_kind(state: str | None) -> str | None:
    """The kind of a valid, unexpired state, without claiming or burning it."""
    if not state:
        return None
    now = time.monotonic()
    with _lock:
        _sweep(now)
        entry = _states.get(state)
        return entry[0] if entry else None


def rekind_state(state: str, to_kind: str) -> None:
    """End the running attempt and give `state` a new kind and a fresh TTL.

    The in-app window signs in, then unlocks in the same window with the same
    state; the unlock step may take the user a few minutes, so the clock restarts.
    """
    with _lock:
        _inflight.discard(state)
        if state in _states:
            _states[state] = (to_kind, time.monotonic() + _STATE_TTL_SECONDS)


def drop_state(state: str | None) -> None:
    """Forget one state (cancelled, blocked or closed): it can never be used again."""
    with _lock:
        if state:
            _states.pop(state, None)
            _inflight.discard(state)


def drop_states_of(kinds: frozenset[str]) -> None:
    """Forget every state of these kinds (a new in-app sign-in replaces the old one)."""
    with _lock:
        for state, (kind, _expiry) in list(_states.items()):
            if kind in kinds:
                del _states[state]
                _inflight.discard(state)


def has_states_of(kinds: frozenset[str]) -> bool:
    """True while any unexpired state of these kinds exists."""
    now = time.monotonic()
    with _lock:
        _sweep(now)
        return any(kind in kinds for kind, _expiry in _states.values())


def record_outcome(kind: str, ok: bool, message: str = "") -> None:
    """Remember how the latest helper hand-off ended, for the dashboard card.

    `message` is plain words written for a person; never a token or a key.
    """
    global _outcome
    with _lock:
        _outcome = {"kind": kind, "ok": ok, "message": message}


def last_outcome() -> dict[str, object] | None:
    """The latest helper hand-off outcome since the last begin, or None."""
    with _lock:
        return dict(_outcome) if _outcome else None


def mark_seen() -> None:
    """Record that the helper's begin page reported it is installed."""
    global _seen_monotonic
    with _lock:
        _seen_monotonic = time.monotonic()


def helper_seen() -> bool:
    """True when the helper reported in within the last hour (a UI hint only)."""
    with _lock:
        return (
            _seen_monotonic is not None and time.monotonic() - _seen_monotonic <= _SEEN_TTL_SECONDS
        )


def signin_generation() -> int:
    """How many helper sign-ins have completed since the daemon started.

    "Switch Google account" compares this against the value it saw when it
    began, so an already-signed-in status is never mistaken for the new sign-in.
    """
    with _lock:
        return _signin_generation


def bump_signin_generation() -> int:
    """Record one more completed helper sign-in; returns the new generation."""
    global _signin_generation
    with _lock:
        _signin_generation += 1
        return _signin_generation


def drop_all_states() -> None:
    """Forget every unconsumed state (Disconnect: a begin URL minted earlier is dead)."""
    with _lock:
        _states.clear()


def reset_for_tests() -> None:
    """Clear all state; used by tests, never in normal operation."""
    global _seen_monotonic, _signin_generation, _outcome
    with _lock:
        _signin_generation = 0
        _inflight.clear()
        _outcome = None
        _states.clear()
        _seen_monotonic = None
