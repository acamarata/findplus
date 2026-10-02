"""Alert text for a person crossing or a left-behind tracker (spec § 5.4).

Purpose : "Zaid just arrived at Grandma's" / "Zaid left Home at Sep 26, 7:40 AM
          EDT", then which tracker saw it and how late, then the evidence
          sentence, then honesty.ALERTS_LATENCY verbatim.
Inputs  : A GroupEvent with basis='person', or a LeftBehindEvent; `now`, the
          send instant (dispatch) or the first attempt's instant (retry).
Outputs : The message string, at most 400 characters before the honesty tail.
Constraints: "just" only when the sighting is under JUST_MINUTES old at `now`;
          otherwise the time (spec Q2: alerts are often 10 to 40 minutes
          late). No coordinates in a message. The evidence sentence goes in
          whole or not at all. Strings come from en.json `people.msg.*`.
"""

from __future__ import annotations

import datetime

from findplus.alerts.dispatch_core import _LATENCY_TAIL, GroupEvent, LeftBehindEvent, as_utc
from findplus.people import messages as m

#: A sighting younger than this may say "just".
JUST_MINUTES = 10
_BUDGET = 400 - len(_LATENCY_TAIL)


def headline(event: GroupEvent, now: datetime.datetime) -> str:
    """The first line: who, which way, where, and "just" or the time."""
    observed = as_utc(event.observed_at)
    fresh = as_utc(now) - observed < datetime.timedelta(minutes=JUST_MINUTES)
    verb = "arrived" if event.event_type == "ENTER" else "left"
    key = f"msg.{verb}Just" if fresh else f"msg.{verb}At"
    return m.t(key, name=event.group_name, place=event.place_name, time=m.fmt_time(observed))


def evidence_line(tracker: str | None, observed, fetched) -> str:
    """'Seen by Zaid Shoes Red · reported Sep 26, 4:31 PM EDT · 19 min late'."""
    observed = as_utc(observed)
    fetched = as_utc(fetched)
    if fetched is None:
        reported, lag = m.t("msg.reportedUnknown"), m.t("msg.lagUnknown")
    else:
        reported = m.fmt_time(fetched)
        lag = m.t("msg.lagMinutes", minutes=round((fetched - observed).total_seconds() / 60))
    return m.t("msg.seenBy", tracker=tracker or m.t("role.other"), reported=reported, lag=lag)


def _fit(lines: list[str], note: str) -> str:
    msg = "\n".join(lines)
    if note and len(f"{msg}\n{note}") <= _BUDGET:
        msg = f"{msg}\n{note}"
    return msg[:_BUDGET] + _LATENCY_TAIL


def _left_behind(event: LeftBehindEvent) -> str:
    place = event.place_name or m.t("msg.unnamedSpot")
    what = m.role_word(event.role) if event.role else event.device_name
    first = m.t("msg.leftBehind", name=event.group_name, what=what, place=place,
                time=m.fmt_time(event.observed_at))  # fmt: skip
    lines = [first, evidence_line(event.device_name, event.observed_at, event.fetched_at)]
    note = ""
    if event.person_place and event.person_seen_at:
        note = m.t("msg.leftBehindPerson", name=event.group_name, place=event.person_place,
                   time=m.fmt_time(event.person_seen_at),
                   tracker=event.person_lead_name or m.t("role.other"))  # fmt: skip
    return _fit(lines, note)


def render_person_message(event: GroupEvent | LeftBehindEvent, now: datetime.datetime) -> str:
    """The full alert text for a person event or a left-behind episode."""
    if isinstance(event, LeftBehindEvent):
        return _left_behind(event)
    lines = [headline(event, now), evidence_line(event.lead_name, event.observed_at,
                                                 event.fetched_at)]  # fmt: skip
    return _fit(lines, event.note or "")
