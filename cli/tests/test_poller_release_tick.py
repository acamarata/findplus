"""Every poll cycle releases quality holds that ran out, even when nothing new came in.

Review 2026-10-02 #5: a held arrival waited for some later ingest, and an
empty batch returns before the hooks, so a tracker that went quiet after a far
fix never got its ENTER.
"""

from __future__ import annotations

import pytest

from findplus import poller
from findplus.poller_outcomes import PollOutcome

TARGETS = [("d1", "Tag 1", "google-find-hub")]


def _cycle(monkeypatch: pytest.MonkeyPatch, release) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(
        poller,
        "poll_device",
        lambda device_id, name, provider, settings: PollOutcome("no_location", device_id, name),
    )
    monkeypatch.setattr(poller, "_process_alert_retries", lambda settings: None)
    monkeypatch.setattr(poller, "release_held_fixes", release)
    monkeypatch.setattr(poller, "_dispatch_alerts", lambda settings, name: sent.append(name))
    poller._run_poll_cycle(TARGETS, settings=None, stagger=0, stop_event=None)
    return sent


def test_a_cycle_with_no_new_fixes_still_releases_and_alerts(monkeypatch) -> None:
    calls: list[object] = []

    def release(session, settings=None):
        calls.append(session)
        return 1

    assert _cycle(monkeypatch, release) == ["held sightings"]
    assert len(calls) == 1


def test_nothing_released_sends_nothing(monkeypatch) -> None:
    assert _cycle(monkeypatch, lambda session, settings=None: 0) == []


def test_a_failing_release_never_breaks_the_cycle(monkeypatch) -> None:
    def boom(session, settings=None):
        raise RuntimeError("scoring bug")

    assert _cycle(monkeypatch, boom) == []
