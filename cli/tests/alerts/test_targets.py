"""alerts/targets.py: parse/validate/format Telegram targets."""

from __future__ import annotations

import pytest

from findplus.alerts.targets import MAX_TARGETS, format_targets, is_valid_target, parse_targets


def test_parse_single_numeric_id() -> None:
    assert parse_targets("123456789") == ["123456789"]


def test_parse_negative_group_id() -> None:
    assert parse_targets("-1001234567890") == ["-1001234567890"]


def test_parse_username() -> None:
    assert parse_targets("@some_group") == ["@some_group"]


def test_parse_trims_spaces() -> None:
    assert parse_targets(" 123 , 456 ") == ["123", "456"]


def test_parse_drops_empties() -> None:
    assert parse_targets("123,,456,") == ["123", "456"]


def test_parse_dedupes_preserving_first_occurrence_order() -> None:
    assert parse_targets("123,456,123") == ["123", "456"]


def test_parse_three_targets_person_group_and_person() -> None:
    """The owner's own phrasing: "a group, a person, or two people"."""
    assert parse_targets("111, -1009876543210, @a_person") == [
        "111",
        "-1009876543210",
        "@a_person",
    ]


def test_parse_empty_string_is_an_error() -> None:
    with pytest.raises(ValueError, match="at least one"):
        parse_targets("")


def test_parse_only_commas_is_an_error() -> None:
    with pytest.raises(ValueError, match="at least one"):
        parse_targets(" , , ")


def test_parse_bad_entry_names_the_exact_value() -> None:
    with pytest.raises(ValueError, match="not-a-target"):
        parse_targets("123,not-a-target,456")


def test_parse_username_too_short_is_rejected() -> None:
    with pytest.raises(ValueError, match="abc"):
        parse_targets("@abc")


def test_parse_caps_at_max_targets() -> None:
    many = ",".join(str(n) for n in range(MAX_TARGETS + 1))
    with pytest.raises(ValueError, match=f"at most {MAX_TARGETS}"):
        parse_targets(many)


def test_parse_exactly_max_targets_is_allowed() -> None:
    exactly = ",".join(str(n) for n in range(MAX_TARGETS))
    assert len(parse_targets(exactly)) == MAX_TARGETS


def test_is_valid_target_accepts_and_rejects() -> None:
    assert is_valid_target("123")
    assert is_valid_target("-100123")
    assert is_valid_target("@valid_name")
    assert not is_valid_target("@shrt")  # 4 chars, under the 5-char floor
    assert not is_valid_target("not-a-target")
    assert not is_valid_target("")
    assert not is_valid_target("12a34")


def test_format_targets_round_trips() -> None:
    assert format_targets(["111", "222"]) == "111,222"


def test_format_targets_dedupes_and_validates() -> None:
    assert format_targets(["111", "111", "@person_x"]) == "111,@person_x"
    with pytest.raises(ValueError):
        format_targets(["bad target"])
