"""The unlock job outlives the flow's own deadline, so MSG_TIMEOUT can show (r1 review #3)."""

from __future__ import annotations

import time

import pytest

from findplus.providers.google_findhub import unlock, unlock_flow


@pytest.fixture(autouse=True)
def _clear_jobs():
    unlock._jobs.clear()
    unlock._active_job_id = None
    yield
    unlock._jobs.clear()
    unlock._active_job_id = None


def test_sweep_threshold_is_longer_than_the_flow_deadline() -> None:
    assert unlock._STALLED_SECONDS > unlock_flow._TOTAL_SECONDS


def test_a_job_waiting_past_ten_minutes_is_not_swept() -> None:
    now = time.monotonic()
    unlock._jobs["j"] = {
        "state": "waiting_for_user",
        "message": unlock.MSG_WAITING,
        "finished_monotonic": None,
        "last_progress_monotonic": now - 700,  # old 600 s limit would have swept it
        "cancelled": False,
        "driver": None,
    }
    unlock._active_job_id = "j"
    assert unlock.get_google_unlock_progress("j")["state"] == "waiting_for_user"


def test_a_flow_timeout_surfaces_the_open_too_long_message(tmp_db, monkeypatch) -> None:
    from findplus.config import get_settings
    from tests.providers._google_token_helpers import isolate_store

    isolate_store(monkeypatch)

    def flow(*_a, **_k):
        raise unlock_flow.FlowTimeoutError("late")

    monkeypatch.setattr(unlock_flow, "run_shared_key_flow", flow)
    monkeypatch.setattr(unlock, "_wake_poller", lambda: None)
    job_id = unlock.start_google_unlock(get_settings())
    deadline = time.monotonic() + 3
    progress = None
    while time.monotonic() < deadline:
        progress = unlock.get_google_unlock_progress(job_id)
        if progress and progress["state"] == "failed":
            break
        time.sleep(0.02)
    assert progress == {"state": "failed", "message": unlock.MSG_TIMEOUT}
