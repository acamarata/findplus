"""Alert rule routes: CRUD for alert_rules.

Purpose    : CRUD for alert_rules. The read-only alert_deliveries feed lives
             in routes_alerts_deliveries.py (split out at the PRI rule-7
             300-line file cap, WP10) -- build_router() below mounts both.
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
from sqlalchemy import func, select

from findplus.alerts.channels_field import format_channels, parse_channels
from findplus.alerts.rule_telegram_targets import (
    format_rule_telegram_targets,
    parse_rule_telegram_targets,
    validate_rule_telegram_targets,
)
from findplus.alerts.store import load_alerts
from findplus.api import routes_alerts_deliveries
from findplus.db.models import Device, Group, Place
from findplus.db.models_alerts import AlertRule
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


def _require_a_connected_channel(channels: list[str]) -> None:
    """UAT2 U11: the dialog no longer defaults to an unconnected channel and
    disables/unticks the rest, but nothing stops a direct API call (or a
    dialog open before `connected` resolves) from saving a rule whose every
    channel would only ever fail to deliver. `native` needs no credentials
    (routes_alerts_channels.py never gates it behind `load_alerts()`), so it
    always counts; telegram/webhook/whatsapp count only once configured.
    """
    ch = load_alerts()
    configured = {"native"}
    if ch.telegram:
        configured.add("telegram")
    if ch.webhook:
        configured.add("webhook")
    if ch.whatsapp:
        configured.add("whatsapp")
    if not set(channels) & configured:
        raise HTTPException(
            status_code=422,
            detail="at least one selected channel must be connected before the rule can be saved",
        )


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
    #: A subset of the account's saved Telegram chat ids, or None for every
    #: saved target (the default -- WP10, gap-audit P13). `[]` is a distinct,
    #: valid value: the owner explicitly picked no chat, so dispatch.py skips
    #: Telegram for this rule instead of falling back to "all".
    telegram_targets: list[str] | None = None

    _check_channels = field_validator("channels")(_validate_channels)
    _check_telegram_targets = field_validator("telegram_targets")(validate_rule_telegram_targets)


class RuleUpdate(BaseModel):
    name: str | None = None
    place_id: int | None = None
    on_enter: bool | None = None
    on_exit: bool | None = None
    channels: list[str] | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    enabled: bool | None = None
    also_notify_members: bool | None = None
    telegram_targets: list[str] | None = None

    _check_channels = field_validator("channels")(_validate_channels)
    _check_telegram_targets = field_validator("telegram_targets")(validate_rule_telegram_targets)


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
        "telegram_targets": parse_rule_telegram_targets(r.telegram_targets),
    }


def _list_rules(session) -> list[dict[str, Any]]:
    # COALESCE(Device.label, Device.name): the rules table and the rule form's
    # own Device select both show the tracker's label, falling back to the
    # provider's name only when unset (UAT U6).
    stmt = (
        select(AlertRule, Place.name, Group.name, func.coalesce(Device.label, Device.name))
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


def get_rules() -> list[dict[str, Any]]:
    with session_scope() as s:
        return _list_rules(s)


def post_rule(body: RuleCreate) -> dict[str, Any]:
    if (body.group_id is None) == (body.device_id is None):
        raise HTTPException(
            status_code=422, detail="exactly one of group_id or device_id is required"
        )
    _require_a_connected_channel(body.channels)
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
            telegram_targets=format_rule_telegram_targets(body.telegram_targets),
            created_at=datetime.now(UTC),
        )
        s.add(rule)
        s.commit()
        rule_id = rule.id
    with session_scope() as s:
        return next(r for r in _list_rules(s) if r["id"] == rule_id)


def put_rule(rule_id: int, body: RuleUpdate) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    if updates.get("channels") is not None:
        _require_a_connected_channel(updates["channels"])
    with session_scope() as s:
        rule = _get_rule_or_404(s, rule_id)
        for field, value in updates.items():
            if field == "channels":
                rule.channels = format_channels(value)
                continue
            if field == "telegram_targets":
                rule.telegram_targets = format_rule_telegram_targets(value)
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


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/alerts", tags=["alerts"])
    router.add_api_route("/rules", get_rules, methods=["GET"])
    router.add_api_route("/rules", post_rule, methods=["POST"], status_code=201)
    router.add_api_route("/rules/{rule_id}", put_rule, methods=["PUT"])
    router.add_api_route("/rules/{rule_id}", delete_rule, methods=["DELETE"], status_code=204)
    routes_alerts_deliveries.register(router)
    return router
