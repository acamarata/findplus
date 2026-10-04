"""Keep the upstream Find Hub push receiver alive between polls.

Purpose    : Upstream's FcmReceiver starts its push client once and sets `_listening`
             for good. After three connection errors in a row (e.g. an SSL close
             race) the push client shuts itself down, but `_listening` stays True,
             so every later poll waited 90 s for an answer that could not arrive
             until the app restarted (seen on a live install 2026-10-04). Also,
             every poll appended a callback that was never removed.
Inputs     : the FcmReceiver singleton (duck-typed: `_listening`, `_loop`,
             `_loop_thread`, `pc` with `do_listen`, `run_state`, `start()`,
             `sequential_error_counters`; `location_update_callbacks`).
Outputs    : `ensure_listening()` -> "ok" | "restarted" | "relaunch";
             `forget_callback()` drops one poll's callback.
Constraints: Vendor code is never edited (PRI rule 8). Never raises on an
             unexpected receiver shape: it answers "ok" and lets the poll run.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from findplus.logging_setup import get_logger

log = get_logger(__name__)

_STOPPED = ("STOPPING", "STOPPED")
RESTART_TIMEOUT_S = 10.0


def _push_stopped(pc: Any) -> bool:
    state = getattr(getattr(pc, "run_state", None), "name", "")
    return getattr(pc, "do_listen", True) is False or state in _STOPPED


def ensure_listening(receiver: Any) -> str:
    """Restart the push client if it shut itself down; call before registering."""
    if not getattr(receiver, "_listening", False):
        return "ok"  # register_for_location_updates starts it from scratch
    loop = getattr(receiver, "_loop", None)
    thread = getattr(receiver, "_loop_thread", None)
    if loop is None or thread is None or not thread.is_alive() or not loop.is_running():
        receiver._listening = False  # the next registration builds a new loop
        log.warning("push_receiver_relaunch")
        return "relaunch"
    pc = getattr(receiver, "pc", None)
    if pc is None or not _push_stopped(pc):
        return "ok"
    counters = getattr(pc, "sequential_error_counters", None)
    if isinstance(counters, dict):
        counters.clear()
    asyncio.run_coroutine_threadsafe(pc.start(), loop).result(timeout=RESTART_TIMEOUT_S)
    log.warning("push_receiver_restarted")
    return "restarted"


def forget_callback(receiver: Any, callback: Any) -> None:
    """Drop one poll's callback so the list does not grow with every poll."""
    callbacks = getattr(receiver, "location_update_callbacks", None)
    if isinstance(callbacks, list):
        with contextlib.suppress(ValueError):
            callbacks.remove(callback)
