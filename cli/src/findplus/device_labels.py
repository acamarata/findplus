"""Device names that stay distinguishable when two trackers share one.

Purpose : Two trackers can carry the same label or provider name ("Ali Pixel 8a"
          twice). Every server-written sentence, export filename and KML name
          that printed that name made the two indistinguishable (UAT #7). This
          module appends a short id tail, and only then.
Inputs  : An open Session.
Outputs : `device_id -> text`: the display name, plus ` (<id tail>)` when another
          VISIBLE device (tracked, or with at least one observation) has the
          same display name. A name that is unique stays exactly as it was.
Constraints:
    - The tail is the shortest suffix of the device id, at least 4 characters,
      that tells the colliding devices apart (the whole id in the worst case).
    - web/app/device_label.js implements the same rule for the dashboard's own
      pickers; cli/tests/test_device_labels.py pins the server half.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from findplus.db.models import Device, LocationObservation
from findplus.labels import display_name

_MIN_TAIL = 4


def id_tails(device_ids: list[str]) -> dict[str, str]:
    """The shortest id suffix (>= 4 chars) that is unique among `device_ids`."""
    longest = max((len(i) for i in device_ids), default=0)
    for size in range(_MIN_TAIL, max(longest, _MIN_TAIL) + 1):
        tails = {i: i[-size:] for i in device_ids}
        if len(set(tails.values())) == len(device_ids):
            return tails
    return {i: i for i in device_ids}


def unique_names(session: Session) -> dict[str, str]:
    """Every device's name, with an id tail on the ones that collide."""
    seen = {
        row[0] for row in session.execute(select(LocationObservation.device_id).distinct()).all()
    }
    rows = session.execute(
        select(Device.device_id, Device.label, Device.name, Device.is_tracked)
    ).all()
    base = {r.device_id: display_name(r.label, r.name, r.device_id) or r.device_id for r in rows}
    visible = {r.device_id for r in rows if r.is_tracked or r.device_id in seen}
    by_name: dict[str, list[str]] = defaultdict(list)
    for device_id in visible:
        by_name[base[device_id]].append(device_id)
    clash = {name for name, ids in by_name.items() if len(ids) > 1}
    result = dict(base)
    for name in clash:
        group = sorted(i for i, b in base.items() if b == name)
        tails = id_tails(group)
        for device_id in group:
            result[device_id] = f"{name} ({tails[device_id]})"
    return result
