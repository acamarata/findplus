"""A sighting held for a second one is "waiting to confirm", never "looked wrong" (uat116 #12)."""

from __future__ import annotations

from findplus.people.day import build_day
from findplus.people.day_text import suspect_sentence
from findplus.quality.text import reason_text

from .test_day_pure import HOME, SCHOOL, _now, day_input, every, fix, t


def _morning(held):
    """Kai at Home until 7:31; the School sighting at 7:40 is held."""
    home = every(HOME, t(0), t(7, 31), 30)
    now = _now(place_id=1, place_name="Home", observed_at=t(7, 31), lat=HOME.lat, lon=HOME.lon)
    return day_input({"zr": home}, now=t(7, 45), now_fix=now, held=held)


def test_a_held_sighting_is_not_counted_as_wrong():
    assert suspect_sentence(0, 1) == "1 sighting is waiting for a second sighting to confirm it."
    both = suspect_sentence(1, 2)
    assert both.startswith("1 sighting looked wrong and was left out. ")
    assert both.endswith("2 sightings are waiting for a second sighting to confirm them.")
    assert "looked wrong" not in build_day(_morning((fix(SCHOOL, t(7, 40)),))).suspect_text


def test_still_at_home_is_not_said_while_a_newer_sighting_waits():
    lines = [x.text for x in build_day(_morning((fix(SCHOOL, t(7, 40)),))).lines]
    assert lines[-1] == "Probably at School (waiting to confirm)"
    assert not any(x.startswith("Still at Home") for x in lines)


def test_an_older_held_sighting_does_not_hide_where_they_are():
    lines = [x.text for x in build_day(_morning((fix(SCHOOL, t(7, 0)),))).lines]
    assert not any("waiting to confirm" in x for x in lines)


def test_the_reason_text_says_waiting_not_wrong():
    text = reason_text(["jump_unconfirmed"])
    assert "waiting for a second sighting" in text and "wrong" not in text
