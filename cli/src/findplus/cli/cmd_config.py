"""`findplus config` command group: get/set/unset/list/path persistent settings.

Purpose    : Let users and automation persist Settings values across
             invocations without hand-editing files or remembering env
             var names.
Inputs     : KEY (and VALUE for set) arguments.
Outputs    : Reads/writes ~/.findplus/config.env (0600); console output.
Constraints: Only host and poll_interval_minutes are validated here — the
             same guardrails Settings itself enforces (loopback-only bind,
             5-minute poll floor).
"""

from __future__ import annotations

import os

import click

from findplus.config import Settings, get_settings

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


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
    _validate_setting(key, value)
    _write_env_key(get_settings(), key, value)


@config_cmd.command("unset")
@click.argument("key")
def config_unset(key: str) -> None:
    """Remove KEY from config.env."""
    _write_env_key(get_settings(), key, None)


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


def _validate_setting(key: str, value: str) -> None:
    key_lower = key.lower()
    if (
        key_lower in ("host", "findplus_host")
        and value not in _LOOPBACK
        and not os.environ.get("FINDPLUS_ALLOW_PUBLIC_BIND")
    ):
        raise click.ClickException(
            f"Non-loopback host '{value}' rejected. Set FINDPLUS_ALLOW_PUBLIC_BIND=1 to allow."
        )
    if (
        key_lower in ("poll_interval_minutes", "findplus_poll_interval_minutes")
        and float(value) < 5.0
        and not get_settings().allow_fast_polling
    ):
        raise click.ClickException(
            "poll_interval_minutes < 5 rejected. Set FINDPLUS_ALLOW_FAST_POLLING=true to allow."
        )


def _write_env_key(settings: Settings, key: str, value: str | None) -> None:
    env_file = settings.state_dir / "config.env"
    settings.ensure_state_dir()
    existing: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                existing[k.strip().upper()] = v.strip()
    if value is None:
        existing.pop(key.upper(), None)
    else:
        existing[key.upper()] = value
    env_file.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
    env_file.chmod(0o600)
