"""POST /api/alerts/rules/dry-run: what a rule would have sent in the last day.

Purpose    : The rule dialog's "Show what this would have sent" check. Read-only:
             nothing is stored or sent. See findplus/alerts/dryrun.py.
Inputs     : A rule's targeting (place, one device or one group, on enter, on
             exit, cooldown) and a window in hours (1-72, default 24).
Outputs    : {window_hours, rows: [{observed_at, event_type, text, sends}],
             would_send, held_back}.
Constraints: Gated like every /api/alerts path. Exactly one of device_id and
             group_id is required (422), the same rule a saved rule follows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from findplus.alerts.dispatch_core import Rule
from findplus.alerts.dryrun import would_have_fired
from findplus.db.session import session_scope


class DryRunBody(BaseModel):
    place_id: int | None = None
    device_id: str | None = None
    group_id: int | None = None
    on_enter: bool = True
    on_exit: bool = True
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)
    hours: int = Field(default=24, ge=1, le=72)


def post_dry_run(body: DryRunBody) -> dict[str, Any]:
    if (body.device_id is None) == (body.group_id is None):
        raise HTTPException(status_code=422, detail="choose exactly one of a tracker or a group")
    rule = Rule(
        id=0,
        name="preview",
        place_id=body.place_id,
        group_id=body.group_id,
        device_id=body.device_id,
        on_enter=body.on_enter,
        on_exit=body.on_exit,
        channels=[],
        cooldown_minutes=body.cooldown_minutes,
        enabled=True,
        also_notify_members=False,
    )
    with session_scope() as session:
        rows = would_have_fired(session, rule, datetime.now(UTC), body.hours)
    sends = sum(1 for r in rows if r["sends"])
    return {
        "window_hours": body.hours,
        "rows": rows,
        "would_send": sends,
        "held_back": len(rows) - sends,
    }


def register(router: APIRouter) -> None:
    router.add_api_route("/rules/dry-run", post_dry_run, methods=["POST"])
