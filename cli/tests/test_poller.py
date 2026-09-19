"""Poller resilience: failures are recorded, never raised, never fabricated."""

from __future__ import annotations

import pytest
from findplus.findhub.types import (
    AuthRequiredError,
    DecryptionError,
    FindHubError,
    LocationTimeoutError,
)
from sqlalchemy import desc, func, select

from findplus.db.models import LocationObservation, PollRun
from findplus.ingest import upsert_device
from findplus.poller import PollerService, poll_device, poll_once
from findplus.state import track_devices
from tests.conftest import make_observation


class FakeProvider:
    """Stands in for a LocationProvider. Never touches the network."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result if result is not None else []
        self.error = error
        self.calls = 0

    def locate(self, device_id: str, device_name: str):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    def is_available(self) -> tuple[bool, str]:
        return (True, "")

    def is_authenticated(self) -> bool:
        return True

    def authenticate(self, interactive: bool = True) -> str:
        return "ok"

    def describe_auth(self) -> dict:
        return {}

    def list_devices(self) -> list:
        return []


class _UnavailableProvider(FakeProvider):
    def is_available(self) -> tuple[bool, str]:
        return (False, "offline")


class _UnauthedProvider(FakeProvider):
    def is_authenticated(self) -> bool:
        return False


@pytest.fixture
def register_provider(monkeypatch: pytest.MonkeyPatch):
    """Inject a fake provider into the registry, undone automatically after the test."""

    def _register(name: str, provider) -> None:
        from findplus.providers import base

        monkeypatch.setitem(base._REGISTRY, name, provider)

    return _register


@pytest.fixture
def selected(tmp_db):
    from findplus.db.session import session_scope

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2", provider="test-fake")
        track_devices(session, ["TAG-001"], exclusive=True)
    return "TAG-001"


def _last_run():
    from findplus.db.session import session_scope

    with session_scope() as session:
        return session.scalar(select(PollRun).order_by(desc(PollRun.started_at)).limit(1))


def _obs_count() -> int:
    from findplus.db.session import session_scope

    with session_scope() as session:
        return int(session.scalar(select(func.count(LocationObservation.id))) or 0)


def test_successful_poll_stores_observations_and_records_health(
    selected, register_provider
) -> None:
    register_provider(
        "test-fake",
        FakeProvider([make_observation(minutes=0), make_observation(minutes=12, lat=41.2)]),
    )
    cycle = poll_once(stagger_seconds=0)

    assert cycle.ok
    assert cycle.inserted == 2
    assert _obs_count() == 2
    run = _last_run()
    assert run.status == "ok"
    assert run.observations_new == 2
    assert run.duration_ms is not None


def test_repeat_poll_records_health_without_new_points(selected, register_provider) -> None:
    obs = make_observation(minutes=0)
    register_provider("test-fake", FakeProvider([obs]))
    poll_once(stagger_seconds=0)
    cycle = poll_once(stagger_seconds=0)

    assert cycle.ok
    assert cycle.inserted == 0
    assert cycle.duplicates == 1
    assert _obs_count() == 1, "a repeated sighting is not a new location"
    assert _last_run().status == "ok"


def test_empty_response_records_no_location_and_invents_nothing(
    selected, register_provider
) -> None:
    register_provider("test-fake", FakeProvider([]))
    outcome = poll_once(stagger_seconds=0).outcomes[0]
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
    selected, register_provider, error: Exception, expected_status: str
) -> None:
    register_provider("test-fake", FakeProvider(error=error))
    outcome = poll_once(stagger_seconds=0).outcomes[0]  # must not raise
    assert outcome.status == expected_status
    assert outcome.ok is False
    run = _last_run()
    assert run.status == expected_status
    assert run.error_type == type(error).__name__
    assert _obs_count() == 0, "a failed poll must never fabricate a location"


def test_no_tracked_devices_is_an_error_not_a_crash(tmp_db) -> None:
    cycle = poll_once(stagger_seconds=0)
    assert cycle.outcomes[0].status == "error"
    assert cycle.outcomes[0].error_type == "NoDeviceTracked"
    assert _obs_count() == 0


def test_daemon_survives_a_long_run_of_failures(selected, register_provider) -> None:
    register_provider("test-fake", FakeProvider(error=FindHubError("down")))
    for _ in range(10):
        assert poll_once(stagger_seconds=0).ok is False
    with_runs = _last_run()
    assert with_runs.status == "error"


def test_error_messages_are_truncated_before_storage(selected, register_provider) -> None:
    register_provider("test-fake", FakeProvider(error=FindHubError("x" * 9000)))
    poll_once(stagger_seconds=0)
    assert len(_last_run().error_message) <= 2000


def test_two_providers_polled_with_stagger(tmp_db, register_provider) -> None:
    from findplus.db.session import session_scope

    provider_a = FakeProvider([make_observation(device_id="TAG-001")])
    provider_b = FakeProvider([make_observation(device_id="TAG-002")])
    register_provider("test-fake", provider_a)
    register_provider("test-fake-2", provider_b)

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2", provider="test-fake")
        upsert_device(session, "TAG-002", "Moto Tag 3", provider="test-fake-2")
        track_devices(session, ["TAG-001", "TAG-002"], exclusive=True)

    poll_once(stagger_seconds=0)

    assert provider_a.calls == 1
    assert provider_b.calls == 1
    with session_scope() as session:
        run_device_ids = {r.device_id for r in session.scalars(select(PollRun))}
    assert run_device_ids == {"TAG-001", "TAG-002"}


def test_unavailable_provider_records_status(tmp_db, register_provider) -> None:
    from findplus.db.session import session_scope

    register_provider("test-unavailable", _UnavailableProvider())
    register_provider("test-fake", FakeProvider([make_observation(device_id="TAG-002")]))

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2", provider="test-unavailable")
        upsert_device(session, "TAG-002", "Moto Tag 3", provider="test-fake")
        track_devices(session, ["TAG-001", "TAG-002"], exclusive=True)

    cycle = poll_once(stagger_seconds=0)

    by_device = {o.device_id: o for o in cycle.outcomes}
    assert by_device["TAG-001"].status == "provider_unavailable"
    assert by_device["TAG-001"].ok is True
    assert by_device["TAG-002"].status == "ok"
    with session_scope() as session:
        run_device_ids = {r.device_id for r in session.scalars(select(PollRun))}
    assert run_device_ids == {"TAG-001", "TAG-002"}, "other devices are not blocked"
    assert cycle.ok is True, "backoff must not escalate on provider_unavailable"


def test_unauthenticated_provider_records_status(tmp_db, register_provider) -> None:
    from findplus.db.session import session_scope

    register_provider("test-unauthed", _UnauthedProvider())
    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2", provider="test-unauthed")
        track_devices(session, ["TAG-001"], exclusive=True)

    outcome = poll_once(stagger_seconds=0).outcomes[0]
    assert outcome.status == "provider_unauthenticated"
    assert outcome.ok is True


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


def test_success_resets_the_backoff(selected, register_provider) -> None:
    register_provider("test-fake", FakeProvider([make_observation(minutes=0)]))
    service = PollerService()
    service._consecutive_failures = 4
    outcome = poll_once(stagger_seconds=0)
    if outcome.ok:
        service._consecutive_failures = 0
    assert service._next_delay_seconds() == service.settings.effective_poll_interval_minutes * 60


def test_poll_interval_floor_is_five_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards the account against rate-limiting/flagging."""
    from findplus.config import Settings

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
        cycle = poll_once(stagger_seconds=0)
        assert cycle.config_error is True
        if cycle.ok or cycle.config_error:
            service._consecutive_failures = 0
        else:
            service._consecutive_failures += 1

    assert service._next_delay_seconds() == base, "backoff must not grow while unconfigured"


