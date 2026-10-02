"""The `people.digest` preference: the evening summary's switch, time and people.

Purpose    : One place that reads, validates and saves the daily-summary
             preference, so GET/PATCH /api/settings, `findplus people digest`
             and the DigestScheduler cannot disagree (spec § 7.2).
Inputs     : An open Session; a partial dict (only the keys being changed).
Outputs    : The full preference dict:
             {"enabled": false, "time": "20:00", "people": [], "channel": "auto",
              "always_send": false}. `people` empty means every person and pet.
Constraints: Stored as JSON in the settings table under `people.digest`. Off by
             default: nothing is ever sent until the owner switches it on. A bad
             value raises ValueError naming it; nothing is written then.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Group
from findplus.db.models_people import PERSON_KINDS
from findplus.state import get_setting, set_setting

KEY = "people.digest"
CHANNELS = ("auto", "telegram")
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "time": "20:00",
    "people": [],
    "channel": "auto",
    "always_send": False,
}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"people.digest.{name} must be true or false")
    return value


def _people(session: Session, value: Any) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in value
    ):
        raise ValueError("people.digest.people must be a list of person ids")
    known = set(session.scalars(select(Group.id).where(Group.kind.in_(PERSON_KINDS))).all())
    missing = [i for i in value if i not in known]
    if missing:
        raise ValueError(f"people.digest.people: person {missing[0]} not found")
    return sorted(set(value))


def validate(session: Session, patch: dict[str, Any]) -> dict[str, Any]:
    """The checked, normalised form of a partial preference. Raises ValueError."""
    unknown = sorted(set(patch) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"unknown people.digest key {unknown[0]!r}")
    out: dict[str, Any] = {}
    for name, value in patch.items():
        if name in ("enabled", "always_send"):
            out[name] = _bool(name, value)
        elif name == "time":
            if not isinstance(value, str) or not _TIME.match(value):
                raise ValueError("people.digest.time must be HH:MM, 24-hour (for example 20:00)")
            out[name] = value
        elif name == "channel":
            if value not in CHANNELS:
                raise ValueError(f"people.digest.channel must be one of {', '.join(CHANNELS)}")
            out[name] = value
        else:
            out[name] = _people(session, value)
    return out


def load(session: Session) -> dict[str, Any]:
    """The stored preference merged over the defaults; a damaged value reads as the default."""
    raw = get_setting(session, KEY)
    try:
        stored = json.loads(raw) if raw else {}
    except ValueError:
        stored = {}
    merged = {**DEFAULTS, "people": []}
    if isinstance(stored, dict):
        merged.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return merged


def save(session: Session, patch: dict[str, Any]) -> dict[str, Any]:
    """Validate then merge `patch` into the stored preference; returns the result."""
    checked = validate(session, patch)
    merged = {**load(session), **checked}
    set_setting(session, KEY, json.dumps(merged, sort_keys=True))
    return merged


def hour_minute(prefs: dict[str, Any]) -> tuple[int, int]:
    hour, minute = prefs["time"].split(":")
    return int(hour), int(minute)
