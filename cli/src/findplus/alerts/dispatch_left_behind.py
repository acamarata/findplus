"""Left-behind alerts: which episodes to send, and on which rules' channels (spec § 4).

Purpose : A confirmed left-behind episode alerts once, "on the channels of the
          rules that cover that person". Several rules cover one person (one
          default rule per place), so each channel is used once per episode,
          under the lowest-id rule that names it: one bag, one message. The
          setting people.left_behind_alerts ("tell me when a tracker is left
          behind, anywhere") decides whether it alerts at all; a rule's place
          never does, so a bag left at an unnamed spot alerts too (uat116 #3).
Inputs  : left_behind rows (state left_behind, confirmed, not yet notified, not
          at a Home place, setting people.left_behind_alerts on); alert rules.
Outputs : LeftBehindEvent dataclasses; the de-duplicated rule list to send on.
Constraints: Home is off by default (a bike in the garage is normal). Pets
          only through a rule naming the pet. An episode is stamped notified
          only once a delivery row exists for it (or it is too old to be news);
          with no rule to carry it, it stays pending and is logged once. The
          person's whereabouts in the text are re-inferred as of the
          confirmation instant, so a retry renders the same words.
"""

from __future__ import annotations

import dataclasses

from findplus.alerts.dispatch_core import ALL_PEOPLE_KINDS, LeftBehindEvent, Rule, as_utc
from findplus.logging_setup import get_logger

log = get_logger(__name__)

#: Setting key; "0" turns left-behind alerts off everywhere (spec Q4).
LEFT_BEHIND_ALERTS = "people.left_behind_alerts"


def match_left_behind(rules: list[Rule], event: LeftBehindEvent) -> list[Rule]:
    """Enabled rules naming this person (or everyone), each channel used once.

    The rule's place does not count: it says where arrivals are news, while
    a left-behind alert follows the person-level setting, wherever the bag is
    (uat116 #3; this reverses review r116's place filter, which dropped every
    bag left at a friend's house or a cafe). An all-people rule covers people,
    not pets (review r116 #12).
    """
    seen: set[str] = set()
    out: list[Rule] = []
    for rule in sorted(rules, key=lambda r: r.id):
        if not rule.enabled:
            continue
        everyone = rule.all_people and event.group_kind in ALL_PEOPLE_KINDS
        if not (everyone or (rule.group_id is not None and rule.group_id == event.group_id)):
            continue
        fresh = [c for c in rule.channels if c not in seen]
        if not fresh:
            continue
        seen.update(fresh)
        out.append(dataclasses.replace(rule, channels=fresh))
    return out


_LOGGED_UNSENT: set[int] = set()


def settled(session, events: list, fresh: list) -> list:
    """The events dispatch may stamp notified now.

    Every device and group event, sent or not. A left-behind episode only when
    a delivery row was written for it, or when it is too old to be news
    (`fresh` lacks it): one that no rule could carry stays pending, so it is
    sent once a channel is connected, and is logged once rather than vanishing.
    """
    from findplus.db.models_alerts import AlertDelivery

    fresh_ids = {id(e) for e in fresh}
    out = []
    for event in events:
        if not isinstance(event, LeftBehindEvent) or id(event) not in fresh_ids:
            out.append(event)
            continue
        q = session.query(AlertDelivery.id).filter_by(
            event_kind="left_behind", event_id=event.left_behind_id
        )
        if q.first() is not None:
            out.append(event)
        elif event.left_behind_id not in _LOGGED_UNSENT:
            _LOGGED_UNSENT.add(event.left_behind_id)
            log.info("left_behind_unsent_no_rule", left_behind_id=event.left_behind_id)
    return out


def _event_for(session, row, names) -> LeftBehindEvent | None:
    from sqlalchemy import select

    from findplus.db.models import Group, LocationObservation, Place
    from findplus.people.describe import labels_for, place_text
    from findplus.people.inputs import infer_person

    group = session.get(Group, row.group_id)
    if group is None:
        return None
    place = session.get(Place, row.place_id) if row.place_id is not None else None
    as_of = as_utc(row.confirmed_at or row.started_observed_at)
    last = session.scalars(
        select(LocationObservation)
        .where(
            LocationObservation.device_id == row.device_id,
            LocationObservation.observed_at <= as_of,
        )
        .order_by(LocationObservation.observed_at.desc())
        .limit(1)
    ).first()
    fix, trackers, _ = infer_person(session, group, as_of, names)
    labels = labels_for(trackers, group.name)
    tracker = next((t for t in trackers if t.device_id == row.device_id), None)
    lead = labels.get(fix.lead_device_id) if fix.lead_device_id else None
    elsewhere = None
    if fix.confidence in ("likely", "probably") and fix.observed_at is not None:
        elsewhere = place_text(fix.place_name, fix.relation, fix.distance_m, fix.reference_place)
    return LeftBehindEvent(
        left_behind_id=row.id,
        group_id=group.id,
        group_name=group.name,
        device_id=row.device_id,
        device_name=labels.get(row.device_id, names.get(row.device_id, row.device_id)),
        role=tracker.role if tracker else None,
        place_id=row.place_id,
        place_name=place.name if place else None,
        observed_at=as_utc(last.observed_at if last else row.started_observed_at),
        fetched_at=as_utc(last.first_fetched_at) if last else None,
        person_place=elsewhere,
        person_seen_at=as_utc(fix.observed_at) if elsewhere else None,
        person_lead_name=lead if elsewhere else None,
        group_kind=group.kind,
        decided_at=as_of,
    )


def _events(session, rows) -> list[LeftBehindEvent]:
    from findplus.device_labels import unique_names

    if not rows:
        return []
    names = unique_names(session)
    events = [_event_for(session, r, names) for r in rows]
    return [e for e in events if e is not None]


def pending_left_behind(session) -> list[LeftBehindEvent]:
    """Confirmed, still-open, un-notified episodes away from Home."""
    from sqlalchemy import or_, select

    from findplus.db.models import Place
    from findplus.db.models_people import LeftBehind
    from findplus.state import get_setting

    if get_setting(session, LEFT_BEHIND_ALERTS, "1") == "0":
        return []
    stmt = (
        select(LeftBehind)
        .outerjoin(Place, Place.id == LeftBehind.place_id)
        .where(
            LeftBehind.state == "left_behind",
            LeftBehind.confirmed_at.is_not(None),
            LeftBehind.notified_at.is_(None),
            or_(Place.id.is_(None), Place.kind != "home"),
        )
        .order_by(LeftBehind.confirmed_at)
    )
    return _events(session, list(session.scalars(stmt).all()))


def left_behind_by_ids(session, ids: list[int]) -> dict[int, LeftBehindEvent]:
    """Episodes by id for a retry or the delivery log, whatever their state."""
    from findplus.db.models_people import LeftBehind

    if not ids:
        return {}
    rows = session.query(LeftBehind).filter(LeftBehind.id.in_(list(ids))).all()
    return {e.left_behind_id: e for e in _events(session, rows)}
