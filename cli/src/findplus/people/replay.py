"""Fill in past days after people or places change, in the background (uat116 #4).

Purpose : History polled before a person or a place existed has no arrive or
          leave lines: the engines only ran on what existed at ingest time. Once
          people are accepted, a place is saved (or moved), or a database from
          before 1.1.6 is first served, this runs the same replay as
          `findplus db rebuild-derived` on a background thread, so every past
          day reads right. GET /api/people/replay reports {state, done, total}
          so the dashboard can say "Updating past days...".
Inputs  : `request(reason)` from the routes and the serve start-up; Settings.
Outputs : Rebuilt derived tables (db/rebuild.py); the status dict.
Constraints: Nothing is sent: every rebuilt event is stamped notified (and the
          alert gates never send history anyway). Before the derived tables are
          emptied, anything already pending is dispatched, so a live alert is
          never swallowed. Live ingest waits on INGEST_LOCK while a replay runs
          (ingest.py takes it), because a newer live sighting would close the
          backfill guard on the older ones being replayed. One replay at a
          time; a request during a run queues exactly one more run. Nothing
          runs when there is no person, no place or no sighting.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from findplus.logging_setup import get_logger

log = get_logger(__name__)

#: Held by a replay for its whole run, and by every live ingest batch.
INGEST_LOCK = threading.RLock()
#: Setting stamped once the 1.1.6 upgrade replay has been queued.
UPGRADE_KEY = "people.replay_version"
UPGRADE_VERSION = "1.1.6"
#: "1" runs a requested replay on the caller's thread (the test suite sets it).
SYNC_ENV = "FINDPLUS_REPLAY_SYNC"

_guard = threading.Lock()
_status: dict[str, Any] = {"state": "idle", "done": 0, "total": 0, "reason": None}
_thread: threading.Thread | None = None
_again: str | None = None


def status() -> dict[str, Any]:
    """{state: idle|running|done|failed, done, total, reason}."""
    with _guard:
        return dict(_status)


def _worth_it(session) -> bool:
    from sqlalchemy import exists, select

    from findplus.db.models import Group, LocationObservation, Place
    from findplus.db.models_people import PERSON_KINDS

    person = select(Group.id).where(Group.kind.in_(PERSON_KINDS))
    return bool(
        session.scalar(select(exists(person)))
        and session.scalar(select(exists(select(Place.id))))
        and session.scalar(select(exists(select(LocationObservation.id))))
    )


def request(reason: str) -> dict[str, Any]:
    """Queue a replay (or one more, if one is running). Never blocks the caller."""
    global _thread, _again
    from findplus.db.session import session_scope

    with session_scope() as s:
        if not _worth_it(s):
            return status()
    if os.environ.get(SYNC_ENV) == "1":  # tests: the same work, on this thread
        with _guard:
            _status.update(state="running", done=0, total=0, reason=reason)
        _run(reason)
        return status()
    with _guard:
        if _thread is not None and _thread.is_alive():
            _again = reason
            return dict(_status)
        _status.update(state="running", done=0, total=0, reason=reason)
        _thread = threading.Thread(target=_run, args=(reason,), name="replay", daemon=True)
        _thread.start()
        return dict(_status)


def wait(timeout: float | None = None) -> None:
    """Block until the current replay (and any queued one) is finished. Tests use it."""
    thread = _thread
    if thread is not None:
        thread.join(timeout)


def _progress(done: int, total: int) -> None:
    with _guard:
        _status.update(done=done, total=total)


def _run(reason: str) -> None:
    global _again
    while True:
        try:
            with INGEST_LOCK:
                _replay_once()
            state = "done"
        except Exception as exc:  # a failed replay leaves history as it was; say so
            log.warning("replay_failed", reason=reason, error=type(exc).__name__)
            state = "failed"
        with _guard:
            if _again is None:
                _status.update(state=state)
                return
            reason, _again = _again, None
            _status.update(state="running", done=0, total=0, reason=reason)


def _replay_once() -> None:
    from findplus.alerts import dispatch
    from findplus.config import get_settings
    from findplus.db.rebuild import rebuild_derived
    from findplus.db.session import session_scope

    settings = get_settings()
    with session_scope() as s:
        # Anything still pending is live news: send it before the tables are emptied.
        dispatch.process(dispatch.load_pending_events(s), s, settings)
    with session_scope() as s:
        result = rebuild_derived(s, settings, progress=_progress)
    log.info("replay_done", observations=result.observations, group_events=result.group_events)


def on_start() -> None:
    """Serve start-up: a database from before 1.1.6 gets its past days filled in
    once. Never raises: the CLI's `db rebuild-derived` still does it by hand."""
    from findplus.db.session import session_scope
    from findplus.state import get_setting, set_setting

    try:
        with session_scope() as s:
            if get_setting(s, UPGRADE_KEY) == UPGRADE_VERSION:
                return
            set_setting(s, UPGRADE_KEY, UPGRADE_VERSION)
        request("upgrade")
    except Exception as exc:  # never stop the server over it
        log.warning("replay_on_start_failed", error=type(exc).__name__)
