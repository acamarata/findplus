"""cli/src/findplus/groups/events.py -- group quorum firing at ingest time (integration).

Covers the E6 CR-C finding: nothing populated group_place_events, so group
alert rules could never fire. These are the ingest.py wiring tests (the hook
never loses the observation batch when it raises, and a poll's ingest+dispatch
are visible in the same cycle). Unit-level evaluate_group_events() coverage
(deterministic `now`, no ingest/poll) split out to test_events_quorum.py
(PRI rule 7, <=300 lines/file). Shared seed/builder helpers in _helpers.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from findplus.db.models import GroupPlaceEvent, LocationObservation, PlaceEvent, PlaceState
from findplus.ingest import ingest_observations

from ._helpers import T0, _add_fix, _raw_obs, _seed_group


def test_hook_failure_never_loses_the_batch(session, monkeypatch):
    """A raising group hook must not roll back the observation it ran on.

    Seeds `a` as already "outside" so the next fix is a real geofence ENTER
    (a first-ever fix only seeds state, per geofence.advance -- it never
    fires an event), which is what makes the group hook actually run.
    """
    _group, place = _seed_group(session)
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="a",
            state="outside",
            streak=0,
            streak_side=None,
            since_observed_at=None,
            last_observation_id=None,
            updated_at=T0,
        )
    )
    session.flush()

    calls: list[int] = []

    def boom(_session, _place_event, _settings):
        calls.append(1)
        raise RuntimeError("group hook exploded")

    monkeypatch.setattr("findplus.ingest._group_events_evaluate", boom)
    result = ingest_observations(session, [_raw_obs("a", T0)])

    assert result.inserted == 1
    assert len(list(session.scalars(select(LocationObservation)))) >= 1
    assert calls == [1]  # the group hook did run, and raising did not lose the batch
    assert session.scalar(select(PlaceEvent)) is not None  # geofence's row survives too


def test_group_event_reaches_dispatch_in_the_same_poll(tmp_db, monkeypatch):
    """One poll must ingest the fix, fire the quorum AND deliver the group alert.

    The two hooks live in different sessions (ingest commits first, dispatch
    runs after), so nothing but an end-to-end poll proves a group_place_events
    row written at ingest is visible to `load_pending_events` before the poll
    returns. Anything less and group rules silently wait for the next cycle.
    """
    from unittest.mock import patch

    from findplus.alerts.channels.telegram import DeliveryResult
    from findplus.alerts.store import AlertsChannels, TelegramCreds
    from findplus.config import get_settings
    from findplus.db.models_alerts import AlertDelivery, AlertRule
    from findplus.db.session import session_scope
    from findplus.poller import _locate_and_ingest

    now = datetime.now(UTC)
    with session_scope() as s:
        group, place = _seed_group(s, quorum="any")
        for device_id in ("a", "b", "c"):
            _add_fix(s, device_id, now - timedelta(minutes=5))
        s.add(
            PlaceState(
                place_id=place.id,
                device_id="a",
                state="outside",
                streak=0,
                streak_side=None,
                since_observed_at=None,
                last_observation_id=None,
                updated_at=now,
            )
        )
        s.add(
            AlertRule(
                name="family-home",
                place_id=place.id,
                group_id=group.id,
                device_id=None,
                on_enter=True,
                on_exit=True,
                channel="telegram",
                cooldown_minutes=30,
                enabled=True,
                also_notify_members=False,
                created_at=now,
            )
        )

    creds = TelegramCreds("123:abc", "42", "Family", "findplus_bot", now.isoformat())

    class _Provider:
        def locate(self, device_id, device_name):
            return [_raw_obs(device_id, now)]

    with (
        patch(
            "findplus.alerts.store.load_alerts",
            return_value=AlertsChannels(telegram=creds, webhook=None),
        ),
        patch(
            "findplus.alerts.channels.telegram.send",
            return_value=DeliveryResult(success=True, status_code=200, error=None),
        ) as send_mock,
    ):
        outcome, _ = _locate_and_ingest(_Provider(), "a", "a", get_settings())

    assert outcome.status == "ok"
    with session_scope() as s:
        assert s.scalar(select(GroupPlaceEvent)) is not None
        delivered = s.query(AlertDelivery).filter_by(event_kind="group", status="sent").all()
        assert len(delivered) == 1
    assert any("tags entered Home" in call[0][0] for call in send_mock.call_args_list)
