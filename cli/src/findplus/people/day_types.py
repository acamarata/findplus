"""Plain data types for the daily summary (spec § 7).

Purpose    : The value objects `people/day.py` consumes and returns, and the JSON
             shape of one summary line. No behaviour beyond serialising.
Inputs     : Built by people/day_load.py from stored rows, or by tests.
Outputs    : DayInput (everything the pure algorithm reads), Line, DayResult.
Constraints: No DB or HTTP. Every datetime is tz-aware UTC; `*_local` strings
             are rendered in the zone the caller asked for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from findplus.quality.fix import Fix


@dataclass(frozen=True)
class PlaceIn:
    id: int
    name: str
    kind: str
    lat: float
    lon: float
    radius_m: int


@dataclass(frozen=True)
class TrackerIn:
    device_id: str
    name: str
    role: str | None
    #: Short wording for sentences: "shoes", or the tracker's name when the role repeats.
    label: str
    weight: float


@dataclass(frozen=True)
class EventIn:
    """One stored person crossing (group_place_events with basis='person')."""

    at: datetime
    event_type: str  # ENTER | EXIT
    place_id: int
    lead_device_id: str | None
    #: Trackers whose own crossings or sightings back this event.
    evidence: tuple[str, ...]
    confidence: str  # high | medium


@dataclass(frozen=True)
class EpisodeIn:
    """A confirmed left-behind episode that overlaps the day."""

    id: int
    device_id: str
    place_id: int | None
    place_name: str | None
    started: datetime
    confirmed_at: datetime | None
    cleared_at: datetime | None
    clear_reason: str | None
    lat: float
    lon: float
    state: str = "left_behind"
    notified_at: datetime | None = None


@dataclass(frozen=True)
class NowIn:
    """The person's current state, only given when the day is today."""

    confidence: str  # likely | probably | unsure | unknown
    place_id: int | None
    place_name: str | None
    relation: str | None
    distance_m: float | None
    reference_place: str | None
    observed_at: datetime | None
    lead_device_id: str | None
    supporters: tuple[str, ...]
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class DayInput:
    name: str
    day: date
    tz: ZoneInfo
    now: datetime
    stale_after_minutes: int
    trackers: tuple[TrackerIn, ...]
    #: device_id -> non-suspect fixes, oldest first: the day plus a few hours before it.
    fixes: dict[str, tuple[Fix, ...]]
    suspect_count: int
    events: tuple[EventIn, ...]
    episodes: tuple[EpisodeIn, ...]
    places: tuple[PlaceIn, ...]
    now_fix: NowIn | None = None


@dataclass(frozen=True)
class Line:
    """One sentence of the day, with the trackers that back it."""

    kind: str
    at: datetime
    text: str
    #: The time part alone ("7:40 AM", "around 7:40 AM", "10:05 to 11:20 AM"); "" when none.
    time: str = ""
    end: datetime | None = None
    via: str = ""
    evidence: tuple[str, ...] = ()
    confidence: str = "high"
    approximate: bool = False
    place_id: int | None = None
    place_name: str | None = None
    lat: float | None = None
    lon: float | None = None

    def to_dict(self, tz: ZoneInfo) -> dict:
        def iso(v: datetime | None):
            return v.astimezone(tz).isoformat(timespec="seconds") if v else None

        def utc(v: datetime | None):
            return v.strftime("%Y-%m-%dT%H:%M:%SZ") if v else None

        return {
            "kind": self.kind,
            "at": utc(self.at),
            "at_local": iso(self.at),
            "end": utc(self.end),
            "end_local": iso(self.end),
            "time": self.time,
            "text": self.text,
            "via": self.via,
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "approximate": self.approximate,
            "place_id": self.place_id,
            "place_name": self.place_name,
            "latitude": self.lat,
            "longitude": self.lon,
        }


@dataclass(frozen=True)
class GapOut:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class DayResult:
    lines: list[Line] = field(default_factory=list)
    gaps: list[GapOut] = field(default_factory=list)
    lead_device_id: str | None = None
    suspect_text: str | None = None
    empty: bool = True
