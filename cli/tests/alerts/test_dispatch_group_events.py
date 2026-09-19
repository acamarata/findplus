"""alerts/dispatch.py: GroupEvent content and end-to-end dispatch (not cooldown-scoped).

Split out of test_dispatch_cooldown.py (PRI rule 7, <=300 lines/file); the
place-scoped cooldown tests stayed in test_dispatch_cooldown.py. Shared
seed/builder helpers in _helpers.py; shared fixtures in conftest.py.
"""

from __future__ import annotations

from unittest.mock import patch

from findplus.alerts.dispatch import GroupEvent, load_pending_events, process
from findplus.db.models import GroupPlaceEvent
from findplus.db.models_alerts import AlertDelivery

from ._helpers import (
    NOW,
    _group_event,
    _rule,
    _seed_group,
    _seed_group_place_event,
    _seed_place_and_device,
    _send_ok,
    _telegram_configured,
)


def test_group_event_end_to_end_dispatch(session, settings_enabled) -> None:
    """A real group_place_events row + a group rule: process() sends and the note lands."""
    _seed_place_and_device(session)
    _seed_group(session)
    session.add(_rule(name="group-rule", device_id=None, place_id=1, group_id=1))
    session.commit()

    gpe_id = _seed_group_place_event(session, group_id=1, place_id=1, observed_at=NOW)
    event = _group_event(group_place_event_id=gpe_id, note="2 of 2 members crossed")

    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()) as send_mock,
    ):
        process([event], session, settings_enabled, now=NOW)

    row = session.query(AlertDelivery).filter_by(event_kind="group").one()
    assert row.status == "sent", row.error
    sent_text = send_mock.call_args[0][0]
    assert "2 of 2 members crossed" in sent_text


def test_group_event_note_states_who_actually_crossed(session, settings_enabled) -> None:
    """load_pending_events must rebuild the note group_place_events cannot store.

    Without it every group alert reads "the group arrived", which is exactly the
    overstatement PROMPT.md §6 forbids when only a quorum crossed and a member
    has no recent fix.
    """
    _seed_place_and_device(session)
    _seed_group(session)
    row = GroupPlaceEvent(
        group_id=1,
        place_id=1,
        event_type="ENTER",
        observed_at=NOW,
        member_event_ids="[]",
        members_crossed=2,
        members_considered=3,
        members_stale=1,
        confidence="medium",
        notified_at=None,
    )
    session.add(row)
    session.commit()

    events = [e for e in load_pending_events(session) if isinstance(e, GroupEvent)]
    assert len(events) == 1
    assert events[0].note == "2 of 3 tags entered Home; 1 tag has no recent fix."


def test_group_event_note_reaches_the_sent_message(session, settings_enabled) -> None:
    _seed_place_and_device(session)
    _seed_group(session)
    session.add(_rule(name="group-rule", device_id=None, place_id=1, group_id=1))
    _seed_group_place_event(session, group_id=1, place_id=1, observed_at=NOW)
    session.commit()

    with (
        patch("findplus.alerts.store.load_alerts", return_value=_telegram_configured()),
        patch("findplus.alerts.channels.telegram.send", return_value=_send_ok()) as send_mock,
    ):
        process(load_pending_events(session), session, settings_enabled, now=NOW)

    sent = [c[0][0] for c in send_mock.call_args_list]
    assert any("2 of 2 tags entered Home." in text for text in sent), sent
