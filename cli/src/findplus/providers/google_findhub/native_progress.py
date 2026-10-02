"""Where the in-app Google sign-in stands, for the card, the CLI and the shell.

Purpose    : One process-wide record of the in-app sign-in window's phase
             (spec in-app-login.md §7): idle, connecting, waiting, finishing,
             needs_unlock, success, blocked_embedded, error, cancelled. Also
             remembers a block for 7 days (spec §3.4) so the card starts at the
             Chrome helper meanwhile, and works out the fallback ladder hint.
Inputs     : `set_phase()` / `set_phase_for()` from native_flow.py and
             native_window.py; `snapshot()` for readers.
Outputs    : `snapshot()` -> the progress dict GET /api/auth/google/native/progress
             serves and /api/auth/status embeds.
Constraints: Never stores a token, a key or a state. The block memory is a tiny
             JSON file in the state dir (0600), holding a time and a reason word.
             This record is the one truth (contract §3.8): a live phase with no
             live window state left (the app quit or crashed; states last 10
             minutes) is expired by `snapshot()`, never shown forever.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from findplus.config import get_settings

from . import native_messages as m

PHASES = (
    "idle",
    "connecting",
    "waiting",
    "finishing",
    "needs_unlock",
    "success",
    "blocked_embedded",
    "error",
    "cancelled",
)
#: Phases after which the window is gone and nothing more will happen.
TERMINAL = frozenset({"idle", "success", "blocked_embedded", "error", "cancelled"})
LIVE = frozenset(PHASES) - TERMINAL
BLOCK_MEMORY = timedelta(days=7)
_FILE = "native-signin.json"

_lock = threading.Lock()
_progress: dict[str, Any] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _blank() -> dict[str, Any]:
    return {
        "phase": "idle",
        "message": m.MSG_IDLE,
        "mode": None,
        "account": None,
        "unlocked": False,
        "reason": None,
        "flow": None,
        "updated_at": _now().isoformat(),
    }


def _write(phase: str, message: str, fields: dict[str, Any]) -> None:
    """Under the lock: one transition."""
    if not _progress:
        _progress.update(_blank())
    _progress.update(fields, phase=phase, message=message, updated_at=_now().isoformat())
    _progress["reason"] = fields.get("reason")


def set_phase(phase: str, message: str, **fields: Any) -> None:
    """Record a transition. `fields` may set mode, account, unlocked, reason and flow."""
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}")
    with _lock:
        _write(phase, message, fields)


def set_phase_for(flow: str, phase: str, message: str, **fields: Any) -> bool:
    """Record a transition only while `flow` is still the current flow.

    A slow token exchange from an older window must never paint over a newer
    sign-in (r12 #4). Returns True when it was written."""
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}")
    with _lock:
        if not flow or _progress.get("flow") != flow:
            return False
        _write(phase, message, fields)
        return True


def current_phase() -> str:
    with _lock:
        return str(_progress.get("phase", "idle"))


def reset() -> None:
    """Back to idle (Disconnect, tests)."""
    with _lock:
        _progress.clear()


# ------------------------------------------------------------- block memory
def _path():
    return get_settings().state_dir / _FILE


def remember_block(reason: str) -> None:
    """Remember that Google blocked the window, for BLOCK_MEMORY."""
    path = _path()
    with contextlib.suppress(OSError):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=True)
        os.chmod(path, 0o600)
        path.write_text(json.dumps({"blocked_at": _now().isoformat(), "reason": reason}))


def forget_block() -> None:
    """A sign-in in the window worked: start there again next time."""
    with contextlib.suppress(OSError):
        _path().unlink(missing_ok=True)


def blocked_at() -> datetime | None:
    """When the window was last blocked, if within BLOCK_MEMORY; else None."""
    try:
        data = json.loads(_path().read_text())
        when = datetime.fromisoformat(str(data["blocked_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when if _now() - when < BLOCK_MEMORY else None


# ----------------------------------------------------------- fallback ladder
def _chrome_found() -> bool:
    try:
        from findplus.cli.doctor import check_chrome

        return bool(check_chrome().passed)
    except Exception:
        return False


def _helper_failed_after_block(blocked: datetime | None) -> bool:
    """True when the window is blocked and the latest Chrome-helper sign-in failed too.

    The helper's outcome is cleared by every begin, so it is always the newest try.
    """
    from . import helper_state

    outcome = helper_state.last_outcome()
    return bool(blocked and outcome and outcome.get("kind") == "signin" and not outcome.get("ok"))


def fallback_hint(phase: str, blocked: datetime | None) -> str | None:
    """The next rung of the ladder (spec §3.4): use_helper, use_paste, or None.

    The window comes first; after a block or an error the Chrome helper; the
    paste path when Chrome is missing or the helper also failed since the block.
    """
    if phase not in ("blocked_embedded", "error") and blocked is None:
        return None
    if not _chrome_found() or _helper_failed_after_block(blocked):
        return "use_paste"
    return "use_helper"


def _expire_stale() -> None:
    """A live phase whose window state is gone: the window can no longer report.

    After a finished sign-in that waited on the unlock it stays signed in
    (locked); anything else goes back to idle."""
    from . import helper_state

    with _lock:
        phase, account = _progress.get("phase"), _progress.get("account")
        if phase not in LIVE or helper_state.has_states_of(helper_state.NATIVE_KINDS):
            return
        if phase == "needs_unlock" and account:
            words = m.MSG_SIGNED_IN.format(account=account)
            _write("success", words, {"account": account, "unlocked": False})
            return
        flow = _progress.get("flow")
        _progress.clear()
        _progress.update(_blank(), flow=flow)


def snapshot() -> dict[str, Any]:
    """The progress dict every reader gets. Never raises."""
    from . import helper_state

    _expire_stale()
    with _lock:
        data = dict(_progress) if _progress else _blank()
    blocked = blocked_at()
    data["blocked_at"] = blocked.isoformat() if blocked else None
    data["start_with"] = "helper" if blocked else "window"
    data["fallback"] = fallback_hint(str(data["phase"]), blocked)
    data["generation"] = helper_state.signin_generation()
    return data
