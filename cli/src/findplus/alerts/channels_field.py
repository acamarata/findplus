"""Parse and format alert_rules.channels: a sorted, de-duplicated comma list.

Purpose    : One place that knows the stored shape of a rule's channel set, so
             the API, the CLI and dispatch never split or join that string
             themselves.
Inputs     : The stored comma string, or a list of channel ids.
Outputs    : A sorted list of ids, or the sorted comma string.
Constraints: Raises ValueError on an empty set or an unknown id. Validation is
             here rather than in a SQLite CHECK (specs/notifications.md § 0):
             SQLite has no per-element regex CHECK worth the complexity for
             four fixed values.
"""

from __future__ import annotations

VALID_CHANNELS = frozenset({"telegram", "webhook", "whatsapp", "native"})


def _checked(values: list[str]) -> list[str]:
    if not values:
        raise ValueError("channels must not be empty")
    for value in values:
        if value not in VALID_CHANNELS:
            raise ValueError(f"unknown channel: {value}")
    return sorted(set(values))


def parse_channels(s: str) -> list[str]:
    """Stored comma string -> sorted, de-duplicated list of channel ids."""
    return _checked([v.strip() for v in s.split(",") if v.strip()])


def format_channels(values: list[str]) -> str:
    """List of channel ids -> the sorted, de-duplicated comma string to store."""
    return ",".join(_checked(list(values)))
