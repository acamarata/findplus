"""CLI: `findplus day <name>` and `findplus people digest` (spec § 7.2).

Purpose    : The command-line twin of GET /api/people/{id}/day: "Sumayah's day"
             in plain words, optionally sent to Telegram now; and the switch for
             the evening summary (`people.digest`).
Inputs     : A person's name (or numeric id), --date, --days, --json, --send;
             for digest: --on/--off, --time, --person, --all-people, --channel,
             --always-send/--no-always-send.
Outputs    : Text (the same lines Telegram gets), or JSON with --json (a list
             when --days is more than 1).
Constraints: Reads the local database directly (no daemon needed). Exit 1 with a
             message on an unknown or ambiguous name, a bad date or zone, or a
             send with no Telegram chat connected. Nothing here edits history.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta

import click
from sqlalchemy import select

from findplus import honesty
from findplus.db.models import Group
from findplus.db.models_people import PERSON_KINDS
from findplus.db.session import session_scope
from findplus.people import digest_prefs, repo
from findplus.people.day_load import day_payload
from findplus.people.day_render import render_text
from findplus.service import digest_send
from findplus.timeline import local_zone

MAX_DAYS = 14


def _fail(message: str) -> None:
    click.echo(f"Error: {message}", err=True)
    sys.exit(1)


def find_person(session, who: str) -> Group:
    """A person or pet by id, exact name, or unique name prefix (any letter case)."""
    rows = list(session.scalars(select(Group).where(Group.kind.in_(PERSON_KINDS))).all())
    if who.isdigit():
        hit = [r for r in rows if r.id == int(who)]
    else:
        key = who.casefold()
        hit = [r for r in rows if r.name.casefold() == key] or [
            r for r in rows if r.name.casefold().startswith(key)
        ]
    if not hit:
        _fail(f"no person named {who!r}. Run `findplus people list`.")
    if len(hit) > 1:
        _fail(f"{who!r} matches {', '.join(r.name for r in hit)}. Use the full name or the id.")
    return hit[0]


def _zone(name: str | None):
    try:
        return local_zone(name)
    except Exception:
        _fail(f"unknown timezone {name!r}")


def _day(value: str | None, tz) -> date:
    if not value:
        return datetime.now(UTC).astimezone(tz).date()
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail(f"invalid date {value!r}, expected YYYY-MM-DD")


@click.command("day")
@click.argument("who")
@click.option("--date", "date_text", default=None, help="Local date, YYYY-MM-DD (default today).")
@click.option("--days", type=click.IntRange(1, MAX_DAYS), default=1, help="Consecutive days.")
@click.option("--timezone", default=None, help="IANA zone (default this computer's).")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.option(
    "--send", "send_it", is_flag=True, help="Also send it to the connected Telegram chat."
)
def day_cmd(who, date_text, days, timezone, as_json, send_it) -> None:
    """A person's day in plain words: when they left, arrived and where they are."""
    tz = _zone(timezone)
    first = _day(date_text, tz)
    now = datetime.now(UTC)
    with session_scope() as s:
        group = find_person(s, who)
        payloads = [day_payload(s, group, first + timedelta(days=i), tz, now) for i in range(days)]
    if as_json:
        click.echo(json.dumps(payloads[0] if days == 1 else payloads, indent=2))
    else:
        click.echo("\n\n".join(render_text(p, notices=False) for p in payloads))
        click.echo(f"\n{honesty.ALERTS_LATENCY}\n{honesty.TRIPS_APPROXIMATE}")
    if send_it:
        _send(payloads[0])


def _send(payload: dict) -> None:
    creds = digest_send.telegram_creds()
    if creds is None:
        _fail("Telegram is not connected. Connect it in the app, then try again.")
    results = digest_send.send_to_targets(render_text(payload), creds)
    sent = sum(r.ok for r in results)
    click.echo(f"Sent to {sent} of {len(results)} Telegram chat(s).")
    for r in results:
        if not r.ok:
            click.echo(f"  {r.target}: {r.error}", err=True)
    if not sent:
        sys.exit(1)


@click.command("digest")
@click.option("--on/--off", "enabled", default=None, help="Switch the evening summary.")
@click.option("--time", "at_time", default=None, help="HH:MM, 24-hour (default 20:00).")
@click.option("--person", "people", multiple=True, help="Name or id; repeat for several.")
@click.option("--all-people", is_flag=True, help="Send for every person and pet.")
@click.option("--channel", type=click.Choice(list(digest_prefs.CHANNELS)), default=None)
@click.option(
    "--always-send/--no-always-send",
    "always",
    default=None,
    help="Also send on a day with nothing tracked.",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def digest_cmd(enabled, at_time, people, all_people, channel, always, as_json) -> None:
    """Show or change the evening summary (off until you turn it on)."""
    patch: dict = {}
    for name, value in (
        ("enabled", enabled),
        ("time", at_time),
        ("channel", channel),
        ("always_send", always),
    ):
        if value is not None:
            patch[name] = value
    with session_scope() as s:
        if all_people:
            patch["people"] = []
        elif people:
            patch["people"] = [find_person(s, p).id for p in people]
        try:
            prefs = digest_prefs.save(s, patch) if patch else digest_prefs.load(s)
        except ValueError as exc:
            s.rollback()
            _fail(str(exc))
        names = [repo.get_person(s, i).name for i in prefs["people"]]
    if as_json:
        click.echo(json.dumps(prefs, indent=2))
        return
    state = "on" if prefs["enabled"] else "off"
    who = ", ".join(names) if names else "everyone"
    click.echo(f"Evening summary: {state}, {prefs['time']}, for {who}, via {prefs['channel']}.")
