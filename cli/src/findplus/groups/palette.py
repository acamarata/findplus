"""Default colour for a new person or pet: the first palette colour nobody uses.

Purpose : A new person should be told apart on the map and in lists without the
          owner opening a colour picker. Existing people are never recoloured.
Inputs  : An open Session.
Outputs : One `#rrggbb` string from labels.DEVICE_PALETTE (the 12 swatches the
          dashboard colour picker shows, same order).
Constraints: Reads only. Colours are compared case-insensitively. When all 12
          are taken the least-used colour wins (ties go to palette order), so
          colours cycle evenly instead of piling onto the first one.
Reuse   : groups/repo.create_group (every create path: API, people suggestion
          accept, CLI), people/repo via create_group.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Group
from findplus.db.models_people import PERSON_KINDS
from findplus.labels import DEVICE_PALETTE


def next_person_color(session: Session) -> str:
    """First palette colour not used by another person or pet; else the least used."""
    used = Counter(
        (c or "").lower()
        for c in session.scalars(select(Group.color).where(Group.kind.in_(PERSON_KINDS)))
    )
    return min(DEVICE_PALETTE, key=lambda c: used[c.lower()])
