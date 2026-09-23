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

#: The same display names web/locales/en.json's `alerts.channels` catalog
#: uses (UAT4 N38): a rule's raw ids read as implementation detail everywhere
#: they were shown as-is ("native, whatsapp") -- the rule dialog and the
#: delivery log already render these; the rules table/list were the two
#: holdouts. `--json` output keeps the raw ids, unaffected by this dict.
CHANNEL_DISPLAY_NAMES: dict[str, str] = {
    "telegram": "Telegram",
    "webhook": "Webhook",
    "whatsapp": "WhatsApp",
    "native": "Desktop notification",
}


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


def display_channels(s: str) -> str:
    """Stored comma string -> "Desktop notification, WhatsApp" for table output.

    Falls back to the raw id for anything `CHANNEL_DISPLAY_NAMES` does not
    know (there is nothing outside `VALID_CHANNELS` today, but a table
    renderer should never raise over a display-name gap).
    """
    return ", ".join(CHANNEL_DISPLAY_NAMES.get(c, c) for c in parse_channels(s))
