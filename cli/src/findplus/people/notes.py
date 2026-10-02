"""The evidence sentence stored on a person event (group_place_events.note).

Purpose : "Sam's bag stayed at Home." and "(probably; only the bag
          reported)", spec § 5.4. Written once, when the event is recorded, so
          the alert, the delivery log and the day summary read the same words.
Inputs  : The person group, the place, the PersonFix that decided it, the
          member trackers and their device-level place states.
Outputs : One sentence string, or None when there is nothing to add.
Constraints: Pure apart from the catalog read. Names trackers, never invents.
"""

from __future__ import annotations

from findplus.people import messages as m
from findplus.people.describe import labels_for, names_of
from findplus.people.infer import PersonFix


def event_note(group, place, fix: PersonFix, trackers, states, event_type: str) -> str | None:
    """The stayed and probably clauses for one person crossing."""
    labels = labels_for(trackers, group.name)
    parts: list[str] = []
    if event_type == "EXIT":
        apart = [
            t.device_id
            for t in trackers
            if t.device_id not in fix.supporters
            and t.device_id not in fix.stale
            and states.get((t.device_id, place.id)) == "inside"
        ]
        if apart:
            what = names_of(apart, labels)
            parts.append(m.t("msg.stayed", name=group.name, what=what, place=place.name))
    if fix.confidence == "probably":
        if len(fix.supporters) == 1:
            parts.append(m.t("msg.probablyOnly", what=labels[fix.supporters[0]]))
        else:
            parts.append(m.t("msg.probably"))
    return " ".join(parts) or None
