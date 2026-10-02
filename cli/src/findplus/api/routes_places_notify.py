"""Backfill of the default arrival/departure rule for existing places (spec § 5.3).

Purpose    : The Alerts tab says "3 places have no arrival alerts. Notify me".
             POST /api/places/notify-defaults?dry_run=1 lists the rules it would
             add; without dry_run it adds them, one per place, in one transaction.
Inputs     : Optional body {"place_ids": [..]} to limit the backfill.
Outputs    : {"dry_run", "count", "rules": [rule preview]} (alerts/default_rules.py).
Constraints: Registered on the /api/places router before its /{place_id}
             routes; gated by the lock middleware like every /api/ path.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from findplus.alerts.default_rules import backfill
from findplus.db.session import session_scope


def post_notify_defaults(
    dry_run: bool = False, place_ids: list[int] | None = Body(default=None, embed=True)
) -> dict[str, Any]:
    with session_scope() as s:
        result = backfill(s, dry_run=dry_run, place_ids=place_ids)
        if not dry_run:
            s.commit()
        return result


def register(router: APIRouter) -> None:
    router.add_api_route("/notify-defaults", post_notify_defaults, methods=["POST"])
