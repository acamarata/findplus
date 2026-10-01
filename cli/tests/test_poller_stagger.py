"""The stagger waits only after a device that really reached Google (UAT finding 0).

Signed out, every device stops at a local check and sends nothing, so a 10 s gap
after each made Poll Now hang for minutes with 17 trackers.
"""

from __future__ import annotations

import time

import pytest

from findplus import poller
from findplus.poller_outcomes import PollOutcome

TARGETS = [(f"d{i}", f"Tag {i}", "google-find-hub") for i in range(4)]


def _run(monkeypatch: pytest.MonkeyPatch, status: str) -> float:
    monkeypatch.setattr(
        poller,
        "poll_device",
        lambda device_id, name, provider, settings: PollOutcome(status, device_id, name),
    )
    monkeypatch.setattr(poller, "_process_alert_retries", lambda settings: None)
    start = time.monotonic()
    cycle = poller._run_poll_cycle(TARGETS, settings=None, stagger=1.0, stop_event=None)
    assert len(cycle.outcomes) == len(TARGETS)
    return time.monotonic() - start


@pytest.mark.parametrize(
    "status", ["provider_unauthenticated", "provider_unavailable", "needs_shared_key"]
)
def test_no_gap_after_a_device_that_sent_nothing(monkeypatch, status) -> None:
    assert _run(monkeypatch, status) < 0.5


def test_the_gap_stays_between_real_google_requests(monkeypatch) -> None:
    assert _run(monkeypatch, "ok") >= 2.9  # three gaps of one second
