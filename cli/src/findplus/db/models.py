"""ORM models.

Purpose : Canonical local schema for Find Hub observation history.
Constraints:
    - All timestamps are UTC (see `UtcDateTime`).
    - Coordinates are stored as integer 1e-7 degrees (`latitude_e7`) because that
      is the native wire precision Google returns. Integers make deduplication
      exact and immune to float comparison drift; float degrees are derived.
    - `observed_at` (Find Hub's sighting time) and `fetched_at` (our query time)
      are distinct and never conflated.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from findplus.db.types import UtcDateTime

E7 = 1e7


class Base(DeclarativeBase):
    pass


class Device(Base):
    """A Find Hub device/tracker visible to the authenticated account."""

    __tablename__ = "devices"
    __table_args__ = (
        Index("ix_devices_tracked", "is_tracked"),
        Index("ix_devices_provider", "provider"),
    )

    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    #: Polled by the daemon. Any number of devices may be tracked at once.
    is_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Which LocationProvider owns this row (registry key, e.g. google-find-hub).
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="google-find-hub")
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    observations: Mapped[list[LocationObservation]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


class LocationObservation(Base):
    """One distinct location sighting reported by the Find Hub network.

    A single poll may yield several of these (Google returns a batch of recent
    network reports), which is why observations are keyed on the sighting itself
    rather than on the poll that retrieved them.
    """

    __tablename__ = "location_observations"
    __table_args__ = (
        # The deduplication contract: identical sighting => identical row.
        UniqueConstraint(
            "device_id",
            "observed_at",
            "latitude_e7",
            "longitude_e7",
            name="uq_observation_identity",
        ),
        Index("ix_obs_device_observed", "device_id", "observed_at"),
        Index("ix_obs_observed", "observed_at"),
        Index("ix_obs_device_fetched", "device_id", "first_fetched_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("devices.device_id"), nullable=False
    )
    device_name: Mapped[str] = mapped_column(String(256), nullable=False)

    latitude_e7: Mapped[int] = mapped_column(Integer, nullable=False)
    longitude_e7: Mapped[int] = mapped_column(Integer, nullable=False)
    altitude_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: When Find Hub says the tag was actually seen.
    observed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: When this computer first retrieved this sighting.
    first_fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: When this computer most recently saw Find Hub return this same sighting.
    last_fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: How many polls returned this identical sighting. Poll health, not movement.
    times_returned: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: Find Hub report class, e.g. crowdsourced / own_report / semantic.
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_own_report: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    semantic_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    battery_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)

    device: Mapped[Device] = relationship(back_populates="observations")

    @property
    def latitude(self) -> float:
        return self.latitude_e7 / E7

    @property
    def longitude(self) -> float:
        return self.longitude_e7 / E7


class PollRun(Base):
    """One attempt to query Find Hub. Records health independently of location data."""

    __tablename__ = "poll_runs"
    __table_args__ = (Index("ix_pollrun_started", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: ok | no_location | error | auth_error | timeout
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    observations_returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observations_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Setting(Base):
    """Small mutable key/value store (selected device, schema bookkeeping)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class Place(Base):
    """A named circular geofence area (migration 0004)."""

    __tablename__ = "places"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    latitude_e7: Mapped[int] = mapped_column(Integer, nullable=False)
    longitude_e7: Mapped[int] = mapped_column(Integer, nullable=False)
    radius_meters: Mapped[int] = mapped_column(Integer, nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="#2f80ed")
    enter_confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    exit_confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class PlaceEvent(Base):
    """One ENTER/EXIT crossing of a place by a device (migration 0004)."""

    __tablename__ = "place_events"
    __table_args__ = (
        Index("ix_place_events_place_device_observed", "place_id", "device_id", "observed_at"),
        Index("ix_place_events_observed", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    place_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("devices.device_id"), nullable=False
    )
    #: Vestigial: nothing writes this. Group alerts landed as the separate
    #: group_place_events table instead, so a group filter on place events
    #: resolves the group to its members (places/repo.py:list_place_events).
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(5), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    observation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("location_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    confidence: Mapped[str] = mapped_column(String(6), nullable=False)
    distance_meters: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class PlaceState(Base):
    """Current geofence state (with hysteresis streak) per (place, device)."""

    __tablename__ = "place_states"
    __table_args__ = (PrimaryKeyConstraint("place_id", "device_id"),)

    place_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("devices.device_id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(8), nullable=False, default="unknown")
    since_observed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    streak_side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class Group(Base):
    """A named set of devices with quorum/presence settings (migration 0005)."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="#27ae60")
    quorum: Mapped[str] = mapped_column(String(16), nullable=False, default="majority")
    cluster_radius_meters: Mapped[int] = mapped_column(Integer, nullable=False, default=150)
    stale_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class DeviceGroup(Base):
    """Membership: which devices belong to which groups (migration 0005)."""

    __tablename__ = "device_group"
    __table_args__ = (PrimaryKeyConstraint("device_id", "group_id"),)

    device_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )


class GroupPlaceEvent(Base):
    """One group-level ENTER/EXIT crossing that met its group's quorum (migration 0005)."""

    __tablename__ = "group_place_events"
    __table_args__ = (Index("ix_gpe_group_place_observed", "group_id", "place_id", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    place_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(5), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: JSON-encoded list of the contributing place_events.id values.
    member_event_ids: Mapped[str] = mapped_column(Text, nullable=False)
    members_crossed: Mapped[int] = mapped_column(Integer, nullable=False)
    members_considered: Mapped[int] = mapped_column(Integer, nullable=False)
    members_stale: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(6), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
