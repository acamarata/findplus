"""Import a `findplus export --format jsonl` file into an empty database.

Purpose    : The way back in: rebuild devices, places, groups, observations and
             alert rules from the JSONL export (see `portable.py`).
Inputs     : An open session on a migrated database, and the file's lines.
Outputs    : `ImportResult` with the counts written.
Constraints: Only into an EMPTY database: it never merges with or overwrites
             existing data. The whole import is one transaction, so a bad line
             leaves nothing behind. A file made by a newer export format, or by a
             schema newer than this Find+, is refused. Unknown fields are
             ignored and missing ones take the column default, so older exports
             keep loading. Derived data is not in the file; run
             `findplus db recompute-quality` afterwards.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from findplus.db.models import Device, DeviceGroup, Group, LocationObservation, Place
from findplus.db.models_alerts import AlertRule
from findplus.db.portable import FORMAT, FORMAT_VERSION, SKIP
from findplus.db.types import UtcDateTime

_MODELS = {
    "device": Device,
    "place": Place,
    "group": Group,
    "observation": LocationObservation,
    "alert_rule": AlertRule,
}
_BATCH = 2000


class PortableImportError(ValueError):
    """The file cannot be imported. The message is plain words; nothing was written."""


@dataclass(slots=True)
class ImportResult:
    counts: dict[str, int] = field(default_factory=dict)


def _clean(model: type, data: dict[str, Any], skip: set[str]) -> dict[str, Any]:
    """The columns of `model` present in `data`, with ISO strings turned back into datetimes."""
    out: dict[str, Any] = {}
    for col in inspect(model).column_attrs:
        if col.key in skip or col.key not in data:
            continue
        value = data[col.key]
        if isinstance(value, str) and isinstance(col.columns[0].type, UtcDateTime):
            value = datetime.fromisoformat(value)
        out[col.key] = value
    return out


def _check_header(rec: dict[str, Any]) -> None:
    from findplus.db.migrate import head_revision

    if rec.get("format") != FORMAT:
        raise PortableImportError("This is not a Find+ export file.")
    if int(rec.get("version", 0)) > FORMAT_VERSION:
        raise PortableImportError("This export was made by a newer Find+. Update Find+ first.")
    exported = rec.get("schema_revision")
    if exported and exported > (head_revision() or ""):
        raise PortableImportError("This export has a newer schema than this Find+. Update first.")


def is_empty(session: Session) -> bool:
    """True when the database holds no devices, places, groups, observations or rules."""
    return all(not session.scalar(select(func.count()).select_from(m)) for m in _MODELS.values())


def _records(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    for n, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PortableImportError(f"Line {n} is not valid JSON: {exc.msg}.") from exc


def _add_group(session: Session, rec: dict[str, Any], names: dict[str, dict[str, int]]) -> None:
    group = Group(**_clean(Group, rec, SKIP["group"]))
    session.add(group)
    session.flush()
    names["group"][group.name] = group.id
    for device_id in rec.get("members", []):
        session.add(DeviceGroup(device_id=device_id, group_id=group.id))
    session.flush()


def _add_rule(session: Session, rec: dict[str, Any], names: dict[str, dict[str, int]]) -> None:
    data = _clean(AlertRule, rec, SKIP["alert_rule"])
    try:
        data["place_id"] = names["place"][rec["place"]] if rec.get("place") else None
        data["group_id"] = names["group"][rec["group"]] if rec.get("group") else None
    except KeyError as exc:
        raise PortableImportError(
            f"An alert rule points at {exc.args[0]!r}, which is not in the file."
        ) from exc
    session.add(AlertRule(**data))


def _flush_observations(session: Session, batch: list[dict[str, Any]]) -> None:
    if batch:
        session.bulk_insert_mappings(LocationObservation, batch)
        batch.clear()


def import_lines(session: Session, lines: Iterable[str]) -> ImportResult:
    """Load the export into an empty database (caller commits, or rolls back on error)."""
    if not is_empty(session):
        raise PortableImportError(
            "This database already has data. Import only into an empty one "
            "(use a fresh state directory)."
        )
    result = ImportResult({k: 0 for k in _MODELS})
    names: dict[str, dict[str, int]] = {"place": {}, "group": {}}
    batch: list[dict[str, Any]] = []
    first = True
    for rec in _records(lines):
        kind = rec.pop("t", None)
        if first:
            if kind != "header":
                raise PortableImportError("The file does not start with an export header.")
            _check_header(rec)
            first = False
            continue
        if kind == "observation":
            batch.append(_clean(LocationObservation, rec, SKIP["observation"]))
            result.counts[kind] += 1
            if len(batch) >= _BATCH:
                _flush_observations(session, batch)
            continue
        _flush_observations(session, batch)
        _add_other(session, kind, rec, names)
        result.counts[kind] += 1
    _flush_observations(session, batch)
    if first:
        raise PortableImportError("The file is empty.")
    session.flush()
    return result


def _add_other(session: Session, kind: str | None, rec: dict, names: dict) -> None:
    if kind == "group":
        _add_group(session, rec, names)
    elif kind == "alert_rule":
        _add_rule(session, rec, names)
    elif kind in ("device", "place"):
        obj = _MODELS[kind](**_clean(_MODELS[kind], rec, SKIP[kind]))
        session.add(obj)
        session.flush()
        if kind == "place":
            names["place"][obj.name] = obj.id
    else:
        raise PortableImportError(f"Unknown record type {kind!r} in the file.")
