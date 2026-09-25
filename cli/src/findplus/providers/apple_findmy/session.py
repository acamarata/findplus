# Purpose: drive FindMy.py's async Apple account from Find+'s synchronous code
#          (CLI prompts, the poller thread, the dashboard's sign-in job).
# Inputs: a findmy.AsyncAppleAccount; coroutines from its public methods.
# Outputs: AppleSession.run() -> the coroutine's result; honest errors for an
#          anisette provider that cannot start.
# Constraints: no findmy import at module level (the optional `apple` extra may
#              be absent). One event loop per session, so a sign-in that spans
#              two HTTP requests (login, then the 2FA code) keeps the same
#              aiohttp session. Calls on one session are serialised.
"""One Apple account plus the event loop that drives it."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["AppleAnisetteError", "AppleSession", "prepare_anisette"]

#: Where FindMy.py's local anisette engine fetches its helper libraries on
#: first use (anisette.anisette.DEFAULT_LIBS_URL in anisette 1.2.x).
LOCAL_ANISETTE_HOST = "anisette.dl.mikealmel.ooo"


class AppleAnisetteError(Exception):
    """The anisette provider could not produce the headers Apple requires."""


class AppleSession:
    """A findmy AsyncAppleAccount and a private event loop to run it on.

    FindMy.py 0.10 is async-first; its sync AppleAccount binds whatever loop is
    current at construction and never closes it. Owning the loop here lets
    close() release the account's HTTP sessions and the loop itself.
    """

    def __init__(self, account: Any) -> None:
        self.account = account
        self._loop = asyncio.new_event_loop()
        self._lock = threading.Lock()

    def run(self, awaitable: Any) -> Any:
        """Run one coroutine to completion on this session's loop."""
        with self._lock:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return self._loop.run_until_complete(awaitable)
            # Called from inside a running loop: run_until_complete would refuse,
            # so hand the work to a short-lived thread and wait for it.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(self._loop.run_until_complete, awaitable).result()

    def close(self) -> None:
        """Close the account's sessions and the loop. Safe to call twice."""
        if self._loop.is_closed() or self._loop.is_running():
            return
        try:
            self.run(self.account.close())
        except Exception as exc:  # closing must never mask the real outcome
            log.debug("apple session close failed: %s", exc)
        finally:
            self._loop.close()

    def __enter__(self) -> AppleSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def prepare_anisette(session: AppleSession, settings: Any) -> None:
    """Start the anisette provider before any credential is sent to Apple.

    The local provider downloads helper libraries on first use and then
    provisions a virtual device with Apple; a remote one needs its server to
    answer. Either can fail for reasons that have nothing to do with the Apple
    ID, so the failure is named here instead of surfacing mid-login.
    """
    try:
        session.run(session.account.get_anisette_headers())
    except Exception as exc:
        url = getattr(settings, "apple_anisette_url", None)
        if url:
            msg = (
                f"Could not reach the anisette server at {url}. "
                "Check the APPLE_ANISETTE_URL setting."
            )
        else:
            msg = (
                "Local anisette could not start. On first use it downloads helper "
                f"libraries from {LOCAL_ANISETTE_HOST}; check your connection, or "
                "run: findplus config set APPLE_ANISETTE_URL <server>"
            )
        raise AppleAnisetteError(f"{msg} ({type(exc).__name__}: {exc})"[:300]) from exc
