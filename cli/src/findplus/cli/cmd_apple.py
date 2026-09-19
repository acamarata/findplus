"""`findplus apple` command group: register/list/remove Apple Find My accessories.

Purpose    : Let a user register the accessories (AirTags, DIY tags) whose
             private keys they hold, so the Apple provider can locate them.
Inputs     : NAME plus one of --plist PATH or --private-key B64; a device ID.
Outputs    : Console confirmation; JSON accessory records on disk.
Constraints: Every subcommand checks is_available() first and exits 1 with
             the install hint when the `apple` extra is not installed.
"""

from __future__ import annotations

import pathlib

import click

from findplus.config import get_settings
from findplus.providers.apple_findmy import is_available
from findplus.providers.apple_findmy.accessories import (
    add_accessory,
    list_accessories,
    remove_accessory,
)

from ._fmt import _prep


def _require_available() -> None:
    avail, hint = is_available()
    if not avail:
        click.echo(f"Apple provider not installed. {hint}", err=True)
        raise SystemExit(1)


@click.group(name="apple")
def apple_group() -> None:
    """Manage Apple Find My accessories (requires findplus[apple])."""


@apple_group.command(name="add-accessory")
@click.argument("name")
@click.option(
    "--plist", "plist_path", type=click.Path(exists=True, path_type=pathlib.Path), default=None
)
@click.option("--private-key", "private_key_b64", default=None)
def add_accessory_cmd(
    name: str, plist_path: pathlib.Path | None, private_key_b64: str | None
) -> None:
    """Register an accessory from a pairing --plist export or a --private-key."""
    _prep()
    _require_available()
    if (plist_path is None) == (private_key_b64 is None):
        click.echo("provide exactly one of --plist or --private-key", err=True)
        raise SystemExit(1)
    settings = get_settings()
    try:
        record = add_accessory(
            name, settings, plist_path=plist_path, private_key_b64=private_key_b64
        )
    except ValueError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    click.echo(f"Accessory '{name}' registered as {record['device_id']}")


@apple_group.command(name="list")
def list_cmd() -> None:
    """List every registered accessory."""
    _prep()
    _require_available()
    settings = get_settings()
    records = list_accessories(settings)
    if not records:
        click.echo("No accessories registered.")
        return
    click.echo(f"{'Name':<24} {'Device ID':<34} {'Kind':<12} Added")
    for r in records:
        click.echo(f"{r['name']:<24} {r['device_id']:<34} {r['kind']:<12} {r['added_at']}")


@apple_group.command(name="remove")
@click.argument("device_id")
@click.option("--yes", is_flag=True, required=True, help="Confirm removal.")
def remove_cmd(device_id: str, yes: bool) -> None:
    """Remove a registered accessory by its device ID."""
    _prep()
    _require_available()
    settings = get_settings()
    try:
        remove_accessory(device_id, settings)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    click.echo(f"Removed {device_id}.")
