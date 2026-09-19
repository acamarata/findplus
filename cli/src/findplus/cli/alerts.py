"""CLI for managing alert channels, rules, and delivery history.

Purpose    : telegram/webhook channel setup, alert rules CRUD, and the
             delivery log, all without a running daemon.
Inputs     : Click options/arguments (see specs/cli-reference.md § alerts).
Outputs    : Table/JSON to stdout; a rule id or error to stderr on add.
Constraints: Channel commands call alerts.store/channels directly; rules and
             deliveries use direct DB access via session_scope (mirrors
             cli/places.py and cli/groups.py).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime

import click

from findplus.alerts.channels.telegram import send, telegram_setup
from findplus.alerts.channels.webhook import build_payload, send_webhook
from findplus.alerts.store import AlertsChannels, WebhookCreds, load_alerts, save_alerts
from findplus.db.models_alerts import AlertDelivery, AlertRule
from findplus.db.session import session_scope

alerts_cmd = click.Group(name="alerts", help="Manage alert channels, rules, and delivery history.")

_WEBHOOK_URL_RE = re.compile(r"^https://|^http://(127\.|localhost)")


@alerts_cmd.command("telegram-setup")
@click.option("--token", "-t", default=None, help="Bot token (prompted if omitted).")
@click.option("--wait", default=120, show_default=True, help="Seconds to wait for a message.")
def telegram_setup_cmd(token: str | None, wait: int) -> None:
    """Connect a Telegram bot: verify the token, then wait for the user to message it."""
    if not token:
        token = click.prompt("Telegram bot token", hide_input=True)
    click.echo(f"Waiting up to {wait} s for a message from Telegram...")
    try:
        result = telegram_setup(token, wait_seconds=wait, poll=2)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    except TimeoutError as exc:
        raise click.ClickException(f"No message received within {wait} s") from exc
    click.echo(
        f"\nConnected: chat '{result['chat_title']}' "
        f"({result['chat_type']}, id={result['chat_id']})"
    )


@alerts_cmd.command("telegram-clear")
@click.option("--yes", is_flag=True, help="Confirm clearing the Telegram configuration.")
def telegram_clear(yes: bool) -> None:
    """Remove the stored Telegram bot token and chat id."""
    if not yes:
        raise click.ClickException("Pass --yes to confirm clearing Telegram configuration")
    ch = load_alerts()
    save_alerts(AlertsChannels(telegram=None, webhook=ch.webhook))
    click.echo("Telegram channel cleared.")


@alerts_cmd.command("webhook-set")
@click.argument("url")
@click.option("--secret", "-s", default=None, help="HMAC signing secret (optional).")
def webhook_set_cmd(url: str, secret: str | None) -> None:
    """Configure the webhook channel."""
    if not _WEBHOOK_URL_RE.match(url):
        raise click.ClickException("URL must be https or http loopback")
    ch = load_alerts()
    save_alerts(AlertsChannels(telegram=ch.telegram, webhook=WebhookCreds(url=url, secret=secret)))
    click.echo(f"Webhook configured: {url}")


@alerts_cmd.command("webhook-clear")
@click.option("--yes", is_flag=True, help="Confirm clearing the webhook configuration.")
def webhook_clear_cmd(yes: bool) -> None:
    """Remove the stored webhook URL and secret."""
    if not yes:
        raise click.ClickException("Pass --yes to confirm")
    ch = load_alerts()
    save_alerts(AlertsChannels(telegram=ch.telegram, webhook=None))
    click.echo("Webhook cleared.")


@alerts_cmd.command("test")
@click.option("--channel", type=click.Choice(["telegram", "webhook"]), required=True)
def test_cmd(channel: str) -> None:
    """Send a test alert through the given channel."""
    ch = load_alerts()
    if channel == "telegram":
        if not ch.telegram:
            raise click.ClickException("Telegram not configured")
        result = send("Find+ test alert", ch.telegram.bot_token, ch.telegram.chat_id)
    else:
        if not ch.webhook:
            raise click.ClickException("Webhook not configured")
        payload = build_payload(
            "ENTER",
            "device",
            "test",
            "Test Tag",
            0,
            "Test Place",
            datetime.now(UTC),
            None,
            0,
            "high",
            "This is a test alert.",
        )
        result = send_webhook(payload, ch.webhook.url, ch.webhook.secret)
    if result.success:
        click.echo(f"Test alert sent via {channel}.")
    else:
        raise click.ClickException(f"Send failed: {result.error}")


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
    "channel",
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
        r.channel,
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
    for i, name, place_id, group_id, device_id, *_rest, channel, _cd, enabled, _n in records:
        click.echo(
            f"{i:<5}{name:<16}{place_id or '':>7}{group_id or '':>7}"
            f"{device_id or '':<10}{channel:<10}{enabled!s:>8}"
        )


@rules_cmd.command("add")
@click.argument("name")
@click.option("--group", "group_id", type=int, default=None)
@click.option("--device-id", default=None)
@click.option("--place", "place_id", type=int, default=None)
@click.option("--enter/--no-enter", default=True)
@click.option("--exit/--no-exit", "exit_", default=True)
@click.option("--channel", type=click.Choice(["telegram", "webhook"]), required=True)
@click.option("--cooldown", default=30, show_default=True)
@click.option("--also-notify-members", is_flag=True, default=False)
def rules_add(
    name: str,
    group_id: int | None,
    device_id: str | None,
    place_id: int | None,
    enter: bool,
    exit_: bool,
    channel: str,
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
            channel=channel,
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
    click.echo(f"{'ID':<6}{'RULE':<16}{'KIND':<8}{'SENT_AT':<26}{'STATUS':<8}")
    for d, rule_name in rows:
        click.echo(
            f"{d.id:<6}{rule_name:<16}{d.event_kind or '':<8}"
            f"{d.sent_at.isoformat():<26}{d.status or '':<8}"
        )
