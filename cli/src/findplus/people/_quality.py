"""The one door from the people engine to the quality flags (spec § 6.3).

Purpose : Person inference and left-behind skip sightings that look wrong.
          The flags come from findplus.quality (built separately); this module
          is the only place in people/ that imports it, so a build without
          that package still runs, just without the filter.
Inputs  : A session, device ids and a time range, or one observation id.
Outputs : The suspect observation ids (a set), or one boolean. Also the
          clock-skew rule the people engine applies on its own: a sighting
          that claims a time later than its first fetch + CLOCK_SLACK is from
          a reporter with a fast clock and never moves a person (r116 #5).
Constraints: Never raises because the quality package is missing: an import
          failure means "nothing is flagged", never "everything is". A real
          error inside a present quality package still propagates.
"""

from __future__ import annotations

from datetime import datetime, timedelta

try:  # pragma: no branch - which side runs depends on the build
    from findplus.quality.api import is_suspect as _is_suspect
    from findplus.quality.api import suspect_ids as _suspect_ids
except ImportError:  # the quality package is not in this build
    _is_suspect = None
    _suspect_ids = None


def suspect_ids(session, device_ids: list[str], start: datetime, end: datetime) -> set[int]:
    """Observation ids of these trackers in [start, end] that look wrong."""
    if _suspect_ids is None or not device_ids:
        return set()
    return set(_suspect_ids(session, device_ids, start, end))


def is_suspect(session, observation_id: int) -> bool:
    """True when this one sighting looks wrong (or is held for confirmation)."""
    if _is_suspect is None:
        return False
    return bool(_is_suspect(session, observation_id))


#: quality's own clock_skew threshold (spec § 6.2): observed_at later than
#: first_fetched_at + 5 min cannot be true.
CLOCK_SLACK = timedelta(minutes=5)


def skewed(observed_at: datetime, fetched_at: datetime | None) -> bool:
    """True when a sighting claims to be from after it was first fetched (+ slack).

    quality scores clock_skew softly (never suspect on its own); for the person
    engine it is hard, because one future time holds the backfill guard shut.
    """
    return fetched_at is not None and observed_at > fetched_at + CLOCK_SLACK


def as_of_for(observed_at: datetime, fetched_at: datetime | None) -> datetime:
    """The instant to evaluate a person at: never later than fetch + slack."""
    if fetched_at is None:
        return observed_at
    return min(observed_at, fetched_at + CLOCK_SLACK)
