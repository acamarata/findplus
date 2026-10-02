"""Plain-text rendering of a day summary for Telegram, the CLI and MCP (spec § 7.2).

Purpose    : "Sumayah's day, Mon Sep 21" then one "- time what (tracker)" line per
             entry, a footer for sightings left out, and the latency and
             approximate-times sentences ONCE at the end.
Inputs     : The dict from people/day_load.day_payload (or the same JSON).
Outputs    : One clean plain-text string (no markup, so Telegram never mangles it).
Constraints: Never adds a claim the payload does not carry. The honesty
             sentences come from findplus.honesty verbatim.
"""

from __future__ import annotations

from datetime import date

from findplus import honesty
from findplus.people.day_text import date_label, day_t


def _line(line: dict) -> str:
    via = line.get("via") or ""
    return day_t("via", text=line["text"], via=via) if via else line["text"]


def heading(payload: dict) -> str:
    when = date_label(date.fromisoformat(payload["date"]))
    return day_t("headingDate", name=payload["person"]["name"], date=when)


def render_text(payload: dict, *, notices: bool = True) -> str:
    """The message body. `notices=False` leaves the two honesty sentences off (CLI --json)."""
    parts = [heading(payload), ""]
    if payload["lines"]:
        parts += [f"- {_line(line)}" for line in payload["lines"]]
    else:
        parts.append(day_t("empty", name=payload["person"]["name"]))
    if payload.get("suspect_text"):
        parts += ["", payload["suspect_text"]]
    if notices:
        parts += ["", honesty.ALERTS_LATENCY, honesty.TRIPS_APPROXIMATE]
    return "\n".join(parts)
