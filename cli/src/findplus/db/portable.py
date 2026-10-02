"""Full-fidelity JSONL export of everything the owner built (the escape hatch).

Purpose    : `findplus export --format jsonl`: devices, observations, places,
             groups (with kinds and members) and alert rules in one human-readable
             file, one JSON object per line, so the data can leave the app and
             come back (`findplus import`) without loss.
Inputs     : An open session.
Outputs    : An iterator of JSON lines. Line 1 is a header (format version, app
             version, schema revision, counts); every other line is
             `{"t": <kind>, ...fields}` in dependency order: setting, device,
             place, group, digest_run, observation, alert_rule, alert_delivery.
Constraints: Columns come from the ORM mapper, so a new column is exported
             without code changes here. Alert rules refer to places and groups by
             NAME (ids are not portable). No sign-in tokens or keys:
             `secrets.json`, `alerts.json` and Apple tokens are never read, and
             the app lock (settings starting `lock_`: PIN hash and salt) is left
             out. Settings, alert deliveries and digest runs are exported
             (portable_extra.py) so cooldowns and daily summaries do not repeat
             after an import. Derived data (quality flags, events, place and
             person states) is left out: `findplus db rebuild-derived`
             recomputes it. Datetimes are ISO-8601 UTC.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from findplus import __version__
from findplus.db.models import (
    Device,
    DeviceGroup,
    Group,
    LocationObservation,
    Place,
)
from findplus.db.models_alerts import AlertRule
from findplus.db.portable_extra import (
    export_deliveries,
    export_digest_runs,
    export_settings,
    extra_counts,
)

FORMAT = "findplus-export"
FORMAT_VERSION = 1
#: Columns that are row ids or foreign keys: re-created on import from names.
SKIP = {
    "device": set(),
    "place": {"id"},
    "group": {"id"},
    "observation": {"id"},
    "alert_rule": {"id", "place_id", "group_id"},
}
_BATCH = 2000


def _value(v: Any) -> Any:
    return v.astimezone(UTC).isoformat() if isinstance(v, datetime) else v


def row_dict(obj: Any, skip: set[str]) -> dict[str, Any]:
    """Every mapped column of `obj` except `skip`, JSON-ready."""
    return {
        c.key: _value(getattr(obj, c.key))
        for c in inspect(type(obj)).column_attrs
        if c.key not in skip
    }


def _line(kind: str, data: dict[str, Any]) -> str:
    return json.dumps({"t": kind, **data}, ensure_ascii=False, sort_keys=False)


def _counts(session: Session) -> dict[str, int]:
    from sqlalchemy import func

    models = {
        "device": Device,
        "place": Place,
        "group": Group,
        "observation": LocationObservation,
        "alert_rule": AlertRule,
    }
    core = {k: session.scalar(select(func.count()).select_from(m)) or 0 for k, m in models.items()}
    return {**core, **extra_counts(session)}


def _header(session: Session, now: datetime) -> str:
    from findplus.db.migrate import current_revision

    return json.dumps(
        {
            "t": "header",
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "app_version": __version__,
            "schema_revision": current_revision(),
            "exported_at": now.astimezone(UTC).isoformat(),
            "counts": _counts(session),
        }
    )


def _groups(session: Session) -> Iterator[str]:
    members: dict[int, list[str]] = {}
    for did, gid in session.execute(
        select(DeviceGroup.device_id, DeviceGroup.group_id).order_by(DeviceGroup.device_id)
    ):
        members.setdefault(gid, []).append(did)
    for g in session.scalars(select(Group).order_by(Group.id)):
        yield _line("group", {**row_dict(g, SKIP["group"]), "members": members.get(g.id, [])})


def _rules(session: Session) -> Iterator[str]:
    places = {p.id: p.name for p in session.scalars(select(Place))}
    groups = {g.id: g.name for g in session.scalars(select(Group))}
    for r in session.scalars(select(AlertRule).order_by(AlertRule.id)):
        extra = {"place": places.get(r.place_id), "group": groups.get(r.group_id), "ref": r.id}
        yield _line("alert_rule", {**row_dict(r, SKIP["alert_rule"]), **extra})


def _observations(session: Session) -> Iterator[str]:
    stmt = select(LocationObservation).order_by(LocationObservation.id)
    for obs in session.scalars(stmt.execution_options(yield_per=_BATCH)):
        yield _line("observation", row_dict(obs, SKIP["observation"]))


def export_lines(session: Session, now: datetime | None = None) -> Iterator[str]:
    """The whole export, header first, one JSON object per yielded string."""
    yield _header(session, now or datetime.now(UTC))
    yield from export_settings(session, row_dict)
    for d in session.scalars(select(Device).order_by(Device.device_id)):
        yield _line("device", row_dict(d, SKIP["device"]))
    for p in session.scalars(select(Place).order_by(Place.id)):
        yield _line("place", row_dict(p, SKIP["place"]))
    yield from _groups(session)
    yield from export_digest_runs(session, row_dict)
    yield from _observations(session)
    yield from _rules(session)
    yield from export_deliveries(session, row_dict)
