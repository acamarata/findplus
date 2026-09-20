"""Pure group presence engine: per-member status and group verdict.

Purpose : Classify each group member as present-at-a-place, moving, stale or
          unknown, then combine those into a group verdict (all together,
          partial, or unknown) with a plain-language note.
Inputs  : MemberInput per device (last/previous fix, inside_places from
          place_states) and the group's stale/cluster-radius/movement
          settings. Callers pass tz-aware `now`.
Outputs : MemberStatus per device; GroupPresence for the group.
Constraints: Pure, no DB access, no wall clock; a naive `now` raises
    ValueError. Honesty (D18): a stale member is never "at home" or "left
    behind" — only reported as having no recent fix.
Reuse: findplus.geo.haversine_meters; findplus.places.geofence.Fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from findplus.geo import haversine_meters
from findplus.places.geofence import Fix

Status = Literal["present_at_place", "moving", "stale", "unknown"]
Verdict = Literal["all_together", "partial", "unknown"]

_DEFAULT_ACCURACY_METERS = 100.0


@dataclass(frozen=True)
class MemberInput:
    device_id: str
    name: str
    last_fix: Fix | None
    prev_fix: Fix | None
    inside_places: list[str]


@dataclass(frozen=True)
class MemberStatus:
    device_id: str
    name: str
    status: Status
    place: str | None
    last_observed_at: datetime | None
    age_minutes: int | None
    accuracy_meters: float | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class GroupPresence:
    group_id: int
    verdict: Verdict
    together: list[str]
    diverged: list[str]
    stale: list[str]
    reporting_count: int
    considered_count: int
    cluster_radius_meters: int
    window_minutes: int
    note: str


def _names_joined(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def verdict_label(
    verdict: str, *, diverged: list[str], reporting_count: int, considered_count: int
) -> str:
    """The one phrase every surface shows for a group verdict.

    Served by the API beside `verdict` so the dashboard, the widget and the CLI
    cannot drift apart again: they printed the raw enum, "Diverged" and
    "Partial" for the same state (E1 honesty round 3 F4).

    `all_together` means everyone who REPORTED is together, which reads as a
    claim about the whole group when part of it is silent -- the overstating
    direction, and the mirror of the `partial`-with-nobody-diverged case that
    was already guarded. So a group with a stale member says how many reported
    (E1 honesty round 3 F3).
    """
    if verdict == "all_together":
        if considered_count and reporting_count < considered_count:
            return f"Together ({reporting_count} of {considered_count} reporting)"
        return "Together"
    if verdict != "partial":
        return "Unknown"
    if diverged:
        return "Diverged"
    if reporting_count == 1:
        return "Only 1 reporting"
    return "Partial"


def _build_stale_clause(stale_names: list[str]) -> str:
    """Standalone sentence closing the 0/1-reporting notes (engines.md)."""
    if not stale_names:
        return ""
    joined = _names_joined(stale_names)
    # The same agreement this module already does for divergence: one member
    # read "Backpack have no recent fix" (E1 honesty round 3 F6).
    verb = "has" if len(stale_names) == 1 else "have"
    they = "it was" if len(stale_names) == 1 else "they were"
    return f" {joined} {verb} no recent fix, which does not mean {they} left behind."


def _stale_suffix(stale_names: list[str]) -> str:
    """Semicolon-joined suffix engines.md pins for the >=2-reporting notes.

    Reusing `_build_stale_clause` here runs two statements together
    ("... near Home Backpack have no recent fix ...").
    """
    if not stale_names:
        return ""
    verb = "has" if len(stale_names) == 1 else "have"
    return f"; {_names_joined(stale_names)} {verb} no recent fix."


def member_status(
    m: MemberInput,
    now: datetime,
    stale_after_minutes: int,
    movement_threshold_meters: float,
    window_minutes: int,
) -> MemberStatus:
    """Classify one member's most recent fix: stale, present, moving or unknown."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    stale = m.last_fix is None or now - m.last_fix.observed_at > timedelta(
        minutes=stale_after_minutes
    )
    if stale:
        # Keep the last fix's timestamp and age. `place` and the coordinates
        # stay None -- honesty.md's presence_stale sentence is about not
        # claiming a stale member's POSITION, not about hiding when they were
        # last heard from. Dropping the age made every stale row in the
        # dashboard and the widget read "no fix for unknown", always, while
        # the answer sat in the row one line above (E1 honesty round 2 F7).
        last = m.last_fix.observed_at if m.last_fix else None
        age = int((now - last).total_seconds() / 60) if last else None
        return MemberStatus(m.device_id, m.name, "stale", None, last, age, None, None, None)

    lat, lon = m.last_fix.latitude_e7 / 1e7, m.last_fix.longitude_e7 / 1e7
    age = int((now - m.last_fix.observed_at).total_seconds() / 60)

    place: str | None = None
    #: Both fixes must fall inside window_minutes, not just prev_fix -- a
    #: last_fix older than the window is stale-adjacent (its age already
    #: reads unknown-fresh territory) and must fall through to "unknown",
    #: not report "moving" off a prev_fix that happens to be newer.
    moved = (
        m.prev_fix is not None
        and m.prev_fix.observed_at >= now - timedelta(minutes=window_minutes)
        and m.last_fix.observed_at >= now - timedelta(minutes=window_minutes)
        and haversine_meters(m.prev_fix.latitude_e7 / 1e7, m.prev_fix.longitude_e7 / 1e7, lat, lon)
        > movement_threshold_meters
    )
    if m.inside_places:
        status: Status = "present_at_place"
        place = m.inside_places[0]
    elif moved:
        status = "moving"
    else:
        status = "unknown"

    return MemberStatus(
        m.device_id, m.name, status, place, m.last_fix.observed_at, age,
        m.last_fix.accuracy_meters, lat, lon,
    )  # fmt: skip


