"""Alert dispatch engine: load pending events, run the pure core, send, record.

Purpose : Turn confirmed geofence/group crossings into outbound notifications.
Inputs  : place_events/group_place_events rows with notified_at IS NULL.
Outputs : Sent Telegram/webhook messages; alert_deliveries rows; notified_at
          stamped on the source row.
Constraints:
    - The pure matching/suppression/cooldown/render rules live in
      dispatch_core.py (re-exported below) and take no DB or network.
    - process() must never raise into the poller: every send is wrapped so a
      channel failure is recorded, not propagated.
Reuse: dispatch_core (match/suppressed_by_group/in_cooldown/render_message),
       alerts.channels.telegram.send, alerts.channels.webhook.send_webhook /
       build_payload, alerts.store.load_alerts.
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
    in_cooldown,
    match,
    render_message,
    suppressed_by_group,
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

_DEVICE_EVENTS_SQL = """SELECT pe.id, pe.place_id, p.name AS place_name, pe.device_id,
       d.name AS device_name, pe.event_type, pe.observed_at, pe.fetched_at, pe.confidence
FROM place_events pe JOIN places p ON p.id = pe.place_id
JOIN devices d ON d.device_id = pe.device_id
WHERE pe.notified_at IS NULL ORDER BY pe.observed_at ASC"""

_GROUP_EVENTS_SQL = """SELECT gpe.id, gpe.group_id, g.name AS group_name, gpe.place_id,
       p.name AS place_name, gpe.event_type, gpe.observed_at, gpe.confidence,
       gpe.members_crossed, gpe.members_considered, gpe.members_stale
FROM group_place_events gpe JOIN groups g ON g.id = gpe.group_id
JOIN places p ON p.id = gpe.place_id
WHERE gpe.notified_at IS NULL ORDER BY gpe.observed_at ASC"""


def load_pending_events(session) -> list[DeviceEvent | GroupEvent]:
    """Un-notified place_events/group_place_events rows, converted to dataclasses.

    notified_at IS NULL is the hand-off from E4's ingest-time geofence hook.
    Raw SQL (no ORM classes are pinned for the groups tables).
    """
    from sqlalchemy import text

    events: list[DeviceEvent | GroupEvent] = []
    for row in session.execute(text(_DEVICE_EVENTS_SQL)).all():
        group_ids = [
            r[0]
            for r in session.execute(
                text("SELECT group_id FROM device_group WHERE device_id = :device_id"),
                {"device_id": row.device_id},
            ).all()
        ]
        events.append(
            DeviceEvent(
                place_event_id=row.id,
                place_id=row.place_id,
                place_name=row.place_name,
                device_id=row.device_id,
                device_name=row.device_name,
                event_type=row.event_type,
                observed_at=as_utc(row.observed_at),
                fetched_at=as_utc(row.fetched_at),
                confidence=row.confidence,
                group_ids=group_ids,
            )
        )

    for row in session.execute(text(_GROUP_EVENTS_SQL)).all():
        events.append(
            GroupEvent(
                group_place_event_id=row.id,
                group_id=row.group_id,
                group_name=row.group_name,
                place_id=row.place_id,
                place_name=row.place_name,
                event_type=row.event_type,
                observed_at=as_utc(row.observed_at),
                confidence=row.confidence,
                note="",
                members_crossed=row.members_crossed,
                members_considered=row.members_considered,
                members_stale=row.members_stale,
            )
        )
    return events


def _load_rules(session) -> list[Rule]:
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
            channel=r.channel,
            cooldown_minutes=r.cooldown_minutes,
            enabled=r.enabled,
            also_notify_members=r.also_notify_members,
        )
        for r in rows
    ]


def _load_recent_deliveries(session, now: datetime.datetime) -> list[Delivery]:
    from findplus.db.models_alerts import AlertDelivery as AlertDeliveryORM

    cutoff = now - datetime.timedelta(hours=24)
    rows = session.query(AlertDeliveryORM).filter(AlertDeliveryORM.sent_at > cutoff).all()
    return [
        Delivery(rule_id=d.rule_id, event_kind=d.event_kind, event_id=d.event_id, sent_at=d.sent_at)
        for d in rows
    ]


def _send(rule: Rule, event: DeviceEvent | GroupEvent, kind: str, text_msg: str, channels_cfg):
    from findplus.alerts.channels.telegram import send as tg_send
    from findplus.alerts.channels.webhook import build_payload, send_webhook

    if rule.channel == "telegram" and channels_cfg.telegram:
        return tg_send(text_msg, channels_cfg.telegram.bot_token, channels_cfg.telegram.chat_id)
    if rule.channel == "webhook" and channels_cfg.webhook:
        subject_id = event.device_id if isinstance(event, DeviceEvent) else event.group_id
        subject_name = event.device_name if isinstance(event, DeviceEvent) else event.group_name
        observed_at = as_utc(event.observed_at)
        fetched_at = as_utc(getattr(event, "fetched_at", None))
        lag = round((fetched_at - observed_at).total_seconds() / 60) if fetched_at else 0
        payload = build_payload(
            event.event_type,
            kind,
            subject_id,
            subject_name,
            event.place_id,
            event.place_name,
            observed_at,
            fetched_at,
            lag,
            event.confidence or "",
            getattr(event, "note", ""),
        )
        return send_webhook(payload, channels_cfg.webhook.url, channels_cfg.webhook.secret)
    return None


def _deliver_one(
    session, rule: Rule, event, channels_cfg, now: datetime.datetime
) -> Delivery | None:
    """Send one (rule, event) pair and record it. None if already delivered or no channel."""
    from findplus.db.models_alerts import AlertDelivery as AlertDeliveryORM

    kind = "device" if isinstance(event, DeviceEvent) else "group"
    eid = event.place_event_id if isinstance(event, DeviceEvent) else event.group_place_event_id
    already = (
        session.query(AlertDeliveryORM)
        .filter_by(rule_id=rule.id, event_kind=kind, event_id=eid)
        .first()
    )
    if already:
        return None

    try:
        text_msg = render_message(event, now)
        result = _send(rule, event, kind, text_msg, channels_cfg)
        if result is None:
            return None
        status, err = ("sent" if result.success else "failed"), result.error
    except Exception as exc:  # a channel failure must never crash dispatch/the poller
        status, err = "failed", str(exc)[:500]

    session.add(
        AlertDeliveryORM(
            rule_id=rule.id,
            event_kind=kind,
            event_id=eid,
            sent_at=now,
            status=status,
            error=err,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # Another poller won the race between the dedup SELECT and this commit.
        session.rollback()
        return None
    return Delivery(rule_id=rule.id, event_kind=kind, event_id=eid, sent_at=now)


def _mark_notified(session, events: list, now: datetime.datetime) -> None:
    from sqlalchemy import text

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
            if in_cooldown(rule, event, deliveries, now):
                continue
            delivered = _deliver_one(session, rule, event, channels_cfg, now)
            if delivered is not None:
                deliveries.append(delivered)

    _mark_notified(session, events, now)
