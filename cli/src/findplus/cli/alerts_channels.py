"""CLI for configuring and test-sending alert channels (telegram/webhook/whatsapp).

Purpose    : Channel setup/clear commands and the "test" send, split out of
             alerts.py (PRI hard rule 7: <=300 lines/file) -- mirrors the
             api package's routes_alerts_channels/routes_alerts_rules split.
Inputs     : Click options/arguments (see specs/cli-reference.md § alerts).
Outputs    : Confirmation text to stdout; a click.ClickException on failure.
Constraints: register() attaches every command onto the caller's `alerts_cmd`
             group so `findplus alerts <channel-command>` is unchanged.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import click

from findplus.alerts.channels.telegram import send, telegram_setup
from findplus.alerts.channels.webhook import build_payload, is_valid_url, send_webhook
from findplus.alerts.store import (
    WebhookCreds,
    WhatsappCreds,
    is_valid_apikey,
    is_valid_bot_token,
    is_valid_phone,
    load_alerts,
    mask_phone,
    save_channel,
)
from findplus.alerts.targets import parse_targets


def register(alerts_cmd: click.Group) -> None:
    """Attach every channel-setup command onto the given `alerts` group."""
    alerts_cmd.add_command(telegram_setup_cmd)
    alerts_cmd.add_command(telegram_targets_cmd)
    alerts_cmd.add_command(telegram_clear)
    alerts_cmd.add_command(webhook_set_cmd)
    alerts_cmd.add_command(webhook_clear_cmd)
    alerts_cmd.add_command(whatsapp_cmd)
    alerts_cmd.add_command(test_cmd)


@click.command("telegram-setup")
@click.option("--token", "-t", default=None, help="Bot token (prompted if omitted).")
@click.option("--wait", default=120, show_default=True, help="Seconds to wait for a message.")
def telegram_setup_cmd(token: str | None, wait: int) -> None:
    """Connect a Telegram bot: verify the token, then wait for the user to message it."""
    if not token:
        token = click.prompt("Telegram bot token", hide_input=True)
    if not is_valid_bot_token(token):
        raise click.ClickException("Bot token must look like a BotFather token")
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


@click.command("telegram-clear")
@click.option("--yes", is_flag=True, help="Confirm clearing the Telegram configuration.")
def telegram_clear(yes: bool) -> None:
    """Remove the stored Telegram bot token and chat id."""
    if not yes:
        raise click.ClickException("Pass --yes to confirm clearing Telegram configuration")
    save_channel(telegram=None)
    click.echo("Telegram channel cleared.")


@click.command("telegram-targets")
@click.argument("targets")
def telegram_targets_cmd(targets: str) -> None:
    """Replace the Telegram target list: chat ids or @usernames, comma separated.

    TARGETS accepts your own numeric user id, a group/supergroup id (negative,
    e.g. -1001234567890), an @username, or several of any of those separated
    by commas. Telegram must already be connected (`telegram-setup`) -- this
    only edits which chats an already-connected bot notifies.
    """
    existing = load_alerts()
    if not existing.telegram:
        raise click.ClickException("Telegram not configured -- run telegram-setup first")
    try:
        chat_ids = tuple(parse_targets(targets))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    save_channel(telegram=dataclasses.replace(existing.telegram, chat_ids=chat_ids))
    click.echo(f"Telegram targets set: {', '.join(chat_ids)}")


@click.command("webhook-set")
@click.argument("url")
@click.option("--secret", "-s", default=None, help="HMAC signing secret (optional).")
def webhook_set_cmd(url: str, secret: str | None) -> None:
    """Configure the webhook channel."""
    if not is_valid_url(url):
        raise click.ClickException("URL must be https or http loopback")
    save_channel(webhook=WebhookCreds(url=url, secret=secret))
    click.echo(f"Webhook configured: {url}")


@click.command("webhook-clear")
@click.option("--yes", is_flag=True, help="Confirm clearing the webhook configuration.")
def webhook_clear_cmd(yes: bool) -> None:
    """Remove the stored webhook URL and secret."""
    if not yes:
        raise click.ClickException("Pass --yes to confirm")
    save_channel(webhook=None)
    click.echo("Webhook cleared.")


whatsapp_cmd = click.Group(name="whatsapp", help="Manage the WhatsApp (CallMeBot) channel.")


@whatsapp_cmd.command("set")
@click.option("--phone", required=True, help="E.164 phone number, e.g. +34123123123.")
@click.option("--apikey", required=True, help="CallMeBot API key.")
def whatsapp_set_cmd(phone: str, apikey: str) -> None:
    """Configure the WhatsApp (CallMeBot) channel."""
    if not is_valid_phone(phone):
        raise click.ClickException("phone must be E.164, e.g. +34123123123")
    if not is_valid_apikey(apikey):
        raise click.ClickException("apikey must be alphanumeric, at least 4 characters")
    save_channel(whatsapp=WhatsappCreds(phone=phone, apikey=apikey))
    click.echo(f"WhatsApp configured: {mask_phone(phone)}")


@whatsapp_cmd.command("clear")
@click.option("--yes", is_flag=True, help="Confirm clearing the WhatsApp configuration.")
def whatsapp_clear_cmd(yes: bool) -> None:
    """Remove the stored WhatsApp phone and apikey."""
    if not yes:
        raise click.ClickException("Pass --yes to confirm")
    save_channel(whatsapp=None)
    click.echo("WhatsApp cleared.")


def _test_telegram(ch) -> None:
    """Send to every configured target; one failing target never stops the
    rest, and each target's own outcome is printed (owner ask: per-target
    reporting for "send test", same as the dashboard's POST /api/alerts/test).
    """
    any_failed = False
    for target in ch.telegram.chat_ids:
        try:
            result = send("Find+ test alert", ch.telegram.bot_token, target)
        except (ValueError, RuntimeError) as exc:
            click.echo(f"{target}: failed ({exc})")
            any_failed = True
            continue
        if result.success:
            click.echo(f"{target}: sent")
        else:
            click.echo(f"{target}: failed ({result.error})")
            any_failed = True
    if any_failed:
        raise click.ClickException("one or more Telegram targets failed, see above")


@click.command("test")
@click.option("--channel", type=click.Choice(["telegram", "webhook", "whatsapp"]), required=True)
def test_cmd(channel: str) -> None:
    """Send a test alert through the given channel."""
    ch = load_alerts()
    if channel == "telegram":
        if not ch.telegram or not ch.telegram.chat_ids:
            raise click.ClickException("Telegram not configured")
        _test_telegram(ch)
        return
    elif channel == "webhook":
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
    else:
        if not ch.whatsapp:
            raise click.ClickException("WhatsApp not configured")
        from findplus.alerts.channels.whatsapp_callmebot import send as wa_send

        result = wa_send("Find+ test alert", ch.whatsapp.phone, ch.whatsapp.apikey)
    if result.success:
        click.echo(f"Test alert sent via {channel}.")
    else:
        raise click.ClickException(f"Send failed: {result.error}")
