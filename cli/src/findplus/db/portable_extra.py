"""The extra record kinds of the JSONL export: settings, deliveries, digest runs.

Purpose    : Carry the state that stops Find+ repeating itself after an import:
             alert deliveries (so cooldowns hold) and digest runs (so a daily
             summary is never sent twice), plus the app settings the owner chose.
Inputs     : An open session (export), or one record at a time (import).
Outputs    : JSON lines `{"t": "setting"|"alert_delivery"|"digest_run", ...}`.
Constraints: Settings starting `lock_` (the PIN hash and salt, and the lock
             switch itself, which is useless without them) are never exported.
             Deliveries name their rule by the rule's `ref` (its old id, written
             on the rule line) and digest runs name their person by group name,
             because ids are not portable. Events are NOT exported: they are
             rebuilt by `findplus db rebuild-derived`, which stamps them as
             already notified so nothing re-sends.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findplus.db.models import Group, Setting
from findplus.db.models_alerts import AlertDelivery
from findplus.db.models_people import DigestRun

#: Never exported: the app lock (PIN hash, salt, switch).
PRIVATE_PREFIX = "lock_"
EXTRA_KINDS = ("setting", "alert_delivery", "digest_run")
EXTRA_SKIP = {
    "setting": set(),
    "alert_delivery": {"id", "rule_id"},
    "digest_run": {"id", "group_id"},
}
MODELS = {"setting": Setting, "alert_delivery": AlertDelivery, "digest_run": DigestRun}


def _line(kind: str, data: dict[str, Any]) -> str:
    return json.dumps({"t": kind, **data}, ensure_ascii=False)


def extra_counts(session: Session) -> dict[str, int]:
    """Counts of the extra kinds, left out when zero so older readers see no change."""
    out = {k: session.scalar(select(func.count()).select_from(m)) or 0 for k, m in MODELS.items()}
    out["setting"] = (
        session.scalar(
            select(func.count()).select_from(Setting).where(~Setting.key.startswith(PRIVATE_PREFIX))
        )
        or 0
    )
    return {k: n for k, n in out.items() if n}


def export_settings(session: Session, row_dict) -> Iterator[str]:
    stmt = select(Setting).where(~Setting.key.startswith(PRIVATE_PREFIX)).order_by(Setting.key)
    for s in session.scalars(stmt):
        yield _line("setting", row_dict(s, EXTRA_SKIP["setting"]))


def export_deliveries(session: Session, row_dict) -> Iterator[str]:
    for d in session.scalars(select(AlertDelivery).order_by(AlertDelivery.id)):
        yield _line(
            "alert_delivery", {**row_dict(d, EXTRA_SKIP["alert_delivery"]), "rule_ref": d.rule_id}
        )


def export_digest_runs(session: Session, row_dict) -> Iterator[str]:
    names = {g.id: g.name for g in session.scalars(select(Group))}
    for r in session.scalars(select(DigestRun).order_by(DigestRun.id)):
        extra = {"group": names[r.group_id]}
        yield _line("digest_run", {**row_dict(r, EXTRA_SKIP["digest_run"]), **extra})


def add_extra(session: Session, kind: str, rec: dict[str, Any], names: dict) -> None:
    """Write one setting, delivery or digest run; raises the importer's error on a dangling name."""
    from datetime import datetime

    from findplus.db.portable_import import PortableImportError, _clean

    model = MODELS[kind]
    data = _clean(model, rec, EXTRA_SKIP[kind])
    if kind == "alert_delivery":
        rule = names["rule"].get(rec.get("rule_ref"))
        if rule is None:
            raise PortableImportError("An alert delivery points at a rule that is not in the file.")
        data["rule_id"] = rule
    elif kind == "digest_run":
        group = names["group"].get(rec.get("group"))
        if group is None:
            raise PortableImportError("A digest record points at a person that is not in the file.")
        data["group_id"] = group
    elif kind == "setting":
        if str(data.get("key", "")).startswith(PRIVATE_PREFIX):
            return  # never import a lock PIN from a file
        existing = session.get(Setting, data["key"])
        if existing is not None:  # a default the migrations seeded: the file wins
            existing.value = data.get("value")
            existing.updated_at = data.get("updated_at") or datetime.now().astimezone()
            return
    session.add(model(**data))
