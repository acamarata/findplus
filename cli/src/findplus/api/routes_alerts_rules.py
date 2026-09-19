"""Alert rule and delivery-history routes.

Purpose    : CRUD for alert_rules, and a read-only feed of alert_deliveries.
Outputs    : Rule dicts with place_name/group_name/device_name resolved via a
             joined query (never N+1 selects). ValueError-free: 404s are
             raised directly by this module.
Constraints: Gated by SessionAuthMiddleware like every /api/ path not in
             _PUBLIC (routes_alerts is never in that set).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from findplus.db.models import Device, Group, Place
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.session import session_scope


class RuleCreate(BaseModel):
    name: str
    place_id: int | None = None
    group_id: int | None = None
    device_id: str | None = None
    on_enter: bool = True
    on_exit: bool = True
    channel: str
    cooldown_minutes: int = 30
    enabled: bool = True
    also_notify_members: bool = False


class RuleUpdate(BaseModel):
    name: str | None = None
    place_id: int | None = None
    on_enter: bool | None = None
    on_exit: bool | None = None
    channel: str | None = None
    cooldown_minutes: int | None = None
    enabled: bool | None = None
    also_notify_members: bool | None = None


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
        "channel": r.channel,
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


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/alerts", tags=["alerts"])

    @router.get("/rules")
    def get_rules() -> list[dict[str, Any]]:
        with session_scope() as s:
            return _list_rules(s)

    @router.post("/rules", status_code=201)
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
                channel=body.channel,
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

    @router.put("/rules/{rule_id}")
    def put_rule(rule_id: int, body: RuleUpdate) -> dict[str, Any]:
        with session_scope() as s:
            rule = _get_rule_or_404(s, rule_id)
            for field, value in body.model_dump(exclude_unset=True).items():
                setattr(rule, field, value)
            s.commit()
        with session_scope() as s:
            return next(r for r in _list_rules(s) if r["id"] == rule_id)

    @router.delete("/rules/{rule_id}", status_code=204)
    def delete_rule(rule_id: int) -> Response:
        with session_scope() as s:
            rule = _get_rule_or_404(s, rule_id)
            s.delete(rule)
            s.commit()
        return Response(status_code=204)

    @router.get("/deliveries")
    def get_deliveries(limit: int = 100) -> list[dict[str, Any]]:
        with session_scope() as s:
            stmt = (
                select(AlertDelivery, AlertRule.name)
                .join(AlertRule, AlertRule.id == AlertDelivery.rule_id)
                .order_by(AlertDelivery.sent_at.desc())
                .limit(limit)
            )
            return [
                {
                    "id": d.id,
                    "rule_id": d.rule_id,
                    "rule_name": rule_name,
                    "event_kind": d.event_kind,
                    "event_id": d.event_id,
                    "sent_at": d.sent_at.isoformat(),
                    "status": d.status,
                    "error": d.error,
                }
                for d, rule_name in s.execute(stmt).all()
            ]

    return router
