"""Read-only delivery-log routes: GET /api/alerts/deliveries and the native
notification ack.

Purpose    : Split out of routes_alerts_rules.py at the PRI rule-7 300-line
             file cap (WP10's telegram_targets fields pushed the rules file
             over it) -- the same reason routes_alerts_telegram.py was split
             out of routes_alerts_channels.py. register() mounts both routes
             onto the shared `/api/alerts` router routes_alerts_rules.py's
             build_router() owns.
Outputs    : Delivery dicts with rendered text/body (batch_delivery_text_
             bodies), never a per-row query.
Constraints: Gated by SessionAuthMiddleware like every /api/ path not in
             _PUBLIC. Handlers close over nothing, so they are module-level
             functions and register() only attaches them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from findplus.api._delivery_render import batch_delivery_text_bodies
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.session import session_scope


def _delivery_to_dict(
    d: AlertDelivery,
    rule_name: str,
    rendered: dict[tuple[str, int], tuple[str | None, str | None]],
) -> dict[str, Any]:
    """One delivery row. `text`/`body` are rendered on read, for every channel
    (UAT4 N32 widened this from native-only -- the renderer needs only the
    event, never the channel, and `None` means the source event was purged).

    `rendered` is the whole page's text/body lookup, built once by
    `batch_delivery_text_bodies` (CF-P2-16) -- never a per-row query. No join
    field (place_name, device_name, group_name, event_type) is exposed: a
    caller that wants any of them already has the rendered text.
    """
    text, body = rendered.get((d.event_kind, d.event_id), (None, None))
    return {
        "id": d.id,
        "rule_id": d.rule_id,
        "rule_name": rule_name,
        # A stored column since migration 0008: one delivery row per channel per
        # event, so the rule no longer owns it alone.
        "channel": d.channel,
        "target": d.target,  # '' unless the channel is per-target (telegram) -- migration 0011
        "event_kind": d.event_kind,
        "event_id": d.event_id,
        "sent_at": d.sent_at.isoformat(),
        "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
        "status": d.status,
        "error": d.error,
        # Retry scheduling (2026-09-22 feature): attempts is 1 for every row
        # that has never been retried; next_attempt_at is set only while
        # status == "retrying".
        "attempts": d.attempts,
        "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None,
        "text": text,
        "body": body,
    }


def get_deliveries(
    limit: int = Query(default=100, le=500), since: int | None = None, channel: str | None = None
) -> list[dict[str, Any]]:
    """The delivery log, and the queue the desktop native poller drains.

    `since` is an exclusive delivery-id cursor and replaces `limit` when
    given: the poller wants everything new, in the order it happened, not a
    fixed page of the most recent (specs/notifications.md § 2).

    `limit` is capped at 500 (422 above it, CR-C closeout m7): unbounded, it
    let `rows` grow past SQLite's ~32766-variable cap once `batch_delivery_
    text_bodies` turned it into an IN-list of (event_kind, event_id) pairs
    for a native-channel request, a 500 where the old row-by-row code was
    only slow.
    """
    with session_scope() as s:
        stmt = select(AlertDelivery, AlertRule.name).join(
            AlertRule, AlertRule.id == AlertDelivery.rule_id
        )
        if channel is not None:
            stmt = stmt.filter(AlertDelivery.channel == channel)
        if since is not None:
            stmt = stmt.filter(AlertDelivery.id > since).order_by(AlertDelivery.id).limit(limit)
        else:
            stmt = stmt.order_by(AlertDelivery.sent_at.desc()).limit(limit)
        rows = s.execute(stmt).all()
        # Every row gets rendered, not only when the REQUEST itself filters
        # to `?channel=native` (UAT3 N18) and not only native rows (UAT4
        # N32): a telegram/whatsapp row's (event_kind, event_id) resolves
        # through the exact same batched renderer a native row does, so
        # gating on `d.channel == "native"` only hid text the server could
        # already produce. `limit` (capped at 500 above) already bounds how
        # many keys this can ever build, so widening this costs nothing.
        keys = [(d.event_kind, d.event_id) for d, _rule_name in rows]
        rendered = batch_delivery_text_bodies(s, keys) if keys else {}
        return [_delivery_to_dict(d, rule_name, rendered) for d, rule_name in rows]


def ack_delivery(delivery_id: int) -> Response:
    """The desktop app confirms it showed a queued native notification.

    404 covers both "no such delivery" and "not queued any more". A repeated
    ack from a retried request is expected, not a conflict, so the client
    treats 404 as success-equivalent (specs/notifications.md § 2).
    """
    with session_scope() as s:
        delivery = s.get(AlertDelivery, delivery_id)
        if delivery is None or delivery.status != "queued":
            raise HTTPException(status_code=404, detail="delivery not queued")
        delivery.status = "delivered"
        delivery.delivered_at = datetime.now(UTC)
        s.commit()
    return Response(status_code=204)


def register(router: APIRouter) -> None:
    """Attach the delivery-log routes onto the shared `/api/alerts` router."""
    router.add_api_route("/deliveries", get_deliveries, methods=["GET"])
    router.add_api_route(
        "/deliveries/{delivery_id}/ack", ack_delivery, methods=["POST"], status_code=204
    )
