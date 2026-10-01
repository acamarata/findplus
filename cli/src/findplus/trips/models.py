"""Plain data types for trip segmentation.

Purpose    : The immutable value objects `segment()` consumes and returns.
Inputs     : Fix rows built from stored observations.
Outputs    : Fix, Stay, TripLeg, Gap, each with a `to_dict()` for the API.
Constraints: No DB or HTTP here. Timestamps are tz-aware UTC; every
             serialised row carries UTC (`*_at`) and, when a zone is given,
             a local ISO string (`*_local`) so the UI never guesses the zone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

#: Accuracy assumed when a fix reports none. Crowd-sourced fixes are rarely better.
DEFAULT_ACCURACY_M = 50.0


@dataclass(frozen=True, slots=True)
class Fix:
    """One sighting. `accuracy_m` is the radius the network reported, if any."""

    id: int
    t: datetime
    lat: float
    lon: float
    accuracy_m: float | None = None

    @property
    def acc(self) -> float:
        return self.accuracy_m if self.accuracy_m else DEFAULT_ACCURACY_M


@dataclass(frozen=True, slots=True)
class Gap:
    """A stretch with no sightings at all. `inside` names the stay or trip it falls in."""

    start: datetime
    end: datetime
    inside: str | None = None

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


@dataclass(frozen=True, slots=True)
class Stay:
    """A dwell: consecutive fixes inside one accuracy-scaled circle."""

    id: str
    start: datetime
    end: datetime
    lat: float
    lon: float
    radius_m: float
    fix_count: int
    longest_gap_min: float
    place_id: int | None = None
    place_name: str | None = None

    @property
    def label(self) -> str:
        return self.place_name or "Unnamed stop"

    @property
    def duration_min(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


@dataclass(frozen=True, slots=True)
class TripLeg:
    """Movement between two stays (or an open end when the data starts or stops moving)."""

    id: str
    start: datetime
    end: datetime
    from_stay: str | None
    to_stay: str | None
    points: tuple[Fix, ...]
    distance_m: float
    fix_count: int
    longest_gap_min: float
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_min(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0


def iso_utc(value: datetime) -> str:
    """UTC ISO-8601 with a trailing Z, whole seconds."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_local(value: datetime, tz: ZoneInfo | None) -> str | None:
    """Local ISO-8601 with offset, or None when no zone was supplied."""
    return value.astimezone(tz).isoformat(timespec="seconds") if tz else None
