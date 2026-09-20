"""The daily retention job (P2-E7-W2-S1-T5).

Purpose    : Pin specs/service-and-settings.md § 5 -- retention off is a no-op,
             retention on deletes only history older than the cutoff, and
             configuration rows are never touched at any age. Also pins the
             scheduler's cadence: one run at once, the next only after the
             24-hour wait.
Inputs     : A tmp_db seeded with old and recent rows in each of the three
             history tables plus a device, a place and a group.
Outputs    : pytest assertions on RetentionResult and on what survives.
Constraints: Never touches the real ~/.findplus or the network; the 24-hour
             wait is always mocked, never slept through.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from findplus.config import get_settings, write_config_key
from findplus.db.models import (
    Device,
    Group,
    GroupPlaceEvent,
    LocationObservation,
    Place,
    PlaceEvent,
)
from findplus.db.session import session_scope
from findplus.ingest import upsert_device
from findplus.service.retention import (
    RUN_INTERVAL_SECONDS,
    RetentionScheduler,
    run_once,
)

OLD = datetime.now(UTC) - timedelta(days=90)
RECENT = datetime.now(UTC) - timedelta(days=1)


def _seed() -> None:
    """One old and one recent row per history table, plus three config rows."""
    now = datetime.now(UTC)
    with session_scope() as session:
        upsert_device(session, "TAG-1", "Keys")
        place = Place(
            name="Home",
            latitude_e7=1,
            longitude_e7=2,
            radius_meters=100,
            created_at=now,
            updated_at=now,
        )
        group = Group(name="Family", created_at=now)
        session.add_all([place, group])
        session.flush()
        place_id, group_id = place.id, group.id

        for when in (OLD, RECENT):
            observation = LocationObservation(
                device_id="TAG-1",
                device_name="Keys",
                latitude_e7=1,
                longitude_e7=2,
                observed_at=when,
                first_fetched_at=when,
                last_fetched_at=when,
                source="test",
            )
            session.add(observation)
            session.flush()
            session.add(
                PlaceEvent(
                    place_id=place_id,
                    device_id="TAG-1",
                    event_type="ENTER",
                    observed_at=when,
                    fetched_at=when,
                    observation_id=observation.id,
                    confidence="high",
                    distance_meters=1.0,
                    accuracy_meters=5.0,
                )
            )
            session.add(
                GroupPlaceEvent(
                    group_id=group_id,
                    place_id=place_id,
                    event_type="ENTER",
                    observed_at=when,
                    member_event_ids="[]",
                    members_crossed=1,
                    members_considered=1,
                    members_stale=0,
                )
            )


def _counts() -> tuple[int, int, int]:
    with session_scope() as session:
        return (
            session.query(LocationObservation).count(),
            session.query(PlaceEvent).count(),
            session.query(GroupPlaceEvent).count(),
        )


def _config_rows() -> tuple[int, int, int]:
    with session_scope() as session:
        return (
            session.query(Device).count(),
            session.query(Place).count(),
            session.query(Group).count(),
        )


# ------------------------------------------------------------------ disabled
def test_retention_off_is_a_no_op(tmp_db) -> None:
    _seed()

    result = run_once()

    assert result.ran is False
    assert result.cutoff is None
    assert (
        result.observations_deleted,
        result.place_events_deleted,
        result.group_place_events_deleted,
    ) == (0, 0, 0)
    assert _counts() == (2, 2, 2)


# -------------------------------------------------------------------- enabled
def test_prunes_only_history_older_than_the_cutoff(tmp_db) -> None:
    _seed()
    write_config_key(get_settings(), "RETENTION_DAYS", "7")

    result = run_once()

    assert result.ran is True
    assert result.cutoff is not None
    assert (
        result.observations_deleted,
        result.place_events_deleted,
        result.group_place_events_deleted,
    ) == (1, 1, 1)
    assert _counts() == (1, 1, 1)


def test_configuration_rows_are_never_touched(tmp_db) -> None:
    _seed()
    write_config_key(get_settings(), "RETENTION_DAYS", "7")

    run_once()

    assert _config_rows() == (1, 1, 1)


def test_the_surviving_rows_are_the_recent_ones(tmp_db) -> None:
    _seed()
    write_config_key(get_settings(), "RETENTION_DAYS", "7")

    run_once()

    with session_scope() as session:
        left = session.query(LocationObservation).one()
        assert left.observed_at > datetime.now(UTC) - timedelta(days=7)


def test_a_retention_change_applies_without_a_restart(tmp_db) -> None:
    """run_once re-reads settings, unlike PollerService's held copy."""
    _seed()
    assert run_once().ran is False

    write_config_key(get_settings(), "RETENTION_DAYS", "7")

    assert run_once().ran is True


# ------------------------------------------------------------------- cadence
def test_scheduler_runs_once_immediately_then_after_the_wait(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs: list[object] = []
    waits: list[float] = []
    monkeypatch.setattr(
        "findplus.service.retention.run_once", lambda state_dir=None: runs.append(state_dir)
    )

    scheduler = RetentionScheduler()

    def _wait(self, timeout=None):
        waits.append(timeout)
        # First tick: keep going. Second: report the stop and end the loop.
        return len(waits) >= 2

    monkeypatch.setattr(threading.Event, "wait", _wait)
    monkeypatch.setattr(threading.Event, "is_set", lambda self: len(waits) >= 2)

    scheduler.run_forever()

    assert len(runs) == 2
    assert waits == [RUN_INTERVAL_SECONDS, RUN_INTERVAL_SECONDS]


def test_stop_ends_the_loop(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[object] = []
    monkeypatch.setattr(
        "findplus.service.retention.run_once", lambda state_dir=None: runs.append(state_dir)
    )
    scheduler = RetentionScheduler()
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: True)

    scheduler.stop()
    scheduler.run_forever()

    assert runs == []
