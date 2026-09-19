"""Custom SQLAlchemy column types.

Purpose : Guarantee that every timestamp round-trips as timezone-aware UTC.
Constraints:
    - SQLite has no native timezone storage. Storing naive-UTC and re-attaching
      UTC on load is the only DST-safe approach; local time is a presentation
      concern handled in the API/UI layer, never in storage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, TypeDecorator


class UtcDateTime(TypeDecorator):
    """A DateTime that is always stored as naive UTC and returned as aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "Refusing to store a naive datetime. Attach a timezone "
                "(use datetime.now(UTC)) before persisting."
            )
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)
