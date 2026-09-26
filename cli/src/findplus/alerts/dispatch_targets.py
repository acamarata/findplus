"""Delivery-row dedup/insert primitives, and Telegram's per-rule target list.

Purpose : Split out of dispatch.py at the PRI rule-7 300-line file cap (WP10's
          per-rule Telegram target subset, gap-audit P13, pushed it over) --
          the same reason dispatch_send.py and dispatch_events.py were split
          out earlier. dispatch.py's _deliver_one() and process() both call
          into this module; nothing here calls back into dispatch.py, so
          there is no import cycle.
Inputs  : A SQLAlchemy session, a Rule, the alerts/store.py channels config.
Outputs : _already_delivered (dedup check), _insert_delivery_row (the one
          AlertDeliveryORM insert every send path shares), _channel_targets
          (which chat ids a telegram send fans out to this cycle, plus a
          skip reason when the rule's own choice leaves none), _deliver_skip
          (a "skipped" row recorded with no channel API call at all).
Constraints: process() never raises into the poller -- _deliver_skip mirrors
          _deliver_one's own dedup-then-insert-then-commit/rollback shape so
          a concurrent poller's race is handled the same way in both places.
"""

from __future__ import annotations

import datetime

from sqlalchemy.exc import IntegrityError

from findplus.alerts.dispatch_core import Delivery, DeviceEvent, Rule


def _already_delivered(
    session, rule_id: int, kind: str, eid: int, channel: str, target: str
) -> bool:
    from findplus.db.models_alerts import AlertDelivery as AlertDeliveryORM

    filters = {
        "rule_id": rule_id,
        "event_kind": kind,
        "event_id": eid,
        "channel": channel,
        "target": target,
    }
    return session.query(AlertDeliveryORM).filter_by(**filters).first() is not None


def _insert_delivery_row(
    session, rule, kind, eid, channel, target, now, status, err, attempts, next_attempt_at
):
    """The one AlertDeliveryORM insert every send/skip path makes, split out
    to keep each caller under the 50-line cap (PRI rule 7)."""
    from findplus.db.models_alerts import AlertDelivery as AlertDeliveryORM

    session.add(
        AlertDeliveryORM(
            rule_id=rule.id,
            event_kind=kind,
            event_id=eid,
            channel=channel,
            target=target,
            sent_at=now,
            status=status,
            error=err,
            attempts=attempts,
            next_attempt_at=next_attempt_at,
        )
    )


def _channel_targets(channel: str, channels_cfg, rule: Rule) -> tuple[list[str], str | None]:
    """Every target a channel fans this event out to, plus a skip reason
    when the rule's own choice leaves nothing to send to.

    Telegram is the only multi-target channel today: one delivery row (and
    one retry ladder) per configured chat id/username. Every other channel,
    including an unconfigured or misconfigured telegram (channels_cfg.
    telegram is None, or configured with no targets at all -- store.py never
    persists an empty chat_ids tuple in practice, but a hand-edited alerts.
    json could), gets a single `""` target so _deliver_one runs exactly once
    and dispatch_send._send()'s existing "channel not configured" -> skipped
    path is unchanged.

    WP10 (gap-audit P13): `rule.telegram_targets` narrows a configured
    Telegram send to a subset of the saved chat_ids. None means "every
    saved target" (unchanged fan-out); a non-None list intersects against
    what is actually saved (a target removed from the account since this
    rule picked it silently drops, never errors); an empty result --
    whether the rule's own subset is `[]` or every picked id has since been
    removed -- returns no targets and a clear reason instead of guessing
    "all" back in, so a picky rule never surprises anyone with an unpicked
    chat.
    """
    if channel != "telegram" or not channels_cfg.telegram or not channels_cfg.telegram.chat_ids:
        return [""], None
    if rule.telegram_targets is None:
        return list(channels_cfg.telegram.chat_ids), None
    saved = set(channels_cfg.telegram.chat_ids)
    subset = [t for t in rule.telegram_targets if t in saved]
    if not subset:
        return [], "no Telegram chats selected for this rule"
    return subset, None


def _deliver_skip(
    session, rule: Rule, channel: str, event, now: datetime.datetime, reason: str
) -> Delivery | None:
    """Record a "skipped" row with no send attempt at all -- WP10's explicit
    "no Telegram chats selected" case (_channel_targets returning no
    targets). Mirrors _deliver_one's own dedup-then-insert-then-commit shape
    but never touches a channel API: there is nothing configured to call."""
    kind = "device" if isinstance(event, DeviceEvent) else "group"
    eid = event.place_event_id if isinstance(event, DeviceEvent) else event.group_place_event_id
    target = ""
    if _already_delivered(session, rule.id, kind, eid, channel, target):
        return None
    _insert_delivery_row(session, rule, kind, eid, channel, target, now, "skipped", reason, 1, None)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return None
    return Delivery(
        rule_id=rule.id,
        event_kind=kind,
        event_id=eid,
        sent_at=now,
        channel=channel,
        status="skipped",
        place_id=event.place_id,
    )
