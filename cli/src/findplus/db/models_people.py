"""ORM models for people, left-behind trackers, observation quality and digests.

Purpose : Map the four tables migration 0013_people_and_quality creates
          (specs/people-and-presence.md § 1.4) and pin the value vocabularies
          the API layer validates. The schema has no CHECK on these values on
          purpose: a CHECK on `groups`, `devices` or `places` would force a
          rebuild of a cascade parent.
Constraints: Schema only. Inference, events, scoring and role weights live in
          people/ and quality/. Raw observations never change (invariant 8);
          quality flags live beside them in observation_quality.
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
from sqlalchemy.orm import Mapped, mapped_column

from findplus.db.models import Base
from findplus.db.types import UtcDateTime

#: groups.kind. 'set' keeps quorum events; person/pet get person events.
GROUP_KINDS = ("set", "person", "pet")
PERSON_KINDS = ("person", "pet")
#: devices.role (NULL = guessed from the name). Weights live in people/roles.py.
DEVICE_ROLES = (
    "phone",
    "watch",
    "collar",
    "wallet",
    "keys",
    "shoes",
    "bag",
    "jacket",
    "bike",
    "scooter",
    "tablet",
    "laptop",
    "car",
    "luggage",
    "other",
)
#: places.kind. Several homes are allowed.
PLACE_KINDS = ("home", "school", "work", "family", "shop", "other")
#: group_place_events.basis.
EVENT_BASES = ("quorum", "person")
#: person_place_states.state / pending_side.
PERSON_PLACE_STATES = ("unknown", "inside", "outside")
#: left_behind.state; 'with_person' is never stored (no row means with the person).
LEFT_BEHIND_STATES = ("apart_pending", "left_behind", "cleared")
LEFT_BEHIND_CLEAR_REASONS = ("carried", "rejoined", "stale", "dismissed")
#: alert_deliveries.event_kind; 'left_behind' rows point at left_behind.id.
DELIVERY_EVENT_KINDS = ("device", "group", "left_behind")
#: The RAISE message the one-person-per-tracker triggers abort with.
ONE_PERSON_PER_DEVICE = "one_person_per_device"


class PersonPlaceState(Base):
    """Person-level inside/outside state per (person group, place), with anti-flap."""

    __tablename__ = "person_place_states"
    __table_args__ = (PrimaryKeyConstraint("group_id", "place_id"),)

    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    place_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(8), nullable=False, default="unknown")
    #: Backfill guard: an observation at or before this never moves the state.
    since_observed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: The side a transition is waiting to settle on, and since when.
    pending_side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pending_since: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_transition_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class LeftBehind(Base):
    """One left-behind episode for one tracker of one person (spec § 4)."""

    __tablename__ = "left_behind"
    __table_args__ = (Index("ix_left_behind_group_device_state", "group_id", "device_id", "state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False
    )
    #: The saved place the tracker sits in, or NULL for an unnamed spot.
    place_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("places.id", ondelete="SET NULL"), nullable=True
    )
    anchor_lat_e7: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_lon_e7: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    started_observed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    clear_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class ObservationQuality(Base):
    """Derived quality flags for one observation; recomputable, never edits the raw row."""

    __tablename__ = "observation_quality"
    __table_args__ = (Index("ix_observation_quality_suspect", "suspect"),)

    observation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("location_observations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    #: 0.0 to 1.0; suspect is score < 0.5 unless corroborated.
    score: Mapped[float] = mapped_column(Float, nullable=False)
    suspect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Comma-separated reason codes (aba_teleport, impossible_speed, ...); '' = none.
    reasons: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: The observation that rescued a suspect fix, if any.
    corroborated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("location_observations.id", ondelete="SET NULL"), nullable=True
    )
    algo_version: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class DigestRun(Base):
    """One daily-summary send per (person, local date, channel, target): never twice."""

    __tablename__ = "digest_runs"
    __table_args__ = (
        UniqueConstraint("group_id", "local_date", "channel", "target", name="uq_digest_runs_once"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    #: YYYY-MM-DD in the person's local zone.
    local_date: Mapped[str] = mapped_column(String(10), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    #: '' (never NULL) for channels without targets, so the UNIQUE still bites.
    target: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
