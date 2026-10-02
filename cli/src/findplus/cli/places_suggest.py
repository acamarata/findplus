"""`findplus places suggest`: the places Find+ noticed in the history.

Purpose    : Show likely places (home, a regular school or work stop, a weekend
             stop) from the last 30 days, so the owner can name them with
             `findplus places add`. Nothing is saved here.
Inputs     : --days, --date, --json, --timezone.
Outputs    : A table (or JSON) of candidates with the coordinates found in the data.
Constraints: Direct DB read, no daemon call. Suggestions are guesses with a
             question mark, never names.
"""

from __future__ import annotations

import json
from datetime import date

import click

from findplus.db.session import session_scope
from findplus.places.suggest_service import LOOKBACK_DAYS, suggestions
from findplus.timeline import local_zone

from ._fmt import _render_table
from .places import places_cmd

_GUESS = {"home": "Home?", "school_or_work": "School or work?", "regular": "Regular stop"}
_DAYS = {"weekdays": "weekdays", "weekends": "weekends", "every_day": "most days"}


def _clock(minute: int) -> str:
    hour, mm = divmod(minute % 1440, 60)
    return f"{(hour % 12) or 12}:{mm:02d} {'AM' if hour < 12 else 'PM'}"


def _typical(t: dict) -> str:
    return f"{_clock(t['start_min'])} to {_clock(t['end_min'])}, {_DAYS[t['days']]}"


@places_cmd.command("suggest")
@click.option("--days", default=LOOKBACK_DAYS, type=click.IntRange(3, 31), show_default=True)
@click.option("--timezone", default=None, help="IANA zone; default is this computer's.")
@click.option("--date", "last_day", default=None, help="Last local day to look at (YYYY-MM-DD).")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def suggest_cmd(days: int, timezone: str | None, last_day: str | None, as_json: bool) -> None:
    """List places Find+ noticed from long stays (nothing is saved)."""
    with session_scope() as s:
        today = date.fromisoformat(last_day) if last_day else None
        found = suggestions(s, local_zone(timezone), today=today, days=days)["candidates"]
    if as_json:
        click.echo(json.dumps(found, indent=2))
        return
    if not found:
        click.echo("Not enough history yet. Find+ needs a few days of sightings to suggest places.")
        return
    rows = [
        (
            _GUESS[c["kind_guess"]],
            f"{c['lat']:.6f}",
            f"{c['lon']:.6f}",
            c["radius_m"],
            c["visits"],
            c["nights"],
            _typical(c["typical"]),
            ", ".join(c["trackers"]),
        )
        for c in found
    ]
    _render_table(
        ("GUESS", "LAT", "LON", "RADIUS", "VISITS", "NIGHTS", "USUALLY", "TRACKERS"),
        "<>>>>><<",
        rows,
    )
    click.echo("Name one with: findplus places add NAME --lat LAT --lon LON --radius RADIUS")
