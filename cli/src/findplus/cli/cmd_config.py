"""`findplus config` command group: get/set/unset/list/path persistent settings.

Purpose    : Let users and automation persist Settings values across
             invocations without hand-editing files or remembering env
             var names.
Inputs     : KEY (and VALUE for set) arguments.
Outputs    : Reads/writes ~/.findplus/config.env (0600); console output.
Constraints: Validation and the config.env rewrite live in config_keys.py, so
             this group and PATCH /api/settings enforce one set of rules
             (specs/service-and-settings.md § 6).
"""

from __future__ import annotations

import click

from findplus.config import get_settings, validate_config_key, write_config_key


@click.group("config")
def config_cmd() -> None:
    """Get, set or inspect persistent settings in ~/.findplus/config.env."""


@config_cmd.command("get")
@click.argument("key")
def config_get(key: str) -> None:
    """Print the value of KEY from config.env, or empty if unset."""
    env_file = get_settings().state_dir / "config.env"
    for line in env_file.read_text().splitlines() if env_file.exists() else []:
        k, _, v = line.partition("=")
        if k.strip().upper() == key.upper():
            click.echo(v.strip())
            return
    click.echo("")


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Write KEY=VALUE to config.env after validating through Settings."""
    try:
        validate_config_key(key, value)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    write_config_key(get_settings(), key, value)


@config_cmd.command("unset")
@click.argument("key")
def config_unset(key: str) -> None:
    """Remove KEY from config.env."""
    write_config_key(get_settings(), key, None)


@config_cmd.command("list")
def config_list() -> None:
    """Print all KEY=VALUE pairs in config.env."""
    env_file = get_settings().state_dir / "config.env"
    if env_file.exists():
        click.echo(env_file.read_text().rstrip())


@config_cmd.command("path")
def config_path() -> None:
    """Print the path to config.env."""
    click.echo(str(get_settings().state_dir / "config.env"))
