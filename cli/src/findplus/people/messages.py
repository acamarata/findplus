"""People sentences, read from the dashboard's own catalog (web/locales/en.json `people.*`).

Purpose : One wording for every person sentence, whichever surface shows it:
          alerts (alerts/render_person.py), the API, the CLI and MCP. The
          strings live in en.json so the dashboard and the server never drift.
Inputs  : A dotted key under `people` plus `{name}` placeholder values.
Outputs : Plain sentences; small formatters for times, ages and distances.
Constraints: Never invents a place: an unnamed spot is called one. Times go
          through dispatch_core._fmt_local_time, the delivery log's own format.
          The catalog ships inside the wheel (hatch_build.py copies web/), so a
          missing file is a packaging bug and raises.
"""

from __future__ import annotations

import datetime
import functools
import json
from pathlib import Path

from findplus.config import PROJECT_ROOT


def _catalog_path() -> Path:
    packaged = Path(__file__).parent.parent / "web" / "static" / "locales" / "en.json"
    return packaged if packaged.exists() else PROJECT_ROOT.parent / "web" / "locales" / "en.json"


@functools.cache
def _people_catalog() -> dict:
    return json.loads(_catalog_path().read_text(encoding="utf-8"))["people"]


def t(key: str, **values: object) -> str:
    """The `people.<key>` string with `{name}` placeholders filled, like i18n.js's t()."""
    node: object = _people_catalog()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"people.{key} is missing from web/locales/en.json")
        node = node[part]
    text = str(node)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def role_word(role: str | None) -> str:
    """'shoes', 'bag'; 'tracker' when the role is unknown."""
    return t(f"role.{role or 'other'}")


def fmt_time(value: datetime.datetime) -> str:
    """ "Sep 26, 4:12 PM EDT" in the machine's zone, the delivery log's format."""
    from findplus.alerts import dispatch_core

    aware = dispatch_core.as_utc(value)
    return dispatch_core._fmt_local_time(aware.astimezone(dispatch_core.local_zone()))


def fmt_age(minutes: int) -> str:
    """ "12 min" or "2 h 5 min"."""
    minutes = max(0, int(minutes))
    if minutes < 60:
        return t("now.ageMinutes", minutes=minutes)
    return t("now.ageHours", hours=minutes // 60, minutes=minutes % 60)


def fmt_distance(meters: float) -> str:
    """ "850 m" or "1.2 km". Always a straight line, never a road distance."""
    if meters < 1000:
        return t("now.m", m=int(round(meters, -1)))
    return t("now.km", km=f"{meters / 1000:.1f}")


def join_words(words: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + f" and {words[-1]}"


def short_labels(members: list[tuple[str, str | None, str]], owner: str | None = None) -> dict:
    """device_id -> 'shoes' when the role is unique in the person, else the tracker name.

    `members` is (device_id, role, display_name). "Sam Shoes Red" and "Sam
    Shoes White" are both shoes, so they keep their names, minus a leading
    owner name when `owner` is given ("Shoes Red"): the sentence must still
    say which tracker it rests on (spec Q1).
    """
    roles = [role for _, role, _ in members if role]
    prefix = f"{owner.casefold()} " if owner else None
    out: dict[str, str] = {}
    for device_id, role, name in members:
        if role and roles.count(role) == 1:
            out[device_id] = role_word(role)
        elif prefix and name.casefold().startswith(prefix) and len(name) > len(prefix):
            out[device_id] = name[len(prefix) :]
        else:
            out[device_id] = name
    return out
