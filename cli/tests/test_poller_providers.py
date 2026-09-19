"""Provider resolution inside the poll loop (E3).

Every provider failure — an unknown name, an entry point that will not load, a
probe that raises, an unavailable or unauthenticated provider — must become a
recorded `poll_runs` row, never an exception out of `poll_device`. Split out of
test_poller.py, which was 416 lines (PRI hard rule 7 applies to test files).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from findplus.db.models import PollRun
from findplus.ingest import upsert_device
from findplus.poller import poll_device, poll_once
from findplus.state import track_devices
from tests.conftest import make_observation
from tests.poller_fakes import (
    FakeProvider,
    _last_run,
    _obs_count,
    _UnauthedProvider,
    _UnavailableProvider,
)


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


def test_poll_device_never_raises_when_an_ingest_hook_fails(
    selected, register_provider, monkeypatch
) -> None:
    """poll_device's "never raises" contract covers the post-ingest hooks too.

    A geofence (or, later, groups/alerts) hook that blows up must not roll back
    the observations or escape as an exception: the fixes are irreplaceable and
    the poll attempt still has to be recorded.
    """

    def boom(_session, _lo):
        raise RuntimeError("hook exploded")

    monkeypatch.setattr("findplus.ingest._geofence_evaluate", boom)
    register_provider("test-fake", FakeProvider([make_observation(minutes=0)]))

    outcome = poll_device("TAG-001", "Moto Tag 2", provider_name="test-fake")

    assert outcome.status == "ok"
    assert outcome.inserted == 1
    assert _obs_count() == 1
    assert _last_run().status == "ok"
