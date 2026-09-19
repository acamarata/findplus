"""Pure quorum engine: does a group-place crossing meet its group's quorum?

Purpose : Decide whether enough non-stale members of a group crossed the same
          place within a window to emit one group_place_event (D19).
Inputs  : QuorumInput — the group's quorum rule, member/stale device ids, and
          the (device_id, place_event_id, observed_at) crossings seen in the
          window. Callers pass tz-aware datetimes.
Outputs : QuorumResult — fire/no-fire, counts, the contributing event ids,
          a confidence label and a note.
Constraints: Pure, no DB access, no wall clock. A naive `observed_at` raises
    ValueError. `quorum='all'` never fires while any member is stale,
    regardless of how many non-stale members crossed.
Reuse: dataclass/comment-block style matches findplus.groups.presence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class QuorumInput:
    group_id: int
    quorum: str
    member_ids: list[str]
    stale_ids: list[str]
    place_id: int
    event_type: str
    window_minutes: int
    member_events: list[tuple[str, int, datetime]]


@dataclass(frozen=True)
class QuorumResult:
    fire: bool
    members_crossed: int
    members_considered: int
    members_stale: int
    member_event_ids: list[int]
    observed_at: datetime | None
    confidence: str
    note: str


def quorum_needed(quorum: str, considered: int) -> int:
    """How many considered (non-stale) members must cross for this rule to fire."""
    if considered == 0:
        return 0
    if quorum == "any":
        return 1
    if quorum == "majority":
        return considered // 2 + 1
    if quorum == "all":
        return considered
    if quorum.isdigit():
        # Floor of 1: groups.validation rejects "0" on the way in, but a row
        # hand-edited in the DB must still not produce needed == 0, which would
        # fire an alert reading "0 of 3 tags entered" with nobody there.
        return max(1, min(int(quorum), considered))
    raise ValueError(f"Unknown quorum value: {quorum!r}")


def stale_note_for_names(names: list[str]) -> str:
    """The `; ... have no recent fix.` clause when the stale members are known."""
    return f"; {', '.join(names)} have no recent fix." if names else "."


def stale_note_for_count(count: int) -> str:
    """The same clause built from a stored count (group_place_events has no names)."""
    if count <= 0:
        return "."
    subject = "1 tag has" if count == 1 else f"{count} tags have"
    return f"; {subject} no recent fix."


def group_event_note(
    *, crossed: int, considered: int, event_type: str, place: str, stale_note: str = "."
) -> str:
    """The honest one-line summary of a group crossing (specs/engines.md § quorum).

    It is the only place an alert says how many tags actually crossed and how
    many were silent, so "Sarah's group arrived at School" can never read as
    "everyone arrived" when one member simply had no fix.
    """
    verb = "entered" if event_type == "ENTER" else "left"
    return f"{crossed} of {considered} tags {verb} {place}{stale_note}"


def evaluate_quorum(q: QuorumInput) -> QuorumResult:
    """Apply the quorum rule to one window's member crossings."""
    for _dev_id, _evt_id, observed_at in q.member_events:
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")

    deduped: dict[str, tuple[int, datetime]] = {}
    for dev_id, evt_id, observed_at in q.member_events:
        prior = deduped.get(dev_id)
        if prior is None or observed_at > prior[1]:
            deduped[dev_id] = (evt_id, observed_at)

    considered_set = set(q.member_ids) - set(q.stale_ids)
    n_considered = len(considered_set)

    crossed_events = [
        (dev_id, evt_id, observed_at)
        for dev_id, (evt_id, observed_at) in deduped.items()
        if dev_id in considered_set
    ]
    n_crossed = len(crossed_events)
    n_stale = len(q.stale_ids)
    needed = quorum_needed(q.quorum, n_considered)

    fire = n_considered > 0 and n_crossed >= needed
    if q.quorum == "all" and n_stale > 0:
        fire = False

    if n_crossed == n_considered and n_stale == 0:
        confidence = "high"
    elif n_crossed >= needed:
        confidence = "medium"
    else:
        confidence = "low"

    observed_at = max((e[2] for e in crossed_events), default=None)
    member_event_ids = [e[1] for e in sorted(crossed_events, key=lambda e: e[2])]

    note = group_event_note(
        crossed=n_crossed,
        considered=n_considered,
        event_type=q.event_type,
        place=f"place {q.place_id}",
        stale_note=stale_note_for_names(q.stale_ids),
    )

    return QuorumResult(
        fire=fire,
        members_crossed=n_crossed,
        members_considered=n_considered,
        members_stale=n_stale,
        member_event_ids=member_event_ids,
        observed_at=observed_at,
        confidence=confidence,
        note=note,
    )
