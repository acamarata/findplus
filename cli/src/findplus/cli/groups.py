"""CLI for managing device groups and viewing presence/quorum events.

Purpose    : list/add/edit/remove groups, manage membership, and diagnose
             presence and group crossings without a running daemon.
Inputs     : Click options/arguments (see specs/cli-reference.md § groups).
Outputs    : Table/JSON/CSV to stdout; a group id or error to stderr on add.
Constraints: Direct DB access via session_scope and findplus.groups.repo —
             no HTTP calls to the daemon (mirrors cli/places.py).
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime

import click
from sqlalchemy.exc import IntegrityError

from findplus.config import get_settings
from findplus.db.models import Group
from findplus.db.session import session_scope
from findplus.groups.presence import verdict_label
from findplus.groups.repo import (
    build_presence,
    create_group,
    delete_group,
    list_group_place_events,
    list_groups,
    set_members,
    update_group,
)

groups_cmd = click.Group(name="groups", help="Manage device groups and view presence.")

_GROUP_KEYS = ("id", "name", "color", "quorum", "cluster_radius", "stale_after", "members")
_EVENT_KEYS = (
    "id",
    "group",
    "place",
    "type",
    "observed_at",
    "crossed",
    "considered",
    "confidence",
)


def _group_values(g: Group) -> tuple:
    return (
        g.id,
        g.name,
        g.color,
        g.quorum,
        g.cluster_radius_meters,
        g.stale_after_minutes,
        len(getattr(g, "_members", [])),
    )


def _event_values(e: dict) -> tuple:
    return (
        e["id"],
        e["group_name"],
        e["place_name"],
        e["event_type"],
        e["observed_at"].isoformat() + "Z",
        e["members_crossed"],
        e["members_considered"],
        e["confidence"],
    )


@groups_cmd.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def list_groups_cmd(as_json: bool) -> None:
    """List every device group."""
    with session_scope() as s:
        rows = list_groups(s)
    if as_json:
        out = [dict(zip(_GROUP_KEYS, _group_values(r), strict=True)) for r in rows]
        click.echo(json.dumps(out, indent=2))
        return
    click.echo(
        f"{'ID':<5}{'NAME':<20}{'COLOR':<10}{'QUORUM':<10}{'RADIUS':>8}{'STALE':>7}{'MEMBERS':>9}"
    )
    for i, name, color, quorum, radius, stale, members in map(_group_values, rows):
        click.echo(f"{i:<5}{name:<20}{color:<10}{quorum:<10}{radius:>8}{stale:>7}{members:>9}")


@groups_cmd.command("add")
@click.argument("name")
@click.option("--color", default="#27ae60", show_default=True)
@click.option("--quorum", default="majority", show_default=True)
@click.option("--cluster-radius", "cluster_radius_meters", default=150, type=int, show_default=True)
@click.option("--stale-after", "stale_after_minutes", default=90, type=int, show_default=True)
@click.option("--member", "member_ids", multiple=True, help="Device id; repeatable.")
def add_group_cmd(name, color, quorum, cluster_radius_meters, stale_after_minutes, member_ids):
    """Create a new device group."""
    with session_scope() as s:
        try:
            g = create_group(
                s,
                name=name,
                color=color,
                quorum=quorum,
                cluster_radius_meters=cluster_radius_meters,
                stale_after_minutes=stale_after_minutes,
                member_ids=list(member_ids),
            )
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        except IntegrityError as exc:
            s.rollback()
            if "UNIQUE" not in str(exc):
                raise
            click.echo("Error: name already exists", err=True)
            sys.exit(1)
        s.commit()
        group_id, group_name = g.id, g.name
    click.echo(f"Created group {group_id}: {group_name}")


@groups_cmd.command("edit")
@click.argument("group_id", type=int)
@click.option("--name", default=None)
@click.option("--color", default=None)
@click.option("--quorum", default=None)
@click.option("--cluster-radius", "cluster_radius_meters", default=None, type=int)
@click.option("--stale-after", "stale_after_minutes", default=None, type=int)
def edit_group_cmd(group_id, name, color, quorum, cluster_radius_meters, stale_after_minutes):
    """Update one or more fields of an existing group."""
    fields = {
        "name": name,
        "color": color,
        "quorum": quorum,
        "cluster_radius_meters": cluster_radius_meters,
        "stale_after_minutes": stale_after_minutes,
    }
    with session_scope() as s:
        try:
            update_group(s, group_id, **fields)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
    click.echo(f"Updated group {group_id}")


@groups_cmd.command("remove")
@click.argument("group_id", type=int)
@click.option("--yes", is_flag=True, help="Confirm removal.")
def remove_group_cmd(group_id, yes):
    """Delete a group and its membership rows."""
    with session_scope() as s:
        group = s.get(Group, group_id)
        if group is None:
            click.echo("Error: group not found", err=True)
            sys.exit(1)
        name = group.name
    if not yes:
        click.confirm(f"Remove group {name} and all its members?", abort=True)
    with session_scope() as s:
        delete_group(s, group_id)
    click.echo("Removed.")


@groups_cmd.command("members")
@click.argument("group_id", type=int)
@click.option("--set", "member_ids_csv", required=True, help="Comma-separated device ids.")
def members_cmd(group_id, member_ids_csv):
    """Replace a group's membership (full replace, not merge)."""
    member_ids = [m.strip() for m in member_ids_csv.split(",") if m.strip()]
    with session_scope() as s:
        try:
            g = set_members(s, group_id, member_ids)
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        names = [m["device_id"] for m in g._members]
    click.echo(f"Members: {', '.join(names) if names else '(none)'}")


