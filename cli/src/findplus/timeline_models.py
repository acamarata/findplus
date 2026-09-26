"""Timeline dataclasses: one observation point, one day's stats, one day's view.

Purpose : Plain data shapes timeline.py assembles and api/routes_history.py
          and cli/cmd_history.py serialize. Split out of timeline.py when it
          grew past the PRI rule-7 300-line file cap; re-exported there so
          `from findplus.timeline import TimelinePoint` (and friends) keeps
          working unchanged for every existing caller.
Constraints: No DB access, no wall clock — pure shapes only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class TimelinePoint:
    """One observation, enriched with its relationship to the previous one."""

    id: int
    sequence: int
    observed_at: str
    observed_at_local: str
    fetched_at: str
    latitude: float
    longitude: float
    accuracy_meters: float | None
    altitude_meters: float | None
    source: str | None
    is_own_report: bool | None
    battery_level: int | None
    times_returned: int
    seconds_since_previous: float | None
    meters_from_previous: float | None
    miles_from_previous: float | None
    is_movement: bool
    gap_before: bool


@dataclass(slots=True)
class DayStats:
    """Summary figures for one local calendar day."""

    observation_count: int
    movement_count: int
    first_observed_at: str | None
    last_observed_at: str | None
    first_observed_at_local: str | None
    last_observed_at_local: str | None
    time_span_seconds: float
    approximate_distance_meters: float
    approximate_distance_miles: float
    longest_gap_seconds: float
    longest_gap_start: str | None
    longest_gap_end: str | None
    distance_label: str = "Approximate distance between observed locations"


@dataclass(slots=True)
class DayTimeline:
    """Everything the UI needs to draw one day."""

    device_id: str | None
    device_name: str | None
    day: str
    timezone: str
    movement_threshold_meters: float
    gap_threshold_minutes: float
    points: list[TimelinePoint] = field(default_factory=list)
    stats: DayStats | None = None

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "day": self.day,
            "timezone": self.timezone,
            "movement_threshold_meters": self.movement_threshold_meters,
            "gap_threshold_minutes": self.gap_threshold_minutes,
            "path_disclaimer": ("Observed path. The actual route between detections may differ."),
            "points": [asdict(p) for p in self.points],
            "stats": asdict(self.stats) if self.stats else None,
        }
