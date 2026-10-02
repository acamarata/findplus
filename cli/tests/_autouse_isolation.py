"""Autouse isolation fixtures shared by the whole suite (imported by conftest.py).

Split out of conftest.py at the 300-line cap; behaviour is unchanged.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clear_poller_flag_files() -> None:
    """Remove the cross-process wake/reset flag files a test may have left behind.

    `wake_poller()` / `reset_backoff()` from a process with no poll loop leave a
    file the next loop would consume, which would end an unrelated test's sleep.
    """
    from findplus.config import get_settings

    for name in ("wake", "reset"):
        (get_settings().state_dir / f"poller.{name}").unlink(missing_ok=True)
    yield


@pytest.fixture(autouse=True)
def _isolate_bind_env_vars() -> None:
    """Undo whatever a test's `serve --host/--port` invocation exported.

    `_bind_or_exit` (cmd_serve.py, CF-P2-3) writes FINDPLUS_HOST/FINDPLUS_PORT
    straight into `os.environ` on purpose -- OriginGuardMiddleware calls
    `get_settings()` fresh on every request, so a `--port` override has to
    reach it that way, and that is production behavior this suite must not
    weaken. But `os.environ` is not test-scoped like `monkeypatch.setenv` is:
    any test that runs `serve`/`cmd_service.serve` through Click's CliRunner
    (test_sigterm.py's `--port 8641` case, not through `_bind_or_exit`
    directly the way test_serve_exclusive.py's own dedicated cases restore
    it) leaves that value set for every test that runs afterward in the same
    process. Every later `client` fixture still hard-codes Host 127.0.0.1:8647
    (LOOPBACK_BASE_URL below), so the leaked port mismatches it and
    OriginGuardMiddleware refuses the request with 421 -- ~90 unrelated
    failures across test_api*.py, test_multi_device_api.py and others,
    order-dependent on whichever test ran last (CF-P2-3 follow-up, 2026-09-22).
    One autouse fixture here, rather than a fix in that one test file, so any
    other direct os.environ write -- present or future -- gets the same snapshot/restore.
    """
    before_port = os.environ.get("FINDPLUS_PORT")
    before_host = os.environ.get("FINDPLUS_HOST")
    try:
        yield
    finally:
        if before_port is None:
            os.environ.pop("FINDPLUS_PORT", None)
        else:
            os.environ["FINDPLUS_PORT"] = before_port
        if before_host is None:
            os.environ.pop("FINDPLUS_HOST", None)
        else:
            os.environ["FINDPLUS_HOST"] = before_host


@pytest.fixture(autouse=True)
def _replay_on_this_thread(monkeypatch) -> None:
    """Saving a place or accepting people replays past days (people/replay.py).
    In tests it runs on the calling thread, so no replay outlives its test
    database or races the assertions that follow."""
    monkeypatch.setenv("FINDPLUS_REPLAY_SYNC", "1")
    yield
