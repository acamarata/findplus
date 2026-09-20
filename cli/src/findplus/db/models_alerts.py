"""ORM models for the alert_rules / alert_deliveries tables (migration 0005).

Purpose : Map the existing alert_rules and alert_deliveries tables (created by
          migration 0005_groups_alerts, P1-E5-W5-S1-T1) onto SQLAlchemy models.
Constraints: No op.create_table here -- the tables already exist. Column types,
          nullability, CHECK and UNIQUE constraints are copied verbatim from
          the 0005 migration so metadata.create_all() in tests matches it
          exactly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from findplus.db.models import Base
from findplus.db.types import UtcDateTime


class AlertRule(Base):
    """A rule tying a place, a device or group, and a notification channel."""

    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint("cooldown_minutes BETWEEN 0 AND 1440", name="ck_alert_rules_cooldown"),
        CheckConstraint(
            "(group_id IS NULL) <> (device_id IS NULL)", name="ck_alert_rules_xor_target"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    place_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=True
    )
    group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True
    )
    device_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=True
    )
    on_enter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    on_exit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: A sorted, comma-separated subset of {telegram, webhook, whatsapp, native}.
    #: Validated in the API layer via alerts.channels_field, never by a SQLite
    #: CHECK (specs/notifications.md § 0).
    channels: Mapped[str] = mapped_column(Text, nullable=False)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    also_notify_members: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class AlertDelivery(Base):
    """One send attempt for one (rule, event) pair. Deduped by the UNIQUE below."""

    __tablename__ = "alert_deliveries"
    __table_args__ = (
        CheckConstraint("event_kind IN ('device','group')", name="ck_alert_deliveries_kind"),
        CheckConstraint(
            "status IN ('sent','failed','skipped','queued','delivered')",
            name="ck_alert_deliveries_status",
        ),
        UniqueConstraint(
            "rule_id", "event_kind", "event_id", "channel", name="uq_alert_deliveries_dedup"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False
    )
    event_kind: Mapped[str | None] = mapped_column(String(6), nullable=True)
    event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: 16, not 0005's 8: 'delivered' (migration 0008) is nine characters. SQLite
    #: never enforces a VARCHAR length, so the widening needs no ALTER of its own.
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: One row per channel per event now that a rule can target several, so the
    #: channel has to travel on the delivery, not just on the rule.
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Stamped by POST /api/alerts/deliveries/{id}/ack when the desktop app has
    #: actually shown a queued native notification.
    delivered_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
