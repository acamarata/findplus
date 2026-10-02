"""CLI for people: list them, preview suggestions, accept, set a tracker's role.

Purpose    : `findplus people list|suggest|accept|set-role`, the command-line
             twin of /api/people (specs/people-and-presence.md § 2, § 7.2).
Inputs     : Click options; the local database (no daemon needed).
Outputs    : A table, or JSON with --json; errors on stderr with exit code 1.
Constraints: Direct DB access via session_scope and findplus.people.* (mirrors
             cli/groups.py). `suggest` never writes; `accept` applies only the
             suggestions named by --key (or every one with --all).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import click

from findplus.db.session import session_scope
from findplus.people import repo, suggestions

people_cmd = click.Group(name="people", help="People and pets built from your trackers.")


def _fail(message: str) -> None:
    click.echo(f"Error: {message}", err=True)
    sys.exit(1)


@people_cmd.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def list_cmd(as_json: bool) -> None:
    """Every person and pet, its trackers and where it likely is now."""
    now = datetime.now(UTC)
    with session_scope() as s:
        rows = [
            {**repo.person_dict(p), "now": repo.now_dict(s, p, now)} for p in repo.list_people(s)
        ]
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("No people yet. Run `findplus people suggest` to see suggestions.")
    for p in rows:
        trackers = ", ".join(f"{t['name']} ({t['role'] or 'tracker'})" for t in p["trackers"])
        click.echo(f"{p['id']}  {p['name']} [{p['kind']}]  {trackers}")
        click.echo(f"    {p['now']['text']}")


@people_cmd.command("suggest")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def suggest_cmd(as_json: bool) -> None:
    """Preview people suggested from tracker names. Nothing is saved."""
    with session_scope() as s:
        preview = suggestions.build(s)
    if as_json:
        click.echo(json.dumps(preview, indent=2))
        return
    for item in preview["suggestions"]:
        click.echo(f"{item['key']}\n    {item['preview']} ({item['confidence']})")
        for extra in (item["question"], item["warning"]):
            if extra:
                click.echo(f"    {extra}")
    for u in preview["unassigned"]:
        click.echo(f"{u['name']}: {u['question']}")
    if not preview["suggestions"] and not preview["unassigned"]:
        click.echo("No suggestions.")


@people_cmd.command("accept")
@click.option("--key", "keys", multiple=True, help="A suggestion key from `people suggest`.")
@click.option("--all", "accept_all", is_flag=True, help="Accept every suggestion as shown.")
@click.option("--dismiss", "dismiss", multiple=True, help="A suggestion key to dismiss.")
@click.option("--kind", type=click.Choice(["person", "pet"]), help="Override the kind.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def accept_cmd(keys, accept_all: bool, dismiss, kind: str | None, as_json: bool) -> None:
    """Create the suggested people (by --key or --all), or dismiss suggestions."""
    if not keys and not accept_all and not dismiss:
        _fail("name at least one --key, --dismiss, or use --all")
    with session_scope() as s:
        preview = suggestions.build(s)["suggestions"]
        chosen = [x for x in preview if accept_all or x["key"] in keys]
        missing = set(keys) - {x["key"] for x in preview}
        if missing:
            _fail(f"no current suggestion with key {sorted(missing)[0]}")
        for item in chosen:
            item["kind"] = kind or item["kind"]
        try:
            result = suggestions.accept(s, chosen, list(dismiss))
        except ValueError as exc:
            s.rollback()
            _fail(str(exc))
        s.commit()
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    for p in result["people"]:
        click.echo(f"Saved {p['kind']} {p['name']} (id {p['id']}).")
    for key in result["dismissed"]:
        click.echo(f"Dismissed {key}.")


@people_cmd.command("set-role")
@click.argument("device_id")
@click.argument("role")
@click.option("--weight", type=float, default=None, help="Carry weight 0 to 1 (default: role's).")
def set_role_cmd(device_id: str, role: str, weight: float | None) -> None:
    """Set a tracker's role (phone, bag, shoes...) and optionally its carry weight."""
    fields: dict = {"role": role}
    if weight is not None:
        fields["carry_weight"] = weight
    with session_scope() as s:
        try:
            d = repo.set_tracker(s, device_id, fields)
        except ValueError as exc:
            s.rollback()
            _fail(str(exc))
        s.commit()
        click.echo(f"{d.device_id}: role {d.role}, weight {d.carry_weight or 'role default'}")
