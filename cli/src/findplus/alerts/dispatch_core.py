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

from findplus.alerts.retry_classify import (
    MAX_ATTEMPTS,
    RETRY_OFFSETS_MINUTES,
    classify_new_delivery,
    compute_next_attempt_at,
    is_transient_failure,
)
from findplus.honesty import ALERTS_LATENCY

#: Re-exported so existing `from findplus.alerts.dispatch_core import ...`
#: call sites (dispatch.py, dispatch_send.py's docstring, retry.py, tests)
#: are unchanged now that the retry math itself lives in retry_classify.py.
__all__ = [
    "MAX_ATTEMPTS",
    "RETRY_OFFSETS_MINUTES",
    "classify_new_delivery",
    "compute_next_attempt_at",
    "is_transient_failure",
]


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
    #: Every channel this rule notifies. One delivery row per channel per event.
    channels: list[str]
    cooldown_minutes: int
    enabled: bool
    also_notify_members: bool
    #: A subset of the account's saved Telegram chat ids, or None for every
    #: saved target (WP10, gap-audit P13) -- parsed from alert_rules.
    #: telegram_targets by alerts/rule_telegram_targets.py. `[]` is a
    #: distinct, meaningful value: the owner picked no chat, so dispatch.py's
    #: _channel_targets() skips Telegram for this rule instead of falling
    #: back to "all". Defaulted so retry.py's own Rule rebuild (which never
    #: needs this -- a retry resends to the row's own already-stored target)
    #: does not have to pass it.
    telegram_targets: list[str] | None = None


@dataclass(frozen=True)
class Delivery:
    rule_id: int
    event_kind: str
    event_id: int
    sent_at: datetime.datetime | None
    #: Which channel this row is for. One event under a multi-channel rule
    #: produces one Delivery per channel, so the rule_id no longer implies it.
    channel: str
    #: "sent" | "failed". 1.0 never retries a delivery (events are stamped
    #: notified_at regardless of outcome, to avoid a resend storm), so a
    #: failed/skipped send must not itself start a cooldown -- only a
    #: successful send should suppress the next same-key alert.
    status: str = "sent"
    #: Derived, never a stored column: the place of the source place_event /
    #: group_place_event row. process() fills it via an ORM join so cooldown
    #: can be scoped per place (a rule with place_id=None must cool down
    #: separately at each place, never across all of them).
    place_id: int | None = None


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
    same place. The place comparison is against the EVENT's place, not the
    device rule's own place_id: a group rule with place_id=None covers every
    place (engines.md match()), and a place-scoped group rule must still
    suppress an any-place device rule at that place -- comparing the two
    rules' place_id fields against each other missed both crossings.
    """
    for r in rules:
        if not r.enabled or r.group_id is None:
            continue
        if r.group_id not in event.group_ids:
            continue
        if r.place_id is not None and r.place_id != event.place_id:
            continue
        covers_type = (event.event_type == "ENTER" and r.on_enter) or (
            event.event_type == "EXIT" and r.on_exit
        )
        if covers_type and not r.also_notify_members:
            return True
    return False


def in_cooldown(
    rule: Rule,
    channel: str,
    event: DeviceEvent | GroupEvent,
    deliveries: list[Delivery],
    now: datetime.datetime,
) -> bool:
    """Key = (rule.id, channel, event.place_id, subject) per engines.md.

    `subject` (device_id, or str(group_id) for a group) is not compared
    directly: `match()` already guarantees any delivery under this same
    `rule.id` was sent for this rule's own fixed device_id/group_id (the
    alert_rules XOR CHECK pins exactly one per rule), so filtering on
    rule.id + place_id is equivalent to also filtering on subject.

    The key is per channel (specs/notifications.md § 2): a rule listing both
    native and telegram must cool each down on its own, since a native send
    cannot fail the way a telegram send can and must not gate the other.

    Only a `status == "sent"` delivery starts the cooldown -- a failed or
    skipped send must not suppress the next attempt at the same key, since
    1.0 never retries a delivery on its own (see Delivery.status).
    """
    if rule.cooldown_minutes == 0:
        return False
    kind = "device" if isinstance(event, DeviceEvent) else "group"
    limit = now - datetime.timedelta(minutes=rule.cooldown_minutes)
    return any(
        d.rule_id == rule.id
        and d.channel == channel
        and d.event_kind == kind
        and d.place_id == event.place_id
        and d.status == "sent"
        and d.sent_at is not None
        and d.sent_at > limit
        for d in deliveries
    )


#: The honesty sentence is never truncated away: the variable head is trimmed
#: instead. It is honesty.ALERTS_LATENCY itself, never a second wording --
#: honesty.py says "Never paraphrase or shorten these", and this surface is the
#: one that arrives with no context around it. The old hand-written tail also
#: named Find Hub to Apple-only users (E1 honesty round 2 F6).
_LATENCY_TAIL = f"\n{ALERTS_LATENCY}"


def as_utc(value: datetime.datetime | str | None) -> datetime.datetime | None:
    """Coerce a timestamp to aware UTC.

    Raw ``text()`` SQL bypasses the UtcDateTime decorator, so SQLite hands back
    a plain string for a DATETIME column. Pure (no DB import), so it lives here.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.datetime.fromisoformat(value)
    return value if value.tzinfo else value.replace(tzinfo=datetime.UTC)


