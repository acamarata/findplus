"""Part 3: the unlock job runs the vendored key flow in Find+'s own Chrome.

Purpose    : start/progress/cancel of providers/google_findhub/unlock.py, the
             stored `shared_key` (0600, never logged), the already-running
             guard, and that the blocked create_driver is re-armed when the job
             ends. The vendored `request_shared_key_flow` is faked, so no
             browser is ever opened.
Constraints: No real ~/.findplus, no network, no Chrome.
"""

from __future__ import annotations

import json
import logging
import stat
import threading
import time

import pytest

from findplus.providers.google_findhub import unlock
from findplus.providers.google_findhub.types import BrowserLaunchBlockedError
from tests.providers._google_token_helpers import isolate_store

SHARED_KEY_HEX = "deadbeefcafef00d"


def _wait_terminal(job_id: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        progress = unlock.get_google_unlock_progress(job_id)
        if progress and progress["state"] in ("done", "failed"):
            return progress
        time.sleep(0.02)
    raise AssertionError("unlock job never reached a terminal state")


def _fake_flow(monkeypatch, result=SHARED_KEY_HEX, block: threading.Event | None = None):
    from findplus.providers.google_findhub import unlock_flow

    def flow(*_args, **_kwargs):
        if block is not None:
            block.wait(3)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(unlock_flow, "run_shared_key_flow", flow)


@pytest.fixture(autouse=True)
def _clear_jobs():
    unlock._jobs.clear()
    unlock._active_job_id = None
    yield
    unlock._jobs.clear()
    unlock._active_job_id = None


def test_a_successful_unlock_stores_the_key_0600_and_never_logs_it(
    tmp_db, monkeypatch, caplog
) -> None:
    store = isolate_store(monkeypatch)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"aas_token": "x", "username": "a@b.com"}))
    _fake_flow(monkeypatch)
    caplog.set_level(logging.DEBUG)
    from findplus.config import get_settings

    job_id = unlock.start_google_unlock(get_settings())
    progress = _wait_terminal(job_id)

    assert progress["state"] == "done"
    data = json.loads(store.read_text())
    assert data["shared_key"] == SHARED_KEY_HEX
    assert SHARED_KEY_HEX not in caplog.text


@pytest.mark.posix_only
def test_the_stored_key_is_0600(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"aas_token": "x", "username": "a@b.com"}))
    _fake_flow(monkeypatch)
    from findplus.config import get_settings

    _wait_terminal(unlock.start_google_unlock(get_settings()))
    assert stat.S_IMODE(store.stat().st_mode) == 0o600


def test_the_blocked_create_driver_is_re_armed_when_the_job_ends(tmp_db, monkeypatch) -> None:
    isolate_store(monkeypatch)
    _fake_flow(monkeypatch)
    from findplus.config import get_settings

    _wait_terminal(unlock.start_google_unlock(get_settings()))
    import chrome_driver

    with pytest.raises(BrowserLaunchBlockedError):
        chrome_driver.create_driver()


def test_an_empty_result_is_a_friendly_failure(tmp_db, monkeypatch) -> None:
    store = isolate_store(monkeypatch)
    _fake_flow(monkeypatch, result="")
    from findplus.config import get_settings

    progress = _wait_terminal(unlock.start_google_unlock(get_settings()))
    assert progress["state"] == "failed"
    assert unlock.MSG_NO_KEY in progress["message"]
    stored = json.loads(store.read_text()) if store.exists() else {}
    assert "shared_key" not in stored


def test_a_second_unlock_while_one_runs_is_refused(tmp_db, monkeypatch) -> None:
    isolate_store(monkeypatch)
    gate = threading.Event()
    _fake_flow(monkeypatch, block=gate)
    from findplus.config import get_settings

    first = unlock.start_google_unlock(get_settings())
    try:
        with pytest.raises(unlock.GoogleUnlockAlreadyRunningError) as caught:
            unlock.start_google_unlock(get_settings())
        assert caught.value.job_id == first
    finally:
        gate.set()
    _wait_terminal(first)


def test_cancel_ends_the_job(tmp_db, monkeypatch) -> None:
    isolate_store(monkeypatch)
    gate = threading.Event()
    _fake_flow(monkeypatch, block=gate)
    from findplus.config import get_settings

    job_id = unlock.start_google_unlock(get_settings())
    try:
        assert unlock.cancel_google_unlock(job_id) is True
        progress = unlock.get_google_unlock_progress(job_id)
        assert progress["state"] == "failed"
        assert progress["message"] == unlock.MSG_CANCELLED
    finally:
        gate.set()


def test_cancel_of_an_unknown_job_is_false(tmp_db) -> None:
    assert unlock.cancel_google_unlock("nope") is False


def test_progress_of_an_unknown_job_is_none(tmp_db) -> None:
    assert unlock.get_google_unlock_progress("nope") is None
