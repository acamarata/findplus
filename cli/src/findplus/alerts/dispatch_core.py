"""Pure dispatch types and rules: match, suppress, cool down, render.

Purpose : The testable core of alert dispatch -- no DB or network import.
Inputs  : DeviceEvent/GroupEvent, Rule, Delivery dataclasses.
Outputs : Filtered rule lists, booleans, a rendered message string.
Constraints: Every function here takes dataclasses only. Split out of
          dispatch.py (PRI hard rule 7: <=300 lines/file) the same way
          poller_outcomes.py was split out of poller.py.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceEvent:
    place_event_id: int
    place_id: int
    place_name: str
    device_id: str
    device_name: str
    event_type: str
    observed_at: datetime.datetime
    fetched_at: datetime.datetime | None
    confidence: str
    group_ids: list[int]


@dataclass(frozen=True)
class GroupEvent:
    group_place_event_id: int
    group_id: int
    group_name: str
    place_id: int
    place_name: str
    event_type: str
    observed_at: datetime.datetime
    confidence: str | None
    note: str
    members_crossed: int
    members_considered: int
    members_stale: int


@dataclass(frozen=True)
class Rule:
    id: int
    name: str
    place_id: int | None
    group_id: int | None
    device_id: str | None
    on_enter: bool
    on_exit: bool
    channel: str
    cooldown_minutes: int
    enabled: bool
    also_notify_members: bool


@dataclass(frozen=True)
class Delivery:
    rule_id: int
    event_kind: str
    event_id: int
    sent_at: datetime.datetime | None


def match(rules: list[Rule], event: DeviceEvent | GroupEvent) -> list[Rule]:
    """Rules that are enabled, cover this event's type and place, and target it."""
    out = []
    for rule in rules:
        if not rule.enabled:
            continue
        if event.event_type == "ENTER" and not rule.on_enter:
            continue
        if event.event_type == "EXIT" and not rule.on_exit:
            continue
        if rule.place_id is not None and rule.place_id != event.place_id:
            continue
        if isinstance(event, DeviceEvent):
            if rule.device_id != event.device_id:
                continue
        elif rule.group_id != event.group_id:
            continue
        out.append(rule)
    return out


def suppressed_by_group(rule: Rule, event: DeviceEvent, rules: list[Rule]) -> bool:
    """True when an enabled group rule already covers this device's event.

    The group rule is checked against THIS event's type, never against the
    device rule's own on_enter/on_exit flags -- a group rule with
    on_enter=False, on_exit=True still suppresses a device EXIT alert at the
    same place.
    """
    for r in rules:
        if not r.enabled or r.group_id is None:
            continue
        if r.group_id not in event.group_ids or r.place_id != rule.place_id:
            continue
        covers_type = (event.event_type == "ENTER" and r.on_enter) or (
            event.event_type == "EXIT" and r.on_exit
        )
        if covers_type and not r.also_notify_members:
            return True
    return False


def in_cooldown(
    rule: Rule,
    event: DeviceEvent | GroupEvent,
    deliveries: list[Delivery],
    now: datetime.datetime,
) -> bool:
    if rule.cooldown_minutes == 0:
        return False
    kind = "device" if isinstance(event, DeviceEvent) else "group"
    limit = now - datetime.timedelta(minutes=rule.cooldown_minutes)
    return any(
        d.rule_id == rule.id
        and d.event_kind == kind
        and d.sent_at is not None
        and d.sent_at > limit
        for d in deliveries
    )


def render_message(event: DeviceEvent | GroupEvent, now: datetime.datetime) -> str:
    subject = event.device_name if isinstance(event, DeviceEvent) else event.group_name
    verb = "arrived at" if event.event_type == "ENTER" else "left"
    ft = getattr(event, "fetched_at", None)
    obs = event.observed_at.strftime("%H:%M")
    rep = ft.strftime("%H:%M") if ft else "unknown"
    lag = round((ft - event.observed_at).total_seconds() / 60) if ft else 0
    note = getattr(event, "note", "")
    msg = (
        f"{subject} {verb} {event.place_name}\n"
        f"Observed {obs} · reported {rep} · {lag} min late\n"
        f"Confidence: {event.confidence}."
    )
    if note:
        msg += f" {note}"
    msg += "\nFind Hub and Find My locations can be minutes to hours late."
    return msg[:400]
