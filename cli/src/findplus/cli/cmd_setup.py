"""`findplus setup`: headless text wizard mirroring the 8-step web onboarding.

Purpose    : Terminal guided first-run setup for brew/curl-pipe installs that
             never open the dashboard; the one-command target of
             `install.sh --start` (D-P2-10).
Inputs     : --yes (non-interactive: accept every default, skip every optional
             step).
Outputs    : Console prompts (interactive) or one summary line per step
             (--yes). Only the interactive Done step writes
             onboarding.completed_at, via findplus.state.set_setting directly
             (no HTTP call); `--yes` writes onboarding.last_step = "headless"
             instead and leaves completed_at unset, so install.sh --start
             still leaves the web first-run wizard armed (R-P2-24).
Constraints: No browser, no GUI dependency. Every step reuses an existing CLI
             code path (auth, groups, alerts, security), never reimplements
             sign-in, group creation, channel connection or PIN hashing.
             Label/icon/colour are NOT settable here (no terminal colour
             picker) -- the dashboard is the reference surface for those
             (onboarding.md § 6 point 3).
"""

from __future__ import annotations

import click

from findplus.db.session import session_scope
from findplus.state import set_setting

from ._fmt import _prep


@click.command()
@click.option(
    "--yes",
    is_flag=True,
    help="Non-interactive: accept every default, skip every optional step.",
)
def setup(yes: bool) -> None:
    """Guided first-run setup: sign-in, devices, groups, places, notifications, app lock."""
    _prep()
    from findplus.honesty import NOT_AFFILIATED

    click.echo(NOT_AFFILIATED)
    _step_signin(yes)
    _step_devices(yes)
    _step_groups(yes)
    _step_places(yes)
    _step_notifications(yes)
    _step_applock(yes)

    from datetime import UTC, datetime

    with session_scope() as session:
        if yes:
            # R-P2-24: headless --yes never stamps completed_at, so the web
            # wizard still shows on the first dashboard visit after a
            # curl-pipe/brew install.
            set_setting(session, "onboarding.last_step", "headless")
        else:
            set_setting(session, "onboarding.completed_at", datetime.now(UTC).isoformat())
    click.secho("Setup complete. Run `findplus start` to begin polling.", fg="green")


def _step_signin(yes: bool) -> None:
    """Step 2. Offers each provider's existing `findplus auth` branch, never a new one."""
    if yes:
        click.echo("Run `findplus auth` later to sign in.")
        return

    from .cmd_auth import auth as auth_cmd

    for provider, question, default in (
        ("google-find-hub", "Sign in with Google now?", True),
        ("apple-find-my", "Sign in with Apple now?", False),
    ):
        if not click.confirm(question, default=default):
            continue
        try:
            auth_cmd.callback(provider=provider)
        except SystemExit:
            # auth exits 1 when Chrome is missing or a sign-in fails. That ends
            # the sign-in step, not the whole wizard.
            click.secho("Sign-in did not finish. Run `findplus auth` later.", fg="yellow")


def _listed_devices(session):
    """Every known device in the order the wizard prints them (by name)."""
    from sqlalchemy import select

    from findplus.db.models import Device

    return list(session.scalars(select(Device).order_by(Device.name)))


def _resolve_indices(answer: str, devices) -> list[str]:
    """Turn "1,3" into device ids, ignoring anything that is not a listed index."""
    ids = []
    for piece in answer.split(","):
        piece = piece.strip()
        if piece.isdigit() and 1 <= int(piece) <= len(devices):
            ids.append(devices[int(piece) - 1].device_id)
    return ids


def _step_devices(yes: bool) -> None:
    """Step 3. Discovers, lists and tracks; labels and icons stay a dashboard job."""
    if yes:
        click.echo("Tracked nothing. Run `findplus devices --track-all` later.")
        return

    from findplus.ingest import upsert_device
    from findplus.providers.google_findhub.client import FindHubClient
    from findplus.state import track_all, track_devices

    try:
        found = FindHubClient().list_devices()
    except Exception as exc:
        click.secho(f"Could not list devices: {exc}", fg="red")
        return

    with session_scope() as session:
        for device in found:
            upsert_device(session, device.device_id, device.name)

    with session_scope() as session:
        devices = _listed_devices(session)
        if not devices:
            click.echo("No devices found on this account.")
            return
        for index, device in enumerate(devices, start=1):
            click.echo(f"  {index}. {device.name} ({device.device_id})")

        answer = click.prompt("Devices to track (comma-separated indices, or 'all')", default="all")
        if answer.strip().lower() == "all":
            tracked = track_all(session)
            click.secho(f"Now tracking all {len(tracked)} device(s).", fg="green")
        else:
            ids = _resolve_indices(answer, devices)
            if ids:
                tracked = track_devices(session, ids, exclusive=True)
                click.secho(f"Now tracking {len(tracked)} device(s).", fg="green")
            else:
                click.echo("Nothing selected; tracking nothing for now.")

    click.echo("Set labels, icons and colours later from the dashboard.")


def _step_groups(yes: bool) -> None:
    """Step 4. Calls the same create_group the groups CLI does."""
    if yes or not click.confirm("Create a group now?", default=False):
        return

    from findplus.groups.repo import create_group

    name = click.prompt("Group name")
    answer = click.prompt("Member device indices (comma-separated)", default="")
    with session_scope() as session:
        ids = _resolve_indices(answer, _listed_devices(session))
        try:
            create_group(session, name=name, member_ids=ids)
        except ValueError as exc:
            click.secho(f"Error: {exc}", fg="red")
            return
    click.secho(f"Created group '{name}' with {len(ids)} member(s).", fg="green")


def _step_places(yes: bool) -> None:
    """Step 5. Always a pointer: there is no terminal geofence UI to offer."""
    click.echo("Add places from the dashboard.")


def _step_notifications(yes: bool) -> None:
    """Step 6. Telegram only, through the same telegram_setup the alerts CLI calls."""
    if yes or not click.confirm("Connect Telegram now?", default=False):
        click.echo("Configure WhatsApp, webhook or native notifications from the dashboard.")
        return

    from findplus.alerts.channels.telegram import telegram_setup

    token = click.prompt("Telegram bot token", hide_input=True)
    click.echo("Waiting up to 120 s for a message from Telegram...")
    try:
        result = telegram_setup(token, wait_seconds=120, poll=2)
    except (RuntimeError, TimeoutError) as exc:
        click.secho(str(exc), fg="red")
        return
    click.echo(
        f"\nConnected: chat '{result['chat_title']}' "
        f"({result['chat_type']}, id={result['chat_id']})"
    )


def _step_applock(yes: bool) -> None:
    """Step 7. Reuses hash_pin/save_pin, the same pair the settings route uses."""
    if yes or not click.confirm("Set an app-lock PIN now?", default=False):
        return

    from findplus.appsettings import save_pin
    from findplus.security import hash_pin

    pin = click.prompt("New PIN", hide_input=True, confirmation_prompt=True)
    try:
        salt, digest = hash_pin(pin)
    except ValueError as exc:
        click.secho(str(exc), fg="red")
        return
    with session_scope() as session:
        save_pin(session, salt, digest)
    click.secho("App lock is on. Locking does not encrypt the database.", fg="green")