@groups_cmd.command("presence")
@click.argument("group_id", type=int)
@click.option("--window", default=60, type=int, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def presence_cmd(group_id, window, as_json):
    """Show live group presence: verdict, note, and a per-device table."""
    with session_scope() as s:
        group = s.get(Group, group_id)
        if group is None:
            click.echo("Error: group not found", err=True)
            sys.exit(1)
        movement_threshold_meters = get_settings().movement_threshold_meters
        presence, statuses = build_presence(s, group, window, movement_threshold_meters)

    if as_json:
        # `members` matches GET /api/groups/{id}/presence (api-contract.md):
        # a script driving the CLI gets the same per-device rows as the API,
        # not just the group verdict.
        click.echo(
            json.dumps(asdict(presence) | {"members": [asdict(s2) for s2 in statuses]}, default=str)
        )
        return

    # The same phrase the dashboard and the widget show, not the raw enum.
    click.echo(
        "Verdict: "
        + verdict_label(
            presence.verdict,
            diverged=presence.diverged,
            reporting_count=presence.reporting_count,
            considered_count=presence.considered_count,
        )
    )
    click.echo(presence.note)
    click.echo(f"{'DEVICE':<14}{'NAME':<16}{'STATUS':<18}{'PLACE':<14}{'AGE_MIN':>8}{'STALE':>7}")
    for s2 in statuses:
        # Read the member's own status, not a name lookup in presence.stale:
        # two trackers can share a display name and would both be flagged.
        stale = "Y" if s2.status == "stale" else "N"
        age = s2.age_minutes if s2.age_minutes is not None else ""
        place = s2.place or ""
        click.echo(f"{s2.device_id:<14}{s2.name:<16}{s2.status:<18}{place:<14}{age!s:>8}{stale:>7}")


@groups_cmd.command("events")
@click.option("--group", "group_id", default=None, type=int)
@click.option("--place", "place_id", default=None, type=int)
@click.option("--since", default=None)
@click.option("--until", default=None)
@click.option("--limit", default=200, type=int, show_default=True)
@click.option(
    "--format",
    "fmt",
    default="table",
    show_default=True,
    type=click.Choice(["table", "csv", "json"]),
)
def events_cmd(group_id, place_id, since, until, limit, fmt):
    """List group ENTER/EXIT crossings that met quorum."""
    with session_scope() as s:
        rows = list_group_place_events(
            s,
            group_id=group_id,
            place_id=place_id,
            since=_parse_iso(since),
            until=_parse_iso(until),
            limit=limit,
        )
    records = [_event_values(r) for r in rows]

    if fmt == "json":
        out = [dict(zip(_EVENT_KEYS, rec, strict=True)) for rec in records]
        click.echo(json.dumps(out, indent=2))
    elif fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(_EVENT_KEYS)
        w.writerows(records)
    else:
        click.echo(
            f"{'ID':<6}{'GROUP':<16}{'PLACE':<16}{'TYPE':<6}{'OBSERVED':<26}{'X/N':<7}{'CONF'}"
        )
        for i, group, place, etype, observed, crossed, considered, conf in records:
            click.echo(
                f"{i:<6}{group:<16}{place:<16}{etype:<6}{observed:<26}{f'{crossed}/{considered}':<7}{conf}"
            )


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
