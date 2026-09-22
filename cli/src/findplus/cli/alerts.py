"""CLI for managing alert rules and delivery history.

Purpose    : Alert rules CRUD and the delivery log, all without a running
             daemon. Channel setup (telegram/webhook/whatsapp) and the
             "test" send live in alerts_channels.py (PRI hard rule 7:
             <=300 lines/file) and are attached here via register().
Inputs     : Click options/arguments (see specs/cli-reference.md § alerts).
Outputs    : Table/JSON to stdout; a rule id or error to stderr on add.
Constraints: Rules and deliveries use direct DB access via session_scope
             (mirrors cli/places.py and cli/groups.py).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import click

from findplus.alerts.channels_field import format_channels
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.session import session_scope

from . import alerts_channels

alerts_cmd = click.Group(name="alerts", help="Manage alert channels, rules, and delivery history.")
alerts_channels.register(alerts_cmd)


rules_cmd = click.Group(name="rules", help="Manage alert rules.")
alerts_cmd.add_command(rules_cmd)

_RULE_KEYS = (
    "id",
    "name",
    "place_id",
    "group_id",
    "device_id",
    "on_enter",
    "on_exit",
    "channels",
    "cooldown_minutes",
    "enabled",
    "also_notify_members",
)


def _rule_row(r: AlertRule) -> tuple:
    return (
        r.id,
        r.name,
        r.place_id,
        r.group_id,
        r.device_id,
        r.on_enter,
        r.on_exit,
        # The stored comma string, shown as-is: re-parsing it to a list only to
        # re-join it for display would buy nothing.
        r.channels,
        r.cooldown_minutes,
        r.enabled,
        r.also_notify_members,
    )


@rules_cmd.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def rules_list(as_json: bool) -> None:
    """List every alert rule."""
    with session_scope() as s:
        rows = s.query(AlertRule).order_by(AlertRule.id).all()
        records = [_rule_row(r) for r in rows]
    if as_json:
        click.echo(json.dumps([dict(zip(_RULE_KEYS, r, strict=True)) for r in records], indent=2))
        return
    click.echo(
        f"{'ID':<5}{'NAME':<16}{'PLACE':>7}{'GROUP':>7}{'DEVICE':<10}{'CHANNEL':<10}{'ENABLED':>8}"
    )
    for i, name, place_id, group_id, device_id, *_rest, channels, _cd, enabled, _n in records:
        click.echo(
            f"{i:<5}{name:<16}{place_id or '':>7}{group_id or '':>7}"
            f"{device_id or '':<10}{channels:<10}{enabled!s:>8}"
        )


@rules_cmd.command("add")
@click.argument("name")
@click.option("--group", "group_id", type=int, default=None)
@click.option("--device-id", default=None)
@click.option("--place", "place_id", type=int, default=None)
@click.option("--enter/--no-enter", default=True)
@click.option("--exit/--no-exit", "exit_", default=True)
@click.option(
    "--channel",
    "channels",
    multiple=True,
    required=True,
    type=click.Choice(["telegram", "webhook", "whatsapp", "native"]),
    help="Repeatable: --channel telegram --channel native.",
)
@click.option("--cooldown", default=30, show_default=True)
@click.option("--also-notify-members", is_flag=True, default=False)
def rules_add(
    name: str,
    group_id: int | None,
    device_id: str | None,
    place_id: int | None,
    enter: bool,
    exit_: bool,
    channels: tuple[str, ...],
    cooldown: int,
    also_notify_members: bool,
) -> None:
    """Create an alert rule for a place, targeting a group or a single device."""
    if (group_id is None) == (device_id is None):
        raise click.ClickException("Provide exactly one of --group or --device-id")
    with session_scope() as s:
        rule = AlertRule(
            name=name,
            place_id=place_id,
            group_id=group_id,
            device_id=device_id,
            on_enter=enter,
            on_exit=exit_,
            channels=format_channels(list(channels)),
            cooldown_minutes=cooldown,
            enabled=True,
            also_notify_members=also_notify_members,
            created_at=datetime.now(UTC),
        )
        s.add(rule)
        s.commit()
        rule_id = rule.id
    click.echo(f"Created rule {rule_id}: {name}")


@rules_cmd.command("remove")
@click.argument("id", type=int)
@click.option("--yes", is_flag=True, help="Confirm removal.")
def rules_remove(id: int, yes: bool) -> None:
    """Delete an alert rule."""
    with session_scope() as s:
        rule = s.get(AlertRule, id)
        if rule is None:
            click.echo("Error: rule not found", err=True)
            sys.exit(1)
        name = rule.name
        if not yes:
            click.confirm(f"Remove rule {name}?", abort=True)
        s.delete(rule)
        s.commit()
    click.echo("Removed.")


@alerts_cmd.command("deliveries")
@click.option("--limit", default=100, show_default=True)
def deliveries_cmd(limit: int) -> None:
    """Show the most recent alert deliveries, newest first."""
    with session_scope() as s:
        rows = (
            s.query(AlertDelivery, AlertRule.name)
            .join(AlertRule, AlertRule.id == AlertDelivery.rule_id)
            .order_by(AlertDelivery.sent_at.desc())
            .limit(limit)
            .all()
        )
    click.echo(
        f"{'ID':<6}{'RULE':<16}{'KIND':<8}{'SENT_AT':<26}{'STATUS':<10}{'ATTEMPTS':<9}NEXT_ATTEMPT"
    )
    for d, rule_name in rows:
        next_attempt = d.next_attempt_at.isoformat() if d.next_attempt_at else ""
        click.echo(
            f"{d.id:<6}{rule_name:<16}{d.event_kind or '':<8}"
            f"{d.sent_at.isoformat():<26}{d.status or '':<10}{d.attempts:<9}{next_attempt}"
        )
