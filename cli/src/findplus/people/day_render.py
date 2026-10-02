"""Plain-text rendering of a day summary for Telegram, the CLI and MCP (spec § 7.2).

Purpose    : "Robin's day, Mon Sep 21" then one "- time what (tracker)" line per
             entry, a footer for sightings left out, and the latency and
             approximate-times sentences ONCE at the end. render_combined puts
             the whole family in one message the same way.
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
    """The line with its trackers: "(shoes)", or folded into a closing bracket
    the text already has: "(seen 7:40 AM; bag and bike)", never two (uat116 #13)."""
    via = line.get("via") or ""
    text = line["text"]
    if not via:
        return text
    if text.endswith(")"):
        return f"{text[:-1]}; {via})"
    return day_t("via", text=text, via=via)


def heading(payload: dict) -> str:
    when = date_label(date.fromisoformat(payload["date"]))
    return day_t("headingDate", name=payload["person"]["name"], date=when)


def _body(payload: dict) -> list[str]:
    """One person's lines, or the empty sentence, then what was left out."""
    if payload["lines"]:
        parts = [f"- {_line(line)}" for line in payload["lines"]]
    else:
        parts = [day_t("empty", name=payload["person"]["name"])]
    if payload.get("suspect_text"):
        parts += ["", payload["suspect_text"]]
    return parts


def _notices() -> list[str]:
    return ["", honesty.ALERTS_LATENCY, honesty.TRIPS_APPROXIMATE]


def render_text(payload: dict, *, notices: bool = True) -> str:
    """The message body. `notices=False` leaves the two honesty sentences off (CLI --json)."""
    parts = [heading(payload), "", *_body(payload)]
    return "\n".join(parts + (_notices() if notices else []))


def render_combined(payloads: list[dict]) -> str:
    """One family message: a heading, then each person's name and lines, then
    the honesty sentences once. A single person reads exactly like render_text."""
    if len(payloads) == 1:
        return render_text(payloads[0])
    when = date_label(date.fromisoformat(payloads[0]["date"]))
    parts = [day_t("familyHeading", date=when)]
    for payload in payloads:
        parts += ["", payload["person"]["name"], *_body(payload)]
    return "\n".join(parts + _notices())
