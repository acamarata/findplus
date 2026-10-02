"""Read-only interface to observation quality, for other packages.

Purpose    : Let the people engine, stays, trips and the API ask "is this fix
             suspect?" without importing scoring code.
Inputs     : A session and either observation ids or devices plus a time window.
Outputs    : `suspect_ids` (a set of observation ids) and `is_suspect` (a bool).
Constraints: Signatures are stable: package B imports them. Reads only the
             `observation_quality` table (written by `quality.store`); an
             observation with no row, or one a later fix rescued, is not
             suspect. Never raises on an empty input.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import LocationObservation
from findplus.db.models_people import ObservationQuality


def suspect_ids(
    session: Session, device_ids: Iterable[str], start: datetime, end: datetime
) -> set[int]:
    """Ids of suspect observations of `device_ids` seen in [start, end] (observed_at)."""
    ids = list(device_ids)
    if not ids:
        return set()
    stmt = (
        select(ObservationQuality.observation_id)
        .join(
            LocationObservation,
            LocationObservation.id == ObservationQuality.observation_id,
        )
        .where(
            ObservationQuality.suspect.is_(True),
            LocationObservation.device_id.in_(ids),
            LocationObservation.observed_at >= start,
            LocationObservation.observed_at <= end,
        )
    )
    return set(session.scalars(stmt))


def is_suspect(session: Session, observation_id: int) -> bool:
    """True when the observation has a quality row marked suspect."""
    flag = session.scalar(
        select(ObservationQuality.suspect).where(
            ObservationQuality.observation_id == observation_id
        )
    )
    return bool(flag)