def _fmt_local_time(dt: datetime.datetime) -> str:
    """ "Sep 26, 2:12 PM EDT" -- the exact format the delivery log's own row
    uses for every timestamp it shows (alerts_deliveries.js's
    fmtDeliveryTime()), so a delivery's rendered body never reads a
    different clock than its own row for the same instant (UAT7 N06,
    superseding the old same-day/full-date "HH:MM ZZZ" split from R-P2-31:
    always spelling out the date is strictly more honest than the old
    conditional omission, never less). `dt` must already be in the zone to
    render -- callers pass an already zone-converted value."""
    hour12 = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt.strftime('%b')} {dt.day}, {hour12}:{dt.strftime('%M %p %Z')}"


def local_zone() -> datetime.tzinfo:
    """The local timezone render_message() renders alert text in.

    A single seam so tests can pin a zone by patching this function instead
    of setting TZ + calling time.tzset() -- tzset() does not exist on
    Windows, and Windows' astimezone(tz=None) reads the OS setting directly
    rather than the TZ env var anyway (see cli/tests/conftest.py
    `pinned_tz`). Default behaviour is identical to bare astimezone(): the
    machine's real local zone.
    """
    return datetime.datetime.now().astimezone().tzinfo


def render_message(event: DeviceEvent | GroupEvent, now: datetime.datetime) -> str:
    """One alert line-set.

    Two honesty rules matter here, since an alert arrives with no context:
      - a bare "14:20" reads as today, so Observed/reported always carry the
        full date via `_fmt_local_time()` -- the same formatter the delivery
        log's own row uses (UAT7 N06, R-P2-31 superseding the old same-day/
        full-date split, which read differently between the two surfaces);
      - with no `fetched_at` the lag is unknown, not zero ("0 min late"
        would claim the report was instant).

    Rendered in the local timezone of the machine running Find+, with a zone
    abbreviation on both times (e.g. "2:32 PM EDT") so the text stays
    unambiguous for a reader in a different zone (pin TZ via
    cli/tests/conftest.py `pinned_tz` for deterministic tests).

    `now` is no longer read here (the dropped same-day check was its only
    use) but stays in the signature: dispatch.py/retry.py call every
    render_message() at a fixed instant regardless, and dropping the
    parameter would only churn every call site for no behaviour change.
    """
    subject = event.device_name if isinstance(event, DeviceEvent) else event.group_name
    verb = "arrived at" if event.event_type == "ENTER" else "left"
    observed = as_utc(event.observed_at)
    ft = as_utc(getattr(event, "fetched_at", None))
    zone = local_zone()
    observed_local = observed.astimezone(zone)
    obs = _fmt_local_time(observed_local)
    rep = _fmt_local_time(ft.astimezone(zone)) if ft else "unknown"
    lag = f"{round((ft - observed).total_seconds() / 60)} min late" if ft else "lag unknown"
    note = getattr(event, "note", "")
    msg = (
        f"{subject} {verb} {event.place_name}\n"
        f"Observed {obs} · reported {rep} · {lag}\n"
        f"Confidence: {event.confidence}."
    )
    budget = 400 - len(_LATENCY_TAIL)
    if note:
        # A note is one honesty sentence of its own ("...which does not mean
        # they were left behind"). Half of it is worse than none of it, so it
        # goes in whole or not at all rather than being sliced mid-clause.
        with_note = f"{msg} {note}"
        msg = with_note if len(with_note) <= budget else msg
    return msg[:budget] + _LATENCY_TAIL