def _greedy_clique(reporting: list[MemberStatus], cluster_radius_meters: int) -> list[int]:
    """Indices into `reporting` of a greedy largest clique, seeded from the closest pair."""

    def acc(i: int) -> float:
        v = reporting[i].accuracy_meters
        return v if v is not None else _DEFAULT_ACCURACY_METERS

    def dist(i: int, j: int) -> float:
        a, b = reporting[i], reporting[j]
        return haversine_meters(a.latitude, a.longitude, b.latitude, b.longitude)

    n = len(reporting)
    best_pair, best_dist = None, float("inf")
    for i in range(n):
        for j in range(i + 1, n):
            d = dist(i, j)
            if d < best_dist:
                best_dist, best_pair = d, (i, j)
    if best_pair is None:
        return list(range(n))

    seed_i, seed_j = best_pair
    within_threshold = best_dist <= cluster_radius_meters + max(acc(seed_i), acc(seed_j))
    clique = [seed_i, seed_j] if within_threshold else [seed_i]
    for k in range(n):
        if k not in clique and all(
            dist(k, m) <= cluster_radius_meters + max(acc(k), acc(m)) for m in clique
        ):
            clique.append(k)
    return clique


def group_presence(
    group_id: int,
    members: list[MemberInput],
    now: datetime,
    stale_after_minutes: int,
    cluster_radius_meters: int,
    movement_threshold_meters: float,
    window_minutes: int,
) -> GroupPresence:
    """Combine every member's status into a group-level presence verdict."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    def result(verdict, together, diverged, reporting_count, note) -> GroupPresence:
        return GroupPresence(
            group_id, verdict, together, diverged, stale_names, reporting_count,
            len(statuses), cluster_radius_meters, window_minutes, note,
        )  # fmt: skip

    statuses = [
        member_status(m, now, stale_after_minutes, movement_threshold_meters, window_minutes)
        for m in members
    ]
    reporting = [s for s in statuses if s.status != "stale"]
    stale_names = [s.name for s in statuses if s.status == "stale"]
    stale_clause = _build_stale_clause(stale_names)

    if len(reporting) == 0:
        # Name the members, like every other note. The one a worried user
        # reaches printed a database id ("No member of group 3 has reported"),
        # and dropped _build_stale_clause -- the sentence whose whole job is to
        # say a missing fix is not evidence (E1 honesty round 3 F7).
        who = _names_joined([s.name for s in statuses]) or "This group"
        note = (
            f"{who} {'has' if len(statuses) == 1 else 'have'} not reported in the last "
            f"{stale_after_minutes} minutes; nothing can be said about where "
            f"{'it is' if len(statuses) == 1 else 'they are'}."
        )
        return result("unknown", [], [], 0, note)

    if len(reporting) == 1:
        r = reporting[0]
        note = f"Only {r.name} is reporting ({r.age_minutes} min ago).{stale_clause}"
        return result("partial", [], [], 1, note)

    stale_suffix = _stale_suffix(stale_names)
    clique = _greedy_clique(reporting, cluster_radius_meters)
    together = [reporting[i] for i in clique]
    diverged = [s for i, s in enumerate(reporting) if i not in clique]
    together_names = [s.name for s in together]
    diverged_names = [s.name for s in diverged]

    if not diverged:
        place_names = list({s.place for s in together if s.place})
        location = place_names[0] if len(place_names) == 1 else "each other"
        note = f"{len(together_names)} tags together near {location}{stale_suffix}"
        return result("all_together", together_names, [], len(reporting), note)

    max_div_dist = max(
        haversine_meters(d.latitude, d.longitude, t.latitude, t.longitude)
        for d in diverged
        for t in together
    )
    diverged_str, together_str = _names_joined(diverged_names), _names_joined(together_names)
    verb = "is" if len(diverged_names) == 1 else "are"
    note = (
        f"{diverged_str} {verb} away from {together_str} "
        f"({round(max_div_dist)} m apart){stale_suffix}"
    )
    return result("partial", together_names, diverged_names, len(reporting), note)
