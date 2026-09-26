"""User-facing application preferences, persisted in the `settings` table.

Purpose : Theme, app-lock configuration and idle timeout — things the user
          changes from the Settings dialog rather than from `.env`.
Constraints:
    - `pin_hash` / `pin_salt` live here but are NEVER returned by any endpoint.
      `AppSettings.public()` is the only shape the API is allowed to serialise.
    - `.env` holds deployment configuration; this holds user preferences. They
      are separate on purpose so editing one never clobbers the other.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from findplus.state import get_setting, set_setting

THEME = "ui_theme"
LOCK_ENABLED = "lock_enabled"
PIN_HASH = "lock_pin_hash"
PIN_SALT = "lock_pin_salt"
IDLE_TIMEOUT = "lock_idle_minutes"

VALID_THEMES = ("dark", "light", "system")
#: UAT6-N20: an unset theme used to read as "dark" no matter the OS. New
#: installs now follow the OS instead; an explicit choice (dark, light or a
#: prior "system") is a stored row and is never touched by this default.
DEFAULT_THEME = "system"
DEFAULT_IDLE_MINUTES = 15
MAX_IDLE_MINUTES = 24 * 60


@dataclass(frozen=True, slots=True)
class AppSettings:
    theme: str = DEFAULT_THEME
    lock_enabled: bool = False
    pin_hash: str | None = None
    pin_salt: str | None = None
    idle_minutes: int = DEFAULT_IDLE_MINUTES

    @property
    def pin_configured(self) -> bool:
        return bool(self.pin_hash and self.pin_salt)

    @property
    def lock_active(self) -> bool:
        """The lock only applies when it is both enabled and actually set up."""
        return self.lock_enabled and self.pin_configured

    def public(self) -> dict[str, object]:
        """Safe-to-serialise view. Never includes the hash or salt."""
        return {
            "theme": self.theme,
            "lock_enabled": self.lock_enabled,
            "pin_configured": self.pin_configured,
            "lock_active": self.lock_active,
            "idle_minutes": self.idle_minutes,
        }


def load_settings(session: Session) -> AppSettings:
    theme = get_setting(session, THEME, DEFAULT_THEME) or DEFAULT_THEME
    if theme not in VALID_THEMES:
        theme = DEFAULT_THEME
    try:
        idle = int(get_setting(session, IDLE_TIMEOUT, str(DEFAULT_IDLE_MINUTES)) or 0)
    except ValueError:
        idle = DEFAULT_IDLE_MINUTES
    return AppSettings(
        theme=theme,
        lock_enabled=(get_setting(session, LOCK_ENABLED, "0") == "1"),
        pin_hash=get_setting(session, PIN_HASH),
        pin_salt=get_setting(session, PIN_SALT),
        idle_minutes=max(0, min(MAX_IDLE_MINUTES, idle)),
    )


def save_theme(session: Session, theme: str) -> None:
    if theme not in VALID_THEMES:
        raise ValueError(f"Unknown theme {theme!r}. Choose one of {VALID_THEMES}.")
    set_setting(session, THEME, theme)


def save_idle_minutes(session: Session, minutes: int) -> None:
    """0 disables idle auto-locking; the app then locks only on restart or manually."""
    if minutes < 0 or minutes > MAX_IDLE_MINUTES:
        raise ValueError(f"Idle timeout must be between 0 and {MAX_IDLE_MINUTES} minutes.")
    set_setting(session, IDLE_TIMEOUT, str(int(minutes)))


def save_pin(session: Session, pin_salt: str, pin_hash: str) -> None:
    set_setting(session, PIN_SALT, pin_salt)
    set_setting(session, PIN_HASH, pin_hash)
    set_setting(session, LOCK_ENABLED, "1")


def clear_pin(session: Session) -> None:
    """Remove the PIN entirely and disable the lock."""
    set_setting(session, PIN_SALT, None)
    set_setting(session, PIN_HASH, None)
    set_setting(session, LOCK_ENABLED, "0")


def set_lock_enabled(session: Session, enabled: bool) -> None:
    set_setting(session, LOCK_ENABLED, "1" if enabled else "0")