def test_real_failures_still_escalate_backoff(selected, register_provider) -> None:
    register_provider("test-fake", FakeProvider(error=FindHubError("down")))
    service = PollerService()
    base = service.settings.effective_poll_interval_minutes * 60

    for _ in range(3):
        cycle = poll_once(stagger_seconds=0)
        assert cycle.config_error is False
        service._consecutive_failures += 0 if (cycle.ok or cycle.config_error) else 1

    assert service._next_delay_seconds() > base


class _BrokenProbeProvider(FakeProvider):
    """A provider whose availability probe throws instead of returning a flag."""

    def is_available(self) -> tuple[bool, str]:
        raise RuntimeError("vendor tree exploded")


def test_provider_probe_exception_is_recorded_not_raised(selected, register_provider) -> None:
    """A third-party provider's probe is not required to be total; the poller is.

    Regression for the E3 review: is_available()/is_authenticated() raising escaped
    poll_device, killed the PollerService thread, and wrote no poll_runs row.
    """
    register_provider("test-fake", _BrokenProbeProvider())
    cycle = poll_once(stagger_seconds=0)

    assert cycle.ok, "an unusable provider is environment state, not a poll failure"
    run = _last_run()
    assert run.status == "provider_unavailable"
    assert run.error_type == "RuntimeError"
    assert "exploded" in run.error_message


def test_provider_load_failure_is_recorded_not_raised(
    selected, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-installed provider (entry point present, module missing) must not crash."""
    import findplus.poller as poller_module

    def _boom(name: str):
        raise ImportError(f"no module for entry point {name!r}")

    monkeypatch.setattr(poller_module, "get_provider", _boom)
    cycle = poll_once(stagger_seconds=0)

    assert cycle.ok
    run = _last_run()
    assert run.status == "provider_unavailable"
    assert run.error_type == "ImportError"


def test_unknown_provider_still_reports_unknown_provider(selected, register_provider) -> None:
    """KeyError keeps its dedicated error_type; only other exceptions are generic."""
    from findplus.db.session import session_scope

    with session_scope() as session:
        upsert_device(session, "TAG-001", "Moto Tag 2", provider="test-fake")
    register_provider("something-else", FakeProvider())
    cycle = poll_once(stagger_seconds=0)

    assert cycle.ok
    assert _last_run().error_type == "unknown_provider"


def test_device_first_seen_through_a_poll_keeps_its_reporting_provider(
    tmp_db, register_provider
) -> None:
    """A device first seen through ingest is tagged with the provider that reported it.

    Regression for the E3 review: ingest_observations called upsert_device without
    a provider, so any device discovered by a poll (rather than by `devices
    --refresh`) was recorded as google-find-hub whatever reported it.
    """
    import dataclasses

    from findplus.db.models import Device
    from findplus.db.session import session_scope

    obs = dataclasses.replace(make_observation(minutes=0), provider="test-fake")
    with session_scope() as session:
        assert session.get(Device, "TAG-001") is None, "no device row exists yet"

    register_provider("test-fake", FakeProvider([obs]))
    assert poll_device("TAG-001", "Moto Tag 2", "test-fake").status == "ok"

    with session_scope() as session:
        assert session.get(Device, "TAG-001").provider == "test-fake"
