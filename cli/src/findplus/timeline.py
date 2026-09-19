"""Timeline assembly: day grouping, movement classification, gaps, statistics.

Purpose : Turn stored observations into the day-view the UI renders.
Constraints:
    - "Distance" here is the geodesic distance BETWEEN OBSERVED LOCATIONS. It is
      not travelled distance and must never be presented as a road route.
    - Day boundaries are computed in the viewer's local timezone from UTC storage,
      so DST transitions produce correct 23h/25h days.
    - Movement filtering annotates; it never deletes. Every raw observation is
      returned with an `is_movement` flag alongside.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from findplus.db.models import LocationObservation
from findplus.geo import haversine_meters, is_meaningful_movement, meters_to_miles


def local_zone(tz_name: str | None = None) -> ZoneInfo:
    """The computer's IANA timezone unless explicitly overridden.

    An IANA zone (not a fixed UTC offset) is required so that day boundaries and
    DST transitions resolve correctly.
    """
    if tz_name:
        return ZoneInfo(tz_name)
    try:
        from tzlocal import get_localzone_name

        name = get_localzone_name()
        if name:
            return ZoneInfo(name)
    except Exception:
        pass
    try:  # POSIX fallback: /etc/localtime -> .../zoneinfo/Area/City
        link = Path("/etc/localtime").resolve()
        parts = link.parts
        if "zoneinfo" in parts:
            idx = len(parts) - 1 - parts[::-1].index("zoneinfo")
            return ZoneInfo("/".join(parts[idx + 1 :]))
    except Exception:
        pass
    return ZoneInfo("UTC")


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC half-open interval [start, end) covering one local calendar day.

    Uses next-midnight rather than start+24h, so 23-hour and 25-hour DST days are
    covered exactly.
    """
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


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
            "path_disclaimer": ("Observed path — actual route between detections may differ."),
            "points": [asdict(p) for p in self.points],
            "stats": asdict(self.stats) if self.stats else None,
        }


def fetch_observations(
    session: Session,
    device_id: str | None,
    start_utc: datetime,
    end_utc: datetime,
) -> list[LocationObservation]:
    """Observations with `observed_at` in [start, end), oldest first."""
    stmt = select(LocationObservation).where(
        LocationObservation.observed_at >= start_utc,
        LocationObservation.observed_at < end_utc,
    )
    if device_id:
        stmt = stmt.where(LocationObservation.device_id == device_id)
    stmt = stmt.order_by(LocationObservation.observed_at.asc(), LocationObservation.id.asc())
    return list(session.scalars(stmt))


def build_timeline(
    observations: list[LocationObservation],
    *,
    tz: ZoneInfo,
    movement_threshold_meters: float,
    gap_threshold_minutes: float,
) -> list[TimelinePoint]:
    """Annotate a chronological run of observations."""
    points: list[TimelinePoint] = []
    gap_seconds = gap_threshold_minutes * 60.0
    previous: LocationObservation | None = None

    for index, obs in enumerate(observations):
        if previous is None:
            delta_s: float | None = None
            meters: float | None = None
            movement = True  # the day's first fix always anchors the timeline
            gap_before = False
        else:
            delta_s = (obs.observed_at - previous.observed_at).total_seconds()
            meters = haversine_meters(
                previous.latitude, previous.longitude, obs.latitude, obs.longitude
            )
            movement = is_meaningful_movement(meters, movement_threshold_meters)
            gap_before = delta_s > gap_seconds

        points.append(
            TimelinePoint(
                id=obs.id,
                sequence=index + 1,
                observed_at=obs.observed_at.isoformat(),
                observed_at_local=obs.observed_at.astimezone(tz).isoformat(),
                fetched_at=obs.first_fetched_at.isoformat(),
                latitude=obs.latitude,
                longitude=obs.longitude,
                accuracy_meters=obs.accuracy_meters,
                altitude_meters=obs.altitude_meters,
                source=obs.source,
                is_own_report=obs.is_own_report,
                battery_level=obs.battery_level,
                times_returned=obs.times_returned,
                seconds_since_previous=delta_s,
                meters_from_previous=meters,
                miles_from_previous=meters_to_miles(meters) if meters is not None else None,
                is_movement=movement,
                gap_before=gap_before,
            )
        )
        previous = obs

    return points


