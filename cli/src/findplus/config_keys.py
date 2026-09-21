"""Validation and persistence for the keys config.env holds.

Purpose    : One implementation of "is this setting legal" and "write it to
             config.env", so `findplus config set` and PATCH /api/settings
             cannot drift apart (specs/service-and-settings.md § 4, § 6).
             Split out of config.py so that file stays under the 300-line cap
             (PRI rule 7), the same way config_bind.py was; config.py
             re-exports both names, so `from findplus.config import
             validate_config_key` works.
Inputs     : A key (with or without the FINDPLUS_ prefix, any case) and its
             string value; a Settings for the state directory.
Outputs    : validate_config_key raises ValueError; write_config_key rewrites
             ~/.findplus/config.env at 0600.
Constraints: validate_config_key raises ValueError and nothing else, so the CLI
             can turn it into a ClickException and the API into a 422. No import
             from findplus.config at module level -- that would be circular.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from findplus.config_bind import is_public_bind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from findplus.config import Settings


def validate_config_key(key: str, value: str) -> None:
    """Raise ValueError if `value` is not a legal setting for `key`.

    The poll-interval range is the API's 5-1440 on both surfaces: § 6 pins one
    rule with no carve-out, so FINDPLUS_ALLOW_FAST_POLLING no longer loosens it
    here. It still applies to a value set directly in the environment or in
    .env, through Settings.effective_poll_interval_minutes.
    """
    key_lower = key.lower().removeprefix("findplus_")
    if key_lower == "host" and is_public_bind(value):
        raise ValueError(
            f"Non-loopback host '{value}' rejected. Set FINDPLUS_ALLOW_PUBLIC_BIND=1 to allow."
        )
    if key_lower == "poll_interval_minutes":
        minutes = float(value)
        if not (5 <= minutes <= 1440):
            raise ValueError("poll.interval_minutes must be between 5 and 1440.")
    if key_lower == "retention_days":
        days = int(value)
        if days != 0 and days < 7:
            raise ValueError("history.retention_days must be null (keep forever) or at least 7.")


def write_config_key(settings: Settings, key: str, value: str | None) -> None:
    """Set or remove KEY in config.env, keeping every other key intact."""
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


def unprefixed_config_env(state_dir: Path, model_fields: dict) -> dict[str, str]:
    """Read the bare (unprefixed) keys out of state_dir/config.env.

    Purpose    : specs/data-model.md § state dir says config.env keys are Settings
                 field names upper-cased with the FINDPLUS_ prefix OPTIONAL — both
                 forms accepted. pydantic-settings applies env_prefix to dotenv files
                 as well as to the environment, so the unprefixed form would otherwise
                 be silently dropped and `findplus config set LOG_LEVEL DEBUG` would
                 write a line that never reaches Settings.
    Inputs     : the resolved state dir; Settings.model_fields, passed in by the
                 caller so this module never imports findplus.config at runtime
                 (config_keys is imported BY config.py).
    Outputs    : {field_name: raw string value} for unprefixed keys only; prefixed keys
                 are left to the normal dotenv source.
    Constraints: a real FINDPLUS_* environment variable always wins, so a key already
                 present in os.environ is skipped. Moved here from config.py at the
                 E6/E11-CF-P2-14 file-cap split; config.py re-exports the name.
    """
    path = state_dir / "config.env"
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        name = key.strip().upper()
        if name.startswith("FINDPLUS_"):
            continue  # handled by the dotenv source
        field = name.lower()
        if field in model_fields and f"FINDPLUS_{name}" not in os.environ:
            values[field] = value.strip().strip("'\"")
    values.pop("state_dir", None)  # already resolved by the caller
    return values
