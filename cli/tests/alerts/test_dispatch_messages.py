"""alerts/dispatch.py: render_message lag/date/truncation formatting, and as_utc parsing.

Split out of test_dispatch.py (PRI rule 7, <=300 lines/file).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from findplus import honesty
from findplus.alerts import dispatch_core

from ._helpers import NOW, _device_event, _group_event


@pytest.fixture(autouse=True)
def _pin_render_tz(pinned_tz):
    """render_message() renders in the machine's local zone (restored after
    the P2 UTC-only regression, R-P2 ruling 2026-09-22): pin one zone so
    every test in this file gets the same "Observed"/"reported" text on any
    host. America/New_York exercises a real, non-UTC abbreviation (EDT/EST).
    """
    pinned_tz("America/New_York")


def test_lag_in_message() -> None:
    from findplus.alerts.dispatch import render_message

    event = _device_event(fetched_at=NOW + timedelta(minutes=5))
    msg = render_message(event, NOW)
    assert "5 min late" in msg


def test_unknown_lag_is_not_reported_as_zero() -> None:
    """No fetched_at means the delay is unknown, never instant."""
    from findplus.alerts.dispatch import render_message

    msg = render_message(_device_event(fetched_at=None), NOW)
    assert "lag unknown" in msg
    assert "0 min late" not in msg
    assert "reported unknown" in msg


def test_message_omits_the_date_for_a_same_day_observation() -> None:
    from findplus.alerts.dispatch import render_message

    msg = render_message(_device_event(), NOW)
    observed_local = NOW.astimezone(dispatch_core.local_zone())
    assert f"Observed {observed_local:%H:%M %Z} ·" in msg
    assert f"{observed_local:%Y-%m-%d}" not in msg


def test_message_spells_out_the_date_when_the_observation_is_not_today() -> None:
    """A bare "Observed 14:20" in a notification reads as today."""
    from findplus.alerts.dispatch import render_message

    observed = NOW - timedelta(days=2)
    msg = render_message(_device_event(observed_at=observed, fetched_at=NOW), NOW)
    assert f"Observed {observed.astimezone(dispatch_core.local_zone()):%Y-%m-%d %H:%M %Z} ·" in msg
    assert len(msg) <= 400


def test_message_with_a_date_and_a_note_still_fits_the_limit() -> None:
    from findplus.alerts.dispatch import render_message

    msg = render_message(
        _device_event(observed_at=NOW - timedelta(days=400), place_name="P" * 600), NOW
    )
    assert len(msg) <= 400
    # The pinned sentence itself, not a second wording of it (honesty round 2 F6).
    assert msg.endswith(honesty.ALERTS_LATENCY)


def test_as_utc_parses_sqlite_strings() -> None:
    from findplus.alerts.dispatch import as_utc

    parsed = as_utc("2026-09-19 12:00:00.000000")
    assert parsed == NOW
    assert as_utc(None) is None
    assert as_utc(NOW) == NOW


def test_render_keeps_the_latency_sentence_when_truncating() -> None:
    from findplus.alerts.dispatch import render_message

    msg = render_message(_device_event(place_name="X" * 600), NOW)
    assert len(msg) <= 400
    assert msg.endswith(honesty.ALERTS_LATENCY)


def test_the_latency_tail_is_the_pinned_sentence_verbatim() -> None:
    """honesty.py: "Never paraphrase or shorten these"."""
    from findplus.alerts.dispatch_core import _LATENCY_TAIL

    assert f"\n{honesty.ALERTS_LATENCY}" == _LATENCY_TAIL
    assert "Find Hub" not in _LATENCY_TAIL, "the tail must not name one provider"


def test_a_note_is_kept_whole_or_dropped_whole() -> None:
    """A half-sliced note loses the clause that does the honesty work.

    The group note ends "...which does not mean they were left behind"; the old
    code sliced the combined string at the byte budget, so a long note could
    keep the accusation and lose the retraction.
    """
    from findplus.alerts.dispatch import render_message

    long_note = "Only Zoe is reporting (4 min ago). " + "Y" * 400
    msg = render_message(_group_event(note=long_note), NOW)

    assert len(msg) <= 400
    assert msg.endswith(honesty.ALERTS_LATENCY)
    assert "Only Zoe" not in msg, "an oversized note is dropped, never half-rendered"

    short_note = "Backpack have no recent fix, which does not mean they were left behind."
    kept = render_message(_group_event(note=short_note), NOW)
    assert short_note in kept