def compute_stats(points: list[TimelinePoint]) -> DayStats:
    """Daily summary. Distance is between observations, not travelled."""
    if not points:
        return DayStats(
            observation_count=0,
            movement_count=0,
            first_observed_at=None,
            last_observed_at=None,
            first_observed_at_local=None,
            last_observed_at_local=None,
            time_span_seconds=0.0,
            approximate_distance_meters=0.0,
            approximate_distance_miles=0.0,
            longest_gap_seconds=0.0,
            longest_gap_start=None,
            longest_gap_end=None,
        )

    total_m = sum(p.meters_from_previous or 0.0 for p in points)
    longest_gap = 0.0
    gap_start = gap_end = None
    for prev, cur in pairwise(points):
        delta = cur.seconds_since_previous or 0.0
        if delta > longest_gap:
            longest_gap = delta
            gap_start, gap_end = prev.observed_at, cur.observed_at

    first, last = points[0], points[-1]
    span = (
        datetime.fromisoformat(last.observed_at) - datetime.fromisoformat(first.observed_at)
    ).total_seconds()

    return DayStats(
        observation_count=len(points),
        movement_count=sum(1 for p in points if p.is_movement),
        first_observed_at=first.observed_at,
        last_observed_at=last.observed_at,
        first_observed_at_local=first.observed_at_local,
        last_observed_at_local=last.observed_at_local,
        time_span_seconds=span,
        approximate_distance_meters=total_m,
        approximate_distance_miles=meters_to_miles(total_m),
        longest_gap_seconds=longest_gap,
        longest_gap_start=gap_start,
        longest_gap_end=gap_end,
    )


def day_timeline(
    session: Session,
    device_id: str | None,
    day: date,
    *,
    tz: ZoneInfo,
    movement_threshold_meters: float,
    gap_threshold_minutes: float,
    device_name: str | None = None,
) -> DayTimeline:
    """Assemble the full day view."""
    start_utc, end_utc = day_bounds_utc(day, tz)
    observations = fetch_observations(session, device_id, start_utc, end_utc)
    points = build_timeline(
        observations,
        tz=tz,
        movement_threshold_meters=movement_threshold_meters,
        gap_threshold_minutes=gap_threshold_minutes,
    )
    return DayTimeline(
        device_id=device_id,
        device_name=device_name or (observations[0].device_name if observations else None),
        day=day.isoformat(),
        timezone=str(tz),
        movement_threshold_meters=movement_threshold_meters,
        gap_threshold_minutes=gap_threshold_minutes,
        points=points,
        stats=compute_stats(points),
    )


def multi_day_timeline(
    session: Session,
    device_ids: list[str] | None,
    day: date,
    *,
    tz: ZoneInfo,
    movement_threshold_meters: float,
    gap_threshold_minutes: float,
) -> list[DayTimeline]:
    """One INDEPENDENT timeline per device.

    Timelines are never merged across devices: distance and elapsed time between
    consecutive points are only meaningful within a single tracker. Interleaving
    two trackers would produce distances that jump between unrelated objects.
    """
    start_utc, end_utc = day_bounds_utc(day, tz)
    if device_ids is None:
        device_ids = devices_with_data_between(session, start_utc, end_utc)

    return [
        day_timeline(
            session,
            device_id,
            day,
            tz=tz,
            movement_threshold_meters=movement_threshold_meters,
            gap_threshold_minutes=gap_threshold_minutes,
        )
        for device_id in device_ids
    ]


def devices_with_data_between(
    session: Session, start_utc: datetime, end_utc: datetime
) -> list[str]:
    """Device ids that have at least one observation in the interval."""
    stmt = (
        select(LocationObservation.device_id)
        .where(
            LocationObservation.observed_at >= start_utc,
            LocationObservation.observed_at < end_utc,
        )
        .distinct()
        .order_by(LocationObservation.device_id)
    )
    return list(session.scalars(stmt))


def days_with_data(session: Session, device_id: str | None, tz: ZoneInfo) -> list[str]:
    """Local calendar dates that contain at least one observation."""
    stmt = select(LocationObservation.observed_at)
    if device_id:
        stmt = stmt.where(LocationObservation.device_id == device_id)
    return sorted({ts.astimezone(tz).date().isoformat() for ts in session.scalars(stmt)})


def observation_count_between(
    session: Session, device_id: str | None, start_utc: datetime, end_utc: datetime
) -> int:
    stmt = select(func.count(LocationObservation.id)).where(
        LocationObservation.observed_at >= start_utc,
        LocationObservation.observed_at < end_utc,
    )
    if device_id:
        stmt = stmt.where(LocationObservation.device_id == device_id)
    return int(session.scalar(stmt) or 0)
