"""Plain-words pieces of the daily summary (spec § 7), read from the locale catalog.

Purpose    : Format clock times in the person's zone and fill the people.day.*
             sentences, so the app, Telegram, the CLI and MCP say the same thing.
Inputs     : tz-aware datetimes, a ZoneInfo, names and distances.
Outputs    : "7:40 AM", "10:05 to 11:20 AM", "around 7:40 AM", sentences.
Constraints: Pure apart from the cached catalog read in people/messages.py.
             "just" is never used in a summary; a time is a time the tag was seen.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from findplus.people import messages as m

#: Largest gap between the two sightings that bracket a time before it is "around".
APPROX_MINUTES = 10
#: Tracker names listed on one line before the rest collapse into "and N more".
MAX_VIA = 2


def day_t(key: str, **values: object) -> str:
    return m.t(f"day.{key}", **values)


def clock(value: datetime, tz: ZoneInfo) -> str:
    """ "7:40 AM" (no leading zero, 12-hour, in `tz`)."""
    local = value.astimezone(tz)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def clock_range(start: datetime, end: datetime, tz: ZoneInfo) -> str:
    """ "10:05 to 11:20 AM" when both share AM/PM, else "11:30 AM to 1:10 PM"."""
    a, b = clock(start, tz), clock(end, tz)
    if a[-2:] == b[-2:]:
        a = a[:-3]
    return day_t("range", start=a, end=b)


def around(text: str) -> str:
    return day_t("approx", time=text)


def date_label(value: datetime | object) -> str:
    """ "Mon Sep 21" for a date (the heading of a Telegram message)."""
    return f"{value.strftime('%a %b')} {value.day}"


def via_text(device_ids, labels: dict[str, str]) -> str:
    """ "shoes and bag"; at most MAX_VIA names, then "and N more"."""
    names = list(dict.fromkeys(labels.get(d, d) for d in device_ids))
    if len(names) > MAX_VIA:
        shown = ", ".join(names[:MAX_VIA])
        return day_t("andMore", names=shown, n=len(names) - MAX_VIA)
    return m.join_words(names)


def suspect_sentence(count: int) -> str | None:
    """ "2 sightings looked wrong and were left out." or None."""
    if count <= 0:
        return None
    return day_t("suspectOne") if count == 1 else day_t("suspectMany", n=count)
