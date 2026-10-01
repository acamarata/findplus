"""poll-now resets the daemon's backoff only when Google actually answered (r1 review #4)."""

from __future__ import annotations

import pytest

from findplus import poller as poller_module
from findplus import poller_service
from findplus.poller_outcomes import CycleOutcome, PollOutcome


def _post(client, monkeypatch, outcomes: list[PollOutcome]) -> int:
    import findplus.api as api_module

    monkeypatch.setattr(api_module, "_last_manual_poll", None)
    resets: list[int] = []
    monkeypatch.setattr(poller_module, "poll_once", lambda *a, **k: CycleOutcome(outcomes))
    monkeypatch.setattr(poller_service, "reset_backoff", lambda: resets.append(1))
    assert client.post("/api/poll-now").status_code == 200
    return len(resets)


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ([PollOutcome("provider_unauthenticated", device_id="a")], 0),
        ([PollOutcome("provider_unavailable", device_id="a")], 0),
        ([PollOutcome("needs_shared_key", device_id="a")], 0),
        ([PollOutcome("timeout", device_id="a"), PollOutcome("error", device_id="b")], 0),
        ([], 0),
        ([PollOutcome("ok", device_id="a"), PollOutcome("error", device_id="b")], 1),
        ([PollOutcome("no_location", device_id="a")], 1),
    ],
)
def test_reset_only_when_google_answered(client, monkeypatch, outcomes, expected) -> None:
    assert _post(client, monkeypatch, outcomes) == expected


def test_reached_google_is_narrower_than_ok() -> None:
    cycle = CycleOutcome([PollOutcome("provider_unauthenticated")])
    assert cycle.ok is True
    assert cycle.reached_google is False
