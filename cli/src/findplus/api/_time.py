"""The one UTC-instant formatter every api/ module shares.

Purpose    : Render a datetime as the ISO-8601 `...Z` string api-contract.md
             pins for every timestamp the API returns.
Inputs     : An aware or naive-UTC datetime, or None.
Outputs    : `YYYY-MM-DDTHH:MM:SSZ`, or None.
Constraints: Its own module so `_helpers.py` and `_widget.py` can both use it
             without importing each other.
"""

from __future__ import annotations

from datetime import UTC, datetime


def _iso_z(dt: datetime | None) -> str | None:
    """UTC instant with a literal Z suffix.

    Built with strftime, never by concatenating "Z" onto an already
    offset-suffixed `isoformat()` string (that doubles up as "+00:00Z").
    """
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
