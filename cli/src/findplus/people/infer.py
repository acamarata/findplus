"""Where is the person now? Inferred from the trackers that are actually carried.

Purpose : specs/people-and-presence.md § 3. Score every reporting tracker by
          carry weight x age x motion x accuracy, cluster them, and say how sure
          the best cluster is: likely, probably, unsure or unknown. A moved
          tracker was carried; a parked one proves little.
Inputs  : MemberIn per tracker (its recent non-suspect fixes, newest last, and
          the places its own geofence state says it is inside), the saved
          places, a tz-aware `now`, InferParams.
Outputs : PersonFix. lat/lon are the lead tracker's own fix, never an average
          (invariant 5/12: no merged or invented point).
Constraints: Pure: no DB, no clock, a naive `now` raises ValueError. A stale
          tracker is never placed (honesty.PRESENCE_STALE), only listed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from findplus.geo import haversine_meters
from findplus.groups.presence import MemberStatus, _greedy_clique
from findplus.people.motion import DEFAULT_ACC as _DEFAULT_ACC
from findplus.people.motion import last_move_at, motion_of, moved

__all__ = ["InferParams", "MemberIn", "PersonFix", "PlaceRef", "TrackerFix", "infer", "motion_of"]


@dataclass(frozen=True)
class TrackerFix:
    observation_id: int
    latitude_e7: int
    longitude_e7: int
    accuracy_meters: float | None
    observed_at: datetime
    fetched_at: datetime | None = None

    @property
    def lat(self) -> float:
        return self.latitude_e7 / 1e7

    @property
    def lon(self) -> float:
        return self.longitude_e7 / 1e7


@dataclass(frozen=True)
class MemberIn:
    device_id: str
    name: str
    role: str | None
    weight: float
    fixes: tuple[TrackerFix, ...]  # non-suspect, <= now: the window plus one before it
    inside_place_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class PlaceRef:
    id: int
    name: str
    kind: str
    latitude_e7: int
    longitude_e7: int
    radius_meters: int


@dataclass(frozen=True)
class InferParams:
    stale_after_minutes: int = 90
    cluster_radius_meters: int = 150
    motion_window_hours: int = 6
    carried_factor: float = 2.0
    parked_factor: float = 0.4
    min_motion_meters: float = 150.0
    age_floor: float = 0.3
    near_place_meters: float = 500.0
    likely_ratio: float = 2.0
    likely_min: float = 0.9
    probably_ratio: float = 1.3


@dataclass(frozen=True)
class MemberScore:
    device_id: str
    name: str
    role: str | None
    weight: float
    motion: str  # carried | parked | unknown | stale
    score: float
    fix: TrackerFix | None
    age_minutes: int | None
    still: bool = False  # its last two fixes did not move (left-behind needs this)
    last_move_at: datetime | None = None  # latest move in the motion window, even when stale


@dataclass(frozen=True)
class PersonFix:
    confidence: str  # likely | probably | unsure | unknown
    place_id: int | None
    place_name: str | None
    relation: str | None  # at (confirmed inside) | near (500 m) | spot (distance_m from ref)
    distance_m: float | None
    reference_place: str | None
    lead_device_id: str | None
    lat: float | None
    lon: float | None
    accuracy_m: float | None
    observed_at: datetime | None
    fetched_at: datetime | None
    supporters: tuple[str, ...]
    dissenters: tuple[str, ...]
    stale: tuple[str, ...]
    best_score: float
    runner_up: float
    members: tuple[MemberScore, ...] = field(default_factory=tuple)
    clusters: tuple[tuple[str, ...], ...] = ()  # device ids per cluster, best first


def _f_acc(accuracy: float | None) -> float:
    acc = accuracy if accuracy is not None else _DEFAULT_ACC
    if acc <= 100:
        return 1.0
    return 0.7 if acc <= 300 else 0.4


def score_member(m: MemberIn, now: datetime, p: InferParams) -> MemberScore:
    """One tracker's score: weight x f_age x f_motion x f_acc, or stale."""
    ordered = sorted(m.fixes, key=lambda f: f.observed_at)
    last = ordered[-1] if ordered else None
    if last is None:
        return MemberScore(m.device_id, m.name, m.role, m.weight, "stale", 0.0, None, None)
    age = int((now - last.observed_at).total_seconds() // 60)
    move_at = last_move_at(ordered, now, p)
    if age > p.stale_after_minutes:
        return MemberScore(m.device_id, m.name, m.role, m.weight, "stale", 0.0, last, age,
                           last_move_at=move_at)  # fmt: skip
    f_age = max(p.age_floor, 1.0 - (1.0 - p.age_floor) * age / p.stale_after_minutes)
    motion = motion_of(ordered, now, p)
    f_motion = {"carried": p.carried_factor, "parked": p.parked_factor}.get(motion, 1.0)
    score = m.weight * f_age * f_motion * _f_acc(last.accuracy_meters)
    still = len(ordered) >= 2 and not moved(ordered[-2], last, p.min_motion_meters)
    return MemberScore(m.device_id, m.name, m.role, m.weight, motion, score, last, age, still,
                       move_at)  # fmt: skip


def clusters_of(reporting: list[MemberScore], radius_m: int) -> list[list[MemberScore]]:
    """Every cluster, by repeating presence._greedy_clique on what is left."""
    remaining = list(reporting)
    out: list[list[MemberScore]] = []
    while remaining:
        statuses = [
            MemberStatus(s.device_id, s.name, "unknown", None, s.fix.observed_at, s.age_minutes,
                         s.fix.accuracy_meters, s.fix.lat, s.fix.lon)
            for s in remaining
        ]  # fmt: skip
        picked = _greedy_clique(statuses, radius_m)
        out.append([remaining[i] for i in picked])
        remaining = [s for i, s in enumerate(remaining) if i not in picked]
    return out


def _cluster_sort_key(c: list[MemberScore]) -> tuple:
    return (-sum(s.score for s in c), sorted(s.device_id for s in c))


def parked_only_while_another_moved(best: list[MemberScore], scores: list[MemberScore]) -> bool:
    """The best cluster never moved, but another tracker (reporting or gone
    quiet) did within the window: the person went with that one, so the
    parked trackers say nothing about where they are now (review r116 #1)."""
    if any(s.motion != "parked" for s in best):
        return False
    ids = {s.device_id for s in best}
    return any(s.last_move_at is not None for s in scores if s.device_id not in ids)


def _confidence(best: float, runner_up: float, p: InferParams) -> str:
    if best <= 0:
        return "unsure"
    if best >= p.likely_ratio * runner_up and best >= p.likely_min:
        return "likely"
    if best >= p.probably_ratio * runner_up:
        return "probably"
    return "unsure"


def infer(
    members: list[MemberIn], places: list[PlaceRef], now: datetime, p: InferParams | None = None
) -> PersonFix:
    """The person's most likely whereabouts from their trackers (spec § 3)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    p = p or InferParams()
    scores = [score_member(m, now, p) for m in members]
    stale = tuple(s.device_id for s in scores if s.motion == "stale")
    reporting = [s for s in scores if s.motion != "stale"]
    inside = {m.device_id: m.inside_place_ids for m in members}
    if not reporting:
        return _unknown(scores, places, stale)
    ranked = sorted(clusters_of(reporting, p.cluster_radius_meters), key=_cluster_sort_key)
    best = ranked[0]
    b = sum(s.score for s in best)
    r = sum(s.score for s in ranked[1]) if len(ranked) > 1 else 0.0
    lead = max(best, key=lambda s: (s.score, s.weight, s.device_id))
    where = locate(lead.fix, lead.device_id, [s.device_id for s in best], inside, places, p)
    confidence = _confidence(b, r, p)
    if parked_only_while_another_moved(best, scores):
        confidence = "unsure"
    return PersonFix(
        confidence=confidence,
        **where,
        lead_device_id=lead.device_id,
        lat=lead.fix.lat,
        lon=lead.fix.lon,
        accuracy_m=lead.fix.accuracy_meters,
        observed_at=lead.fix.observed_at,
        fetched_at=lead.fix.fetched_at,
        supporters=tuple(s.device_id for s in best),
        dissenters=tuple(s.device_id for c in ranked[1:] for s in c),
        stale=stale,
        best_score=b,
        runner_up=r,
        members=tuple(scores),
        clusters=tuple(tuple(s.device_id for s in c) for c in ranked),
    )


def _where(pid=None, name=None, relation=None, distance=None, ref=None) -> dict:
    return {
        "place_id": pid,
        "place_name": name,
        "relation": relation,
        "distance_m": distance,
        "reference_place": ref,
    }


def locate(
    fix: TrackerFix,
    lead_id: str | None,
    best_ids: list[str],
    inside: dict[str, tuple[int, ...]],
    places: list[PlaceRef],
    p: InferParams,
) -> dict:
    """Place fields for a fix (spec § 3 step 6): a confirmed inside place of
    the lead (else of any best-cluster member), else "near" a place within
    500 m of its edge, else an unnamed spot measured from the nearest Home."""
    by_id = {pl.id: pl for pl in places}
    ids = [pid for pid in inside.get(lead_id, ()) if pid in by_id] or [
        pid for d in best_ids for pid in inside.get(d, ()) if pid in by_id
    ]
    if ids:
        pl = min((by_id[pid] for pid in ids), key=lambda x: (x.radius_meters, x.name))
        return _where(pl.id, pl.name, "at")
    edge = [(max(0.0, _dist(pl, fix) - pl.radius_meters), pl) for pl in places]
    near = [e for e in edge if e[0] <= p.near_place_meters]
    if near:
        pl = min(near, key=lambda e: (e[0], e[1].name))[1]
        return _where(pl.id, pl.name, "near")
    homes = [e for e in edge if e[1].kind == "home"] or edge
    if not homes:
        return _where(relation="spot")
    ref = min(homes, key=lambda e: (e[0], e[1].name))[1]
    return _where(relation="spot", distance=_dist(ref, fix), ref=ref.name)


def _dist(pl: PlaceRef, fix: TrackerFix) -> float:
    return haversine_meters(pl.latitude_e7 / 1e7, pl.longitude_e7 / 1e7, fix.lat, fix.lon)


def _unknown(scores: list[MemberScore], places: list[PlaceRef], stale: tuple) -> PersonFix:
    """Nobody reporting: when and near where the newest sighting was; lat/lon stay
    empty because a stale tracker is never placed (PRESENCE_STALE)."""
    seen = [s for s in scores if s.fix is not None]
    newest = max(seen, key=lambda s: s.fix.observed_at) if seen else None
    where = _where()
    if newest is not None:
        # Its old inside state is not a place claim: never "at", only "near".
        where = locate(newest.fix, None, [], {}, places, InferParams())
        if where["relation"] == "at":
            where["relation"] = "near"
    return PersonFix(
        confidence="unknown",
        **where,
        lead_device_id=newest.device_id if newest else None,
        lat=None,
        lon=None,
        accuracy_m=None,
        observed_at=newest.fix.observed_at if newest else None,
        fetched_at=newest.fix.fetched_at if newest else None,
        supporters=(),
        dissenters=(),
        stale=stale,
        best_score=0.0,
        runner_up=0.0,
        members=tuple(scores),
    )
