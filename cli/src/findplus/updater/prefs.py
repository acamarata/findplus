"""The `updates.auto` preference: check, download and install updates by themselves.

Purpose    : One switch in Settings. On (the default): Find+ checks GitHub every
             few hours, downloads a new version and installs it when the app is
             not in use. Off: no update request is made unless the owner presses
             Check now or Update now.
Inputs     : A database session.
Outputs    : bool; a settings-table row "updates.auto" of "1" or "0".
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from findplus.state import get_setting, set_setting

KEY = "updates.auto"


def auto_enabled(session: Session) -> bool:
    return get_setting(session, KEY, "1") != "0"


def set_auto(session: Session, value: object) -> None:
    """Store the switch. Raises ValueError on anything but true or false."""
    if not isinstance(value, bool):
        raise ValueError("updates.auto must be true or false.")
    set_setting(session, KEY, "1" if value else "0")
