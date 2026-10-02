"""The "where is Sam now" sentence for a PersonFix (spec § 3 step 5).

Purpose : Turn the engine's answer into plain words that never overstate it:
          "Likely at School, seen 12 min ago (shoes, bike)." / "Not sure: ..."
          / "No recent sightings. Last seen near Home at 4:10 PM." Never "is at".
Inputs  : A PersonFix, the person's Tracker rows, the saved places, `now`.
Outputs : One sentence (str); short tracker labels for other sentences.
Constraints: Pure apart from the catalog read in people/messages.py. A stale
          tracker is named as having no recent sighting, never placed.
"""

from __future__ import annotations

from datetime import datetime

from findplus.people import messages as m
from findplus.people.infer import InferParams, PersonFix, PlaceRef, locate


def labels_for(trackers, owner: str | None = None) -> dict[str, str]:
    """device_id -> 'shoes' / 'Sam Shoes Red' (people/messages.short_labels)."""
    return m.short_labels([(t.device_id, t.role, t.name) for t in trackers], owner)


def place_text(place_name: str | None, relation: str | None, distance_m, reference) -> str:
    """'School', or 'an unnamed spot, 1.2 km from Home', or 'an unnamed spot'."""
    if place_name and relation in ("at", "near"):
        return place_name
    if distance_m is not None and reference:
        return m.t("now.unnamedSpotFrom", distance=m.fmt_distance(distance_m), place=reference)
    return m.t("now.unnamedSpot")


def names_of(ids, labels: dict[str, str]) -> str:
    return m.join_words(list(dict.fromkeys(labels.get(i, i) for i in ids)))


def _unsure_parts(fix: PersonFix, labels: dict[str, str], places: list[PlaceRef]) -> str:
    """'shoes near School, bag near Home': each cluster by its own lead's fix."""
    scores = {s.device_id: s for s in fix.members}
    parts = []
    for cluster in fix.clusters:
        lead = max((scores[d] for d in cluster), key=lambda s: (s.score, s.device_id))
        where = locate(lead.fix, None, [], {}, places, InferParams())
        text = place_text(where["place_name"], where["relation"], where["distance_m"],
                          where["reference_place"])  # fmt: skip
        parts.append(m.t("now.part", trackers=names_of(cluster, labels), place=text))
    return ", ".join(parts)


def now_text(
    fix: PersonFix, trackers, places: list[PlaceRef], now: datetime, owner: str | None = None
) -> str:
    """The one-line now-status sentence for a person (`owner` = the person's name)."""
    labels = labels_for(trackers, owner)
    where = place_text(fix.place_name, fix.relation, fix.distance_m, fix.reference_place)
    if fix.confidence == "unknown":
        if fix.observed_at is None:
            return m.t("now.unknownNever")
        return m.t("now.unknown", place=where, time=m.fmt_time(fix.observed_at))
    if fix.confidence == "unsure":
        text = m.t("now.unsure", parts=_unsure_parts(fix, labels, places))
    else:
        age = m.fmt_age(int((now - fix.observed_at).total_seconds() // 60))
        rel = "At" if fix.relation == "at" or fix.relation == "spot" else "Near"
        key = f"now.{fix.confidence}{rel}"
        text = m.t(key, place=where, age=age, trackers=names_of(fix.supporters, labels))
    if fix.stale:
        text += " " + m.t("now.stale", trackers=names_of(fix.stale, labels))
    return text
