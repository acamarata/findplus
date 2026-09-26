"""Alert dispatch engine: load pending events, run the pure core, send, record.

Purpose : Turn confirmed geofence/group crossings into outbound notifications.
Inputs  : place_events/group_place_events rows with notified_at IS NULL.
Outputs : Sent messages; alert_deliveries rows; notified_at stamped on the
          source row.
Constraints:
    - Pure matching/suppression/cooldown/render/retry rules live in
      dispatch_core.py (re-exported below) and take no DB or network.
    - process() never raises into the poller: every send is wrapped. A
      transient failure is scheduled for retry (alerts/retry.py drains it);
      a permanent failure/skip must not start the next cooldown.
"""

from __future__ import annotations

import datetime

from sqlalchemy.exc import IntegrityError

from findplus.alerts.dispatch_core import (
    Delivery,
    DeviceEvent,
    GroupEvent,
    Rule,
    as_utc,
    classify_new_delivery,
    in_cooldown,
    match,
    render_message,
    suppressed_by_group,
)
from findplus.alerts.dispatch_events import load_pending_events
from findplus.alerts.dispatch_send import _status_for
from findplus.alerts.dispatch_targets import (
    _already_delivered,
    _channel_targets,
    _deliver_skip,
    _insert_delivery_row,
)

__all__ = [
    "Delivery",
    "DeviceEvent",
    "GroupEvent",
    "Rule",
    "as_utc",
    "in_cooldown",
    "load_pending_events",
    "match",
    "process",
    "render_message",
    "suppressed_by_group",
]


def _load_rules(session) -> list[Rule]:
    from findplus.alerts.channels_field import parse_channels
    from findplus.alerts.rule_telegram_targets import parse_rule_telegram_targets
    from findplus.db.models_alerts import AlertRule as AlertRuleORM

    rows = session.query(AlertRuleORM).filter_by(enabled=True).all()
    return [
        Rule(
            id=r.id,
            name=r.name,
            place_id=r.place_id,
            group_id=r.group_id,
            device_id=r.device_id,
            on_enter=r.on_enter,
            on_exit=r.on_exit,
            channels=parse_channels(r.channels),
            cooldown_minutes=r.cooldown_minutes,
            enabled=r.enabled,
            also_notify_members=r.also_notify_members,
            telegram_targets=parse_rule_telegram_targets(r.telegram_targets),
        )
        for r in rows
    ]


def _delivery_place_ids(session, rows) -> dict[tuple[str, int], int | None]:
    """Derived place_id per (event_kind, event_id): alert_deliveries has no place_id column."""
    from findplus.db.models import GroupPlaceEvent, PlaceEvent

    out: dict[tuple[str, int], int | None] = {}
    for kind, model in (("device", PlaceEvent), ("group", GroupPlaceEvent)):
        ids = {d.event_id for d in rows if d.event_kind == kind}
        if not ids:
            continue
        for event_id, place_id in session.query(model.id, model.place_id).filter(model.id.in_(ids)):
            out[(kind, event_id)] = place_id
    return out


def _load_recent_deliveries(session, now: datetime.datetime) -> list[Delivery]:
    from findplus.db.models_alerts import AlertDelivery as AlertDeliveryORM

    cutoff = now - datetime.timedelta(hours=24)
    rows = session.query(AlertDeliveryORM).filter(AlertDeliveryORM.sent_at > cutoff).all()
    place_ids = _delivery_place_ids(session, rows)
    return [
        Delivery(
            rule_id=d.rule_id,
            event_kind=d.event_kind,
            event_id=d.event_id,
            sent_at=d.sent_at,
            channel=d.channel,
            status=d.status,
            place_id=place_ids.get((d.event_kind, d.event_id)),
        )
        for d in rows
    ]


def _resolve_status(channel: str, rule: Rule, event, kind: str, channels_cfg, now, target: str):
    # "native" has no send and no DeliveryResult, never a retry candidate.
    if channel == "native":
        return "queued", None, None, None
    return _status_for(channel, rule, event, kind, channels_cfg, now, target)


def _deliver_one(
    session,
    rule: Rule,
    channel: str,
    event,
    channels_cfg,
    now: datetime.datetime,
    target: str = "",
) -> Delivery | None:
    """Send one (rule, channel, target, event) tuple and record it. None if
    already delivered. A failure on one target never touches another --
    each target is its own row, its own retry ladder (alerts/retry.py)."""
    kind = "device" if isinstance(event, DeviceEvent) else "group"
    eid = event.place_event_id if isinstance(event, DeviceEvent) else event.group_place_event_id
    if _already_delivered(session, rule.id, kind, eid, channel, target):
        return None

    status, err, status_code, retry_after = _resolve_status(
        channel, rule, event, kind, channels_cfg, now, target
    )
    status, attempts, next_attempt_at = classify_new_delivery(
        status, err, status_code, retry_after, now
    )
    _insert_delivery_row(
        session, rule, kind, eid, channel, target, now, status, err, attempts, next_attempt_at
    )
    try:
        session.commit()
    except IntegrityError:
        # Another poller won the race between the dedup SELECT and this commit.
        session.rollback()
        return None
    # status travels with the row so a failed/retrying send does not start
    # this run's in-memory cooldown (Delivery.status defaults to "sent").
    return Delivery(
        rule_id=rule.id,
        event_kind=kind,
        event_id=eid,
        sent_at=now,
        channel=channel,
        status=status,
        place_id=event.place_id,
    )


def _mark_notified(session, events: list, now: datetime.datetime) -> None:
    from sqlalchemy import text

    # text() bypasses the UtcDateTime bind hook: normalise here so SQLite
    # never stores an offset string the reader re-reads as UTC.
    now = now.astimezone(datetime.UTC).replace(tzinfo=None)
    for event in events:
        if isinstance(event, DeviceEvent):
            session.execute(
                text("UPDATE place_events SET notified_at = :n WHERE id = :i"),
                {"n": now, "i": event.place_event_id},
            )
        else:
            session.execute(
                text("UPDATE group_place_events SET notified_at = :n WHERE id = :i"),
                {"n": now, "i": event.group_place_event_id},
            )
    session.commit()


def process(events: list, session, settings, now: datetime.datetime | None = None) -> None:
    """Match, suppress, cool down, send, record. The sole DB/network entry point."""
    if not getattr(settings, "alerts_enabled", True) or not events:
        return

    from findplus.alerts.store import load_alerts

    now = now or datetime.datetime.now(datetime.UTC)
    rules = _load_rules(session)
    deliveries = _load_recent_deliveries(session, now)
    channels_cfg = load_alerts()

    for event in events:
        for rule in match(rules, event):
            if isinstance(event, DeviceEvent) and suppressed_by_group(rule, event, rules):
                continue
            for channel in rule.channels:
                if in_cooldown(rule, channel, event, deliveries, now):
                    continue
                # Cooldown stays per (rule, channel, place) -- not per target --
                # same as before multi-target telegram existed: it answers "did
                # this rule already notify over this channel recently", not
                # "did this exact person already hear about it".
                targets, skip_reason = _channel_targets(channel, channels_cfg, rule)
                if skip_reason is not None:
                    delivered = _deliver_skip(session, rule, channel, event, now, skip_reason)
                    if delivered is not None:
                        deliveries.append(delivered)
                    continue
                for target in targets:
                    delivered = _deliver_one(
                        session, rule, channel, event, channels_cfg, now, target
                    )
                    if delivered is not None:
                        deliveries.append(delivered)

    _mark_notified(session, events, now)
