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

from findplus.honesty import ALERTS_LATENCY


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


#: Minutes after the first failure that retry 1/2/3 (attempts 2/3/4) are due.
#: Indexed by `attempts - 1`, where `attempts` is the count already made.
RETRY_OFFSETS_MINUTES = (1, 5, 30)

#: 1 initial send + 3 retries. `attempts` reaching this with no success means
#: give up -- the row's final status is "failed", not "retrying" again.
MAX_ATTEMPTS = 4

_RETRY_CAP = datetime.timedelta(minutes=RETRY_OFFSETS_MINUTES[-1])


def is_transient_failure(status_code: int | None, error: str | None) -> bool:
    """True for a network error, a timeout, HTTP 429, or any 5xx.

    Everything else -- a 4xx other than 429, a channel-unconfigured skip, or a
    credential/shape exception (telegram.py's malformed-token/blocked-bot
    raises, whatsapp_callmebot's malformed-phone/apikey results) -- is
    permanent and must never be retried. Those never produce status_code=429
    or >=500 and never carry the exact literal "timeout" error, so the two
    checks below are sufficient without inspecting the exception type.
    """
    if status_code == 429:
        return True
    if status_code is not None and status_code >= 500:
        return True
    return status_code is None and error == "timeout"


def compute_next_attempt_at(
    sent_at: datetime.datetime,
    attempts: int,
    now: datetime.datetime,
    retry_after_seconds: int | None,
) -> datetime.datetime:
    """When the attempt after `attempts` is due.

    The ladder (RETRY_OFFSETS_MINUTES) is anchored to `sent_at`, the first
    failure -- not to `now` -- so the schedule reads the same regardless of
    when the poller actually gets around to running it. A Retry-After header
    only ever pushes the wait later (never shorter than the ladder's own
    value), and the total wait from the first failure is capped at 30
    minutes either way.
    """
    ladder_at = sent_at + datetime.timedelta(minutes=RETRY_OFFSETS_MINUTES[attempts - 1])
    if retry_after_seconds is not None:
        requested_at = now + datetime.timedelta(seconds=max(0, retry_after_seconds))
        ladder_at = max(ladder_at, requested_at)
    return min(ladder_at, sent_at + _RETRY_CAP)


def classify_new_delivery(
    status: str,
    error: str | None,
    status_code: int | None,
    retry_after_seconds: int | None,
    sent_at: datetime.datetime,
) -> tuple[str, int, datetime.datetime | None]:
    """(status, attempts, next_attempt_at) for a row being written for the
    first time. Only a transient "failed" outcome becomes "retrying"; every
    other status (sent/skipped/queued, or a permanent failure) is stored as
    given, with attempts=1 and nothing scheduled.
    """
    if status == "failed" and is_transient_failure(status_code, error):
        return "retrying", 1, compute_next_attempt_at(sent_at, 1, sent_at, retry_after_seconds)
    return status, 1, None


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


def render_message(event: DeviceEvent | GroupEvent, now: datetime.datetime) -> str:
    """One alert line-set.

    Two honesty rules are load-bearing here, because an alert arrives with no
    surrounding context:
      - a bare "Observed 14:20" reads as today, so the date is spelled out
        whenever the observation fell on a different local day than now;
      - with no `fetched_at` the lag is unknown, not zero. Printing "0 min
        late" would claim the report was instant.
    """
    subject = event.device_name if isinstance(event, DeviceEvent) else event.group_name
    verb = "arrived at" if event.event_type == "ENTER" else "left"
    observed = as_utc(event.observed_at)
    ft = as_utc(getattr(event, "fetched_at", None))
    observed_local = observed.astimezone()
    same_day = observed_local.date() == now.astimezone().date()
    obs = observed_local.strftime("%H:%M" if same_day else "%Y-%m-%d %H:%M %Z")
    rep = ft.astimezone().strftime("%H:%M") if ft else "unknown"
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
