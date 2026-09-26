"""CLI for managing alert rules and delivery history.

Purpose    : Alert rules CRUD and the delivery log, all without a running
             daemon. Channel setup (telegram/webhook/whatsapp) and the
             "test" send live in alerts_channels.py, and the `--json`/table
             row builders live in alerts_fmt.py (PRI hard rule 7:
             <=300 lines/file) -- both attached/imported here.
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
from sqlalchemy import func, select

from findplus.alerts.channels_field import format_channels
from findplus.alerts.rule_telegram_targets import (
    format_rule_telegram_targets,
    validate_rule_telegram_targets,
)
from findplus.db.models import Device, Group, Place
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.session import session_scope

from . import alerts_channels
from ._fmt import _render_table
from .alerts_fmt import _delivery_records, _delivery_table_rows, _rule_records, _rule_table_rows
from .alerts_rule_telegram import _resolve_telegram_targets_option, _rule_edit_fields

#: A table row's error stays skimmable; the full text is still in the API
#: and the dashboard's delivery log (UAT U23 asked for the column, not for
#: reproducing an unbounded webhook/Telegram error inline).
_ERROR_CELL_MAX = 60

alerts_cmd = click.Group(name="alerts", help="Manage alert channels, rules, and delivery history.")
alerts_channels.register(alerts_cmd)


rules_cmd = click.Group(name="rules", help="Manage alert rules.")
alerts_cmd.add_command(rules_cmd)


def _list_rules(s) -> list[tuple]:
    """Every rule, joined to the place/group/device it targets.

    Same query api/routes_alerts_rules.py's `_list_rules` runs: a raw
    `place_id`/`device_id` in the table read as a floating number nobody
    could place, and `device_id` alone hid a renamed tracker's label behind
    its provider id (UAT U23). `func.coalesce(Device.label, Device.name)`
    matches the rule form's own Device select (UAT U6) -- label first,
    provider name only when unset.
    """
    stmt = (
        select(AlertRule, Place.name, Group.name, func.coalesce(Device.label, Device.name))
        .outerjoin(Place, Place.id == AlertRule.place_id)
        .outerjoin(Group, Group.id == AlertRule.group_id)
        .outerjoin(Device, Device.device_id == AlertRule.device_id)
        .order_by(AlertRule.id)
    )
    return list(s.execute(stmt).all())


@rules_cmd.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def rules_list(as_json: bool) -> None:
    """List every alert rule."""
    with session_scope() as s:
        rows = _list_rules(s)
    if as_json:
        click.echo(json.dumps(_rule_records(rows), indent=2))
        return
    headers = (
        "ID",
        "NAME",
        "PLACE",
        "GROUP",
        "DEVICE",
        "CHANNELS",
        "COOLDOWN",
        "ENABLED",
        "TELEGRAM",
    )
    _render_table(headers, "<<<<<<>><", _rule_table_rows(rows))


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
@click.option(
    "--telegram-target",
    "telegram_targets",
    multiple=True,
    help="Repeatable: limit Telegram delivery to this saved chat id. Omit for every saved target.",
)
@click.option(
    "--telegram-all",
    is_flag=True,
    default=False,
    help="Send to every saved Telegram target (the default).",
)
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
    telegram_targets: tuple[str, ...],
    telegram_all: bool,
) -> None:
    """Create an alert rule for a place, targeting a group or a single device."""
    if (group_id is None) == (device_id is None):
        raise click.ClickException("Provide exactly one of --group or --device-id")
    targets_value = _resolve_telegram_targets_option(telegram_targets, telegram_all)
    try:
        validate_rule_telegram_targets(targets_value)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
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
            telegram_targets=format_rule_telegram_targets(targets_value),
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


@rules_cmd.command("edit")
@click.argument("id", type=int)
@click.option("--name", default=None, help="Rename the rule.")
@click.option("--place", "place_id", type=int, default=None)
@click.option("--enter/--no-enter", default=None)
@click.option("--exit/--no-exit", "exit_", default=None)
@click.option(
    "--channel",
    "channels",
    multiple=True,
    type=click.Choice(["telegram", "webhook", "whatsapp", "native"]),
    help="Repeatable; passing any --channel replaces the whole set.",
)
@click.option("--cooldown", type=int, default=None)
@click.option("--enable/--disable", "enabled", default=None)
@click.option(
    "--telegram-target",
    "telegram_targets",
    multiple=True,
    help="Repeatable: limit Telegram delivery to this saved chat id.",
)
@click.option(
    "--telegram-all",
    is_flag=True,
    default=False,
    help="Switch back to every saved Telegram target.",
)
def rules_edit(
    id: int,
    name: str | None,
    place_id: int | None,
    enter: bool | None,
    exit_: bool | None,
    channels: tuple[str, ...],
    cooldown: int | None,
    enabled: bool | None,
    telegram_targets: tuple[str, ...],
    telegram_all: bool,
) -> None:
    """Edit an alert rule; only the given options change.

    Uses the same PUT /api/alerts/rules/{id} handler the dashboard's edit
    dialog calls (api/routes_alerts_rules.py's `put_rule`/`RuleUpdate`), so
    validation (known channels, at least one connected channel, known
    Telegram targets) matches the UI exactly. There is no `--group`/
    `--device-id` here: `RuleUpdate` has no such field, and the dashboard
    disables both target pickers while editing for the same reason --
    retarget a rule by removing and re-adding it.
    """
    from fastapi import HTTPException

    from findplus.api.routes_alerts_rules import RuleUpdate, put_rule

    fields = _rule_edit_fields(
        name, place_id, enter, exit_, channels, cooldown, enabled, telegram_targets, telegram_all
    )
    if not fields:
        raise click.ClickException("Provide at least one field to change")
    try:
        rule = put_rule(id, RuleUpdate(**fields))
    except HTTPException as exc:
        if exc.status_code == 404:
            click.echo("Error: rule not found", err=True)
            sys.exit(1)
        raise click.ClickException(str(exc.detail)) from exc
    click.echo(f"Updated rule {rule['id']}: {rule['name']}")


@alerts_cmd.command("deliveries")
@click.option("--limit", default=100, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
def deliveries_cmd(limit: int, as_json: bool) -> None:
    """Show the most recent alert deliveries, newest first."""
    with session_scope() as s:
        rows = (
            s.query(AlertDelivery, AlertRule.name)
            .join(AlertRule, AlertRule.id == AlertDelivery.rule_id)
            .order_by(AlertDelivery.sent_at.desc())
            .limit(limit)
            .all()
        )
    if as_json:
        click.echo(json.dumps(_delivery_records(rows), indent=2))
        return
    headers = (
        "ID",
        "RULE",
        "CHANNEL",
        "TARGET",
        "KIND",
        "SENT_AT",
        "STATUS",
        "ATTEMPTS",
        "NEXT_ATTEMPT",
        "ERROR",
    )
    _render_table(headers, "<<<<<<<>><", _delivery_table_rows(rows, _ERROR_CELL_MAX))
