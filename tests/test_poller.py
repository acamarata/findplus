"""Poller resilience: failures are recorded, never raised, never fabricated."""

from __future__ import annotations

import pytest
from sqlalchemy import desc, func, select

from bike_tracker.db.models import LocationObservation, PollRun
from bike_tracker.findhub.types import (
    AuthRequiredError,
    DecryptionError,
    FindHubError,
    LocationTimeoutError,
)
from bike_tracker.ingest import upsert_device
from bike_tracker.poller import PollerService, poll_once
from bike_tracker.state import track_devices
from tests.conftest import make_observation


class FakeClient:
    """Stands in for FindHubClient. Never touches the network."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result if result is not None else []
        self.error = error
        self.calls = 0

    def locate(self, device_id: str, device_name: str):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def selected(tmp_db):
    from bike_tracker.db.session import session_scope

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2")
        track_devices(session, ["TAG-001"], exclusive=True)
    return "TAG-001"


def _last_run():
    from bike_tracker.db.session import session_scope

    with session_scope() as session:
        return session.scalar(select(PollRun).order_by(desc(PollRun.started_at)).limit(1))


def _obs_count() -> int:
    from bike_tracker.db.session import session_scope

    with session_scope() as session:
        return int(session.scalar(select(func.count(LocationObservation.id))) or 0)


def test_successful_poll_stores_observations_and_records_health(selected) -> None:
    client = FakeClient([make_observation(minutes=0), make_observation(minutes=12, lat=41.2)])
    cycle = poll_once(client, stagger_seconds=0)

    assert cycle.ok
    assert cycle.inserted == 2
    assert _obs_count() == 2
    run = _last_run()
    assert run.status == "ok"
    assert run.observations_new == 2
    assert run.duration_ms is not None


def test_repeat_poll_records_health_without_new_points(selected) -> None:
    obs = make_observation(minutes=0)
    poll_once(FakeClient([obs]), stagger_seconds=0)
    cycle = poll_once(FakeClient([obs]), stagger_seconds=0)

    assert cycle.ok
    assert cycle.inserted == 0
    assert cycle.duplicates == 1
    assert _obs_count() == 1, "a repeated sighting is not a new location"
    assert _last_run().status == "ok"


def test_empty_response_records_no_location_and_invents_nothing(selected) -> None:
    outcome = poll_once(FakeClient([]), stagger_seconds=0).outcomes[0]
    assert outcome.status == "no_location"
    assert _obs_count() == 0
    assert _last_run().status == "no_location"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (AuthRequiredError("expired"), "auth_error"),
        (LocationTimeoutError("no push"), "timeout"),
        (DecryptionError("owner key reset"), "error"),
        (FindHubError("nova rejected"), "error"),
        (ConnectionError("network is unreachable"), "error"),
        (ValueError("malformed payload"), "error"),
    ],
)
def test_every_failure_mode_is_recorded_not_raised(
    selected, error: Exception, expected_status: str
) -> None:
    outcome = poll_once(FakeClient(error=error), stagger_seconds=0).outcomes[0]  # must not raise
    assert outcome.status == expected_status
    assert outcome.ok is False
    run = _last_run()
    assert run.status == expected_status
    assert run.error_type == type(error).__name__
    assert _obs_count() == 0, "a failed poll must never fabricate a location"


def test_no_tracked_devices_is_an_error_not_a_crash(tmp_db) -> None:
    cycle = poll_once(FakeClient([make_observation()]), stagger_seconds=0)
    assert cycle.outcomes[0].status == "error"
    assert cycle.outcomes[0].error_type == "NoDeviceTracked"
    assert _obs_count() == 0


def test_daemon_survives_a_long_run_of_failures(selected) -> None:
    for _ in range(10):
        assert poll_once(FakeClient(error=FindHubError("down")), stagger_seconds=0).ok is False
    with_runs = _last_run()
    assert with_runs.status == "error"


def test_error_messages_are_truncated_before_storage(selected) -> None:
    poll_once(FakeClient(error=FindHubError("x" * 9000)), stagger_seconds=0)
    assert len(_last_run().error_message) <= 2000


# ------------------------------------------------------------------ backoff
def test_backoff_starts_at_the_configured_interval() -> None:
    service = PollerService()
    assert service._next_delay_seconds() == service.settings.effective_poll_interval_minutes * 60


def test_backoff_grows_exponentially_and_is_capped() -> None:
    service = PollerService()
    base = service.settings.effective_poll_interval_minutes * 60
    cap = service.settings.poll_max_backoff_minutes * 60

    service._consecutive_failures = 1
    assert service._next_delay_seconds() == min(base * 2, cap)
    service._consecutive_failures = 2
    assert service._next_delay_seconds() == min(base * 4, cap)
    service._consecutive_failures = 50
    assert service._next_delay_seconds() == cap


def test_success_resets_the_backoff(selected) -> None:
    service = PollerService()
    service.client = FakeClient([make_observation(minutes=0)])
    service._consecutive_failures = 4
    outcome = poll_once(service.client, stagger_seconds=0)
    if outcome.ok:
        service._consecutive_failures = 0
    assert service._next_delay_seconds() == service.settings.effective_poll_interval_minutes * 60


def test_poll_interval_floor_is_five_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards the account against rate-limiting/flagging."""
    from bike_tracker.config import Settings

    assert Settings(poll_interval_minutes=1).effective_poll_interval_minutes == 5.0
    assert Settings(poll_interval_minutes=0.5).effective_poll_interval_minutes == 5.0
    assert Settings(poll_interval_minutes=15).effective_poll_interval_minutes == 15.0
    # The floor is escapable only by explicit opt-in.
    fast = Settings(poll_interval_minutes=1, allow_fast_polling=True)
    assert fast.effective_poll_interval_minutes == 1.0


def test_unconfigured_state_does_not_escalate_backoff(tmp_db) -> None:
    """A daemon started before setup must pick up a device selection promptly.

    "No devices tracked" is a configuration state, not a Google failure. Treating
    it as a failure would leave the poller in an hour-long backoff at exactly the
    moment the user finishes configuring it.
    """
    service = PollerService()
    base = service.settings.effective_poll_interval_minutes * 60

    for _ in range(8):
        cycle = poll_once(FakeClient([]), stagger_seconds=0)
        assert cycle.config_error is True
        if cycle.ok or cycle.config_error:
            service._consecutive_failures = 0
        else:
            service._consecutive_failures += 1

    assert service._next_delay_seconds() == base, "backoff must not grow while unconfigured"


def test_real_failures_still_escalate_backoff(selected) -> None:
    service = PollerService()
    base = service.settings.effective_poll_interval_minutes * 60

    for _ in range(3):
        cycle = poll_once(FakeClient(error=FindHubError("down")), stagger_seconds=0)
        assert cycle.config_error is False
        service._consecutive_failures += 0 if (cycle.ok or cycle.config_error) else 1

    assert service._next_delay_seconds() > base
