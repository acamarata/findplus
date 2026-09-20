"""alerts/channels_field.py: the stored comma-list shape of alert_rules.channels.

Purpose    : Pin the parse/format contract migration 0008 and every caller rely
             on -- sorted, de-duplicated, non-empty, ids from the fixed four.
Constraints: Pure; no DB, no network.
"""

from __future__ import annotations

import pytest

from findplus.alerts.channels_field import VALID_CHANNELS, format_channels, parse_channels


def test_parse_round_trips_format() -> None:
    assert parse_channels(format_channels(["telegram", "native"])) == ["native", "telegram"]


def test_format_sorts_and_dedups() -> None:
    assert format_channels(["native", "telegram", "native"]) == "native,telegram"


def test_parse_sorts_dedups_and_ignores_whitespace() -> None:
    assert parse_channels(" telegram , native ,telegram") == ["native", "telegram"]


def test_parse_rejects_an_empty_string() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        parse_channels("")


def test_parse_rejects_a_comma_only_string() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        parse_channels(",,")


def test_parse_rejects_an_unknown_value() -> None:
    with pytest.raises(ValueError, match="unknown channel: email"):
        parse_channels("telegram,email")


def test_format_rejects_an_empty_list() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        format_channels([])


def test_format_rejects_an_unknown_value() -> None:
    with pytest.raises(ValueError, match="unknown channel: sms"):
        format_channels(["sms"])


def test_the_four_valid_channels_are_pinned() -> None:
    assert set(VALID_CHANNELS) == {"telegram", "webhook", "whatsapp", "native"}
