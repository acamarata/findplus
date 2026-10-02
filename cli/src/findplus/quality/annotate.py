"""Add `suspect` and `suspect_reason` to observation payloads.

Purpose    : One place the API, the timeline and the exports use to say whether a
             sighting looks wrong and why, in plain words.
Inputs     : A session and observation rows, ids or payload dicts.
Outputs    : The same objects with `suspect` (bool) and `suspect_reason` (str or
             None). Only a suspect fix carries a reason; a rescued or merely
             soft-flagged fix does not, so the UI never cries wolf.
Constraints: Read-only. A fix with no stored verdict is not suspect (it has not
             been scored yet, or retention removed the row).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy.orm import Session

from findplus.quality.store import verdicts_for
from findplus.quality.text import reason_text

#: CSV/JSON export columns, in order.
EXPORT_FIELDS = ("suspect", "suspect_reason")


def suspect_fields(session: Session, ids: Sequence[int]) -> dict[int, tuple[bool, str | None]]:
    """observation id -> (suspect, plain-words reason or None) for every id asked about."""
    stored = verdicts_for(session, list(ids))
    out: dict[int, tuple[bool, str | None]] = {}
    for oid in ids:
        suspect, codes = stored.get(oid, (False, ()))
        out[oid] = (suspect, reason_text(codes) if suspect else None)
    return out


def annotate_dicts(session: Session, payloads: Iterable[dict[str, Any]], key: str = "id") -> None:
    """Add the two fields to each dict that has `key` (an observation id)."""
    items = [p for p in payloads if p.get(key) is not None]
    fields = suspect_fields(session, [p[key] for p in items])
    for p in items:
        p["suspect"], p["suspect_reason"] = fields[p[key]]


def annotate_points(session: Session, points: Sequence[Any]) -> None:
    """Set `suspect` / `suspect_reason` on timeline points (objects with an `id`)."""
    fields = suspect_fields(session, [p.id for p in points])
    for p in points:
        p.suspect, p.suspect_reason = fields[p.id]


def attach_to_rows(session: Session, rows: Sequence[Any]) -> None:
    """Set `suspect` / `suspect_reason` as plain attributes on observation rows (for exporters)."""
    fields = suspect_fields(session, [r.id for r in rows])
    for r in rows:
        r.suspect, r.suspect_reason = fields[r.id]


def export_fields(obs: Any) -> dict[str, Any]:
    """The two fields for one exported row; blank/false when the row was never annotated."""
    return {
        "suspect": bool(getattr(obs, "suspect", False)),
        "suspect_reason": getattr(obs, "suspect_reason", None),
    }
