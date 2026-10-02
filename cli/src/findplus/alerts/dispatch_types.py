"""Dispatch dataclasses: the events, rules and deliveries the pure core works on.

Purpose : Split out of dispatch_core.py (PRI rule 7, 300-line cap) when person
          events and left-behind alerts (specs/people-and-presence.md § 4, § 5)
          added fields and a third event type. dispatch_core re-exports every
          name here, so `from findplus.alerts.dispatch_core import GroupEvent`
          keeps working at every call site.
Inputs  : None. Plain frozen dataclasses.
Outputs : DeviceEvent, GroupEvent, LeftBehindEvent, Rule, Delivery, event_key().
Constraints: No DB or network import. New fields carry defaults so existing
          constructors (tests, retry.py, the delivery-log renderer) stay valid.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field


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
    #: The person/pet groups among `group_ids`: an all-people rule suppresses
    #: device alerts for these trackers (spec § 5.2).
    person_group_ids: list[int] = field(default_factory=list)
    #: The person groups among those that recorded their own person event for
    #: this place and type near this crossing. Only these suppress the
    #: tracker's device rules: with no person event, the device rule still
    #: sends (review r116 #4).
    person_event_group_ids: list[int] = field(default_factory=list)


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
    #: quorum (a set's D19 event) | person (one person crossing, spec § 5).
    basis: str = "quorum"
    #: groups.kind: set | person | pet.
    group_kind: str = "set"
    #: The tracker whose crossing decided a person event, and its label.
    lead_device_id: str | None = None
    lead_name: str | None = None
    #: When this computer first fetched the lead tracker's deciding sighting.
    fetched_at: datetime.datetime | None = None


@dataclass(frozen=True)
class LeftBehindEvent:
    """One confirmed left-behind episode, ready to alert once (spec § 4)."""

    left_behind_id: int
    group_id: int
    group_name: str
    device_id: str
    device_name: str
    role: str | None
    #: None for an unnamed spot.
    place_id: int | None
    place_name: str | None
    #: The tracker's last sighting at the anchor.
    observed_at: datetime.datetime
    fetched_at: datetime.datetime | None
    #: Where the person was last seen instead, if anywhere: (place text, time).
    person_place: str | None = None
    person_seen_at: datetime.datetime | None = None
    person_lead_name: str | None = None
    event_type: str = "LEFT_BEHIND"
    confidence: str = "medium"
    note: str = ""


@dataclass(frozen=True)
class Rule:
    id: int
    name: str
    place_id: int | None
    group_id: int | None
    device_id: str | None
    on_enter: bool
    on_exit: bool
    #: Every channel this rule notifies. One delivery row per channel per event.
    channels: list[str]
    cooldown_minutes: int
    enabled: bool
    also_notify_members: bool
    #: A subset of the account's saved Telegram chat ids, or None for every
    #: saved target (WP10). `[]` means the owner picked no chat: Telegram is
    #: skipped for this rule instead of falling back to "all".
    telegram_targets: list[str] | None = None
    #: Matches every person/pet group's events (migration 0013, spec § 5.2).
    all_people: bool = False


@dataclass(frozen=True)
class Delivery:
    rule_id: int
    event_kind: str
    event_id: int
    sent_at: datetime.datetime | None
    #: Which channel this row is for: one event under a multi-channel rule
    #: produces one Delivery per channel.
    channel: str
    #: Only a "sent" row starts a cooldown; a failed or skipped send never
    #: suppresses the next attempt at the same key.
    status: str = "sent"
    #: Derived, never a stored column: the place of the source event, so a
    #: rule with place_id=None cools down separately at each place.
    place_id: int | None = None
    #: Derived the same way: the source event's group, so an all-people
    #: rule's cooldown stays per person.
    group_id: int | None = None


def event_key(event: DeviceEvent | GroupEvent | LeftBehindEvent) -> tuple[str, int]:
    """(alert_deliveries.event_kind, event_id) for any dispatchable event."""
    if isinstance(event, DeviceEvent):
        return "device", event.place_event_id
    if isinstance(event, LeftBehindEvent):
        return "left_behind", event.left_behind_id
    return "group", event.group_place_event_id
