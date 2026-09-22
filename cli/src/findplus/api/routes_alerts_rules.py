"""Alert rule and delivery-history routes.

Purpose    : CRUD for alert_rules, and a read-only feed of alert_deliveries.
Outputs    : Rule dicts with place_name/group_name/device_name resolved via a
             joined query (never N+1 selects). ValueError-free: 404s are
             raised directly by this module.
Constraints: Gated by SessionAuthMiddleware like every /api/ path not in
             _PUBLIC (routes_alerts is never in that set). Handlers close
             over nothing, so they are module-level functions and
             build_router only registers them (E13 loop-1 function-cap
             refactor; routes and signatures unchanged).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from findplus.alerts.channels_field import format_channels, parse_channels
from findplus.api._delivery_render import batch_delivery_text_bodies
from findplus.db.models import Device, Group, Place
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.session import session_scope


def _validate_channels(value: list[str] | None) -> list[str] | None:
    """422, not 500: pydantic turns a ValueError here into a field error.

    format_channels owns the rules (non-empty, known ids); this only surfaces
    them, and leaves an omitted RuleUpdate.channels alone.
    """
    if value is None:
        return None
    format_channels(value)
    return value


class RuleCreate(BaseModel):
    name: str
    place_id: int | None = None
    group_id: int | None = None
    device_id: str | None = None
    on_enter: bool = True
    on_exit: bool = True
    channels: list[str]
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)
    enabled: bool = True
    also_notify_members: bool = False

    _check_channels = field_validator("channels")(_validate_channels)


class RuleUpdate(BaseModel):
    name: str | None = None
    place_id: int | None = None
    on_enter: bool | None = None
    on_exit: bool | None = None
    channels: list[str] | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    enabled: bool | None = None
    also_notify_members: bool | None = None

    _check_channels = field_validator("channels")(_validate_channels)


def _rule_to_dict(
    r: AlertRule, place_name: str | None, group_name: str | None, device_name: str | None
) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "place_id": r.place_id,
        "place_name": place_name,
        "group_id": r.group_id,
        "group_name": group_name,
        "device_id": r.device_id,
        "device_name": device_name,
        "on_enter": r.on_enter,
        "on_exit": r.on_exit,
        "channels": parse_channels(r.channels),
        "cooldown_minutes": r.cooldown_minutes,
        "enabled": r.enabled,
        "also_notify_members": r.also_notify_members,
    }


def _list_rules(session) -> list[dict[str, Any]]:
    stmt = (
        select(AlertRule, Place.name, Group.name, Device.name)
        .outerjoin(Place, Place.id == AlertRule.place_id)
        .outerjoin(Group, Group.id == AlertRule.group_id)
        .outerjoin(Device, Device.device_id == AlertRule.device_id)
        .order_by(AlertRule.id)
    )
    return [
        _rule_to_dict(r, place_name, group_name, device_name)
        for r, place_name, group_name, device_name in session.execute(stmt).all()
    ]


def _get_rule_or_404(session, rule_id: int) -> AlertRule:
    rule = session.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"alert rule {rule_id} not found")
    return rule


def _delivery_to_dict(
    d: AlertDelivery,
    rule_name: str,
    rendered: dict[tuple[str, int], tuple[str | None, str | None]],
) -> dict[str, Any]:
    """One delivery row. `text`/`body` are rendered on read, for native rows only.

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


def get_rules() -> list[dict[str, Any]]:
    with session_scope() as s:
        return _list_rules(s)


def post_rule(body: RuleCreate) -> dict[str, Any]:
    if (body.group_id is None) == (body.device_id is None):
        raise HTTPException(
            status_code=422, detail="exactly one of group_id or device_id is required"
        )
    with session_scope() as s:
        rule = AlertRule(
            name=body.name,
            place_id=body.place_id,
            group_id=body.group_id,
            device_id=body.device_id,
            on_enter=body.on_enter,
            on_exit=body.on_exit,
            channels=format_channels(body.channels),
            cooldown_minutes=body.cooldown_minutes,
            enabled=body.enabled,
            also_notify_members=body.also_notify_members,
            created_at=datetime.now(UTC),
        )
        s.add(rule)
        s.commit()
        rule_id = rule.id
    with session_scope() as s:
        return next(r for r in _list_rules(s) if r["id"] == rule_id)


def put_rule(rule_id: int, body: RuleUpdate) -> dict[str, Any]:
    with session_scope() as s:
        rule = _get_rule_or_404(s, rule_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            if field == "channels":
                rule.channels = format_channels(value)
                continue
            setattr(rule, field, value)
        s.commit()
    with session_scope() as s:
        return next(r for r in _list_rules(s) if r["id"] == rule_id)


def delete_rule(rule_id: int) -> Response:
    with session_scope() as s:
        rule = _get_rule_or_404(s, rule_id)
        s.delete(rule)
        s.commit()
    return Response(status_code=204)


def get_deliveries(
    limit: int = 100, since: int | None = None, channel: str | None = None
) -> list[dict[str, Any]]:
    """The delivery log, and the queue the desktop native poller drains.

    `since` is an exclusive delivery-id cursor and replaces `limit` when
    given: the poller wants everything new, in the order it happened, not a
    fixed page of the most recent (specs/notifications.md § 2).
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
        render_native = channel == "native"
        keys = [
            (d.event_kind, d.event_id)
            for d, _rule_name in rows
            if render_native and d.channel == "native"
        ]
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


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/alerts", tags=["alerts"])
    router.add_api_route("/rules", get_rules, methods=["GET"])
    router.add_api_route("/rules", post_rule, methods=["POST"], status_code=201)
    router.add_api_route("/rules/{rule_id}", put_rule, methods=["PUT"])
    router.add_api_route("/rules/{rule_id}", delete_rule, methods=["DELETE"], status_code=204)
    router.add_api_route("/deliveries", get_deliveries, methods=["GET"])
    router.add_api_route(
        "/deliveries/{delivery_id}/ack", ack_delivery, methods=["POST"], status_code=204
    )
    return router
