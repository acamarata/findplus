"""The `updates.*` keys of GET/PATCH /api/settings.

Purpose    : Expose the automatic-update switch and the developer build folder
             through the same settings body the dashboard and CLI use.
Inputs     : The PATCH body's raw dict (a key's presence is the signal).
Outputs    : {"updates.auto": bool, "updates.dev_dir": str | None}; settings rows.
Constraints: Both values are checked before either is written; a bad value
             raises ValueError, which the route turns into a 422. FINDPLUS_UPDATE_DEV_DIR,
             when set, wins over the stored folder at run time (devsource.py).
"""

from __future__ import annotations

from typing import Any

from findplus.state import get_setting
from findplus.updater import devsource, prefs


def update_fields(session) -> dict[str, Any]:
    return {
        prefs.KEY: prefs.auto_enabled(session),
        devsource.KEY: get_setting(session, devsource.KEY),
    }


def write_update_fields(session, raw_body: dict[str, Any]) -> None:
    """Persist whichever `updates.*` keys the PATCH named."""
    auto, dev = prefs.KEY in raw_body, devsource.KEY in raw_body
    if auto and not isinstance(raw_body[prefs.KEY], bool):
        raise ValueError("updates.auto must be true or false.")
    if dev:
        value = raw_body[devsource.KEY]
        if value not in (None, "") and not isinstance(value, str):
            raise ValueError("updates.dev_dir must be a full path, or null to turn it off.")
        devsource.set_dev_dir(session, value)
    if auto:
        prefs.set_auto(session, raw_body[prefs.KEY])
