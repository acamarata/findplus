"""The backup keys of GET/PATCH /api/settings.

Purpose    : Expose where backups go and how many are kept, through the same
             settings body the dashboard and `findplus config` already use.
Inputs     : The PATCH body's raw dict (presence of a key is the signal, so an
             explicit null means "back to the default"), and Settings.
Outputs    : The three wire keys for the GET body; writes to config.env.
Constraints: Validation reuses `validate_config_key`, so the CLI
             (`findplus config set backup_keep_daily 10`) and this API cannot
             disagree. Everything is checked before anything is written, and a
             bad value raises ValueError (the route turns it into a 422).
"""

from __future__ import annotations

from typing import Any

from findplus.config import Settings, get_settings, validate_config_key, write_config_key

#: wire key -> config.env key
_KEYS = {
    "backup.directory": "BACKUP_DIR",
    "backup.keep_daily": "BACKUP_KEEP_DAILY",
    "backup.keep_weekly": "BACKUP_KEEP_WEEKLY",
}


def backup_fields(settings: Settings) -> dict[str, Any]:
    """The three wire keys; `backup.directory` is the directory in force."""
    return {
        "backup.directory": str(settings.effective_backup_dir),
        "backup.keep_daily": settings.backup_keep_daily,
        "backup.keep_weekly": settings.backup_keep_weekly,
    }


def write_backup_fields(raw_body: dict[str, Any]) -> None:
    """Validate then persist whichever backup keys the PATCH named."""
    named = {k: raw_body[k] for k in _KEYS if k in raw_body}
    for key, value in named.items():
        if value is not None:
            validate_config_key(_KEYS[key], str(value))
        elif key != "backup.directory":
            raise ValueError(f"{key} cannot be null; send a number.")
    settings = get_settings()
    for key, value in named.items():
        write_config_key(settings, _KEYS[key], None if value is None else str(value))
