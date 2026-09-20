"""A stale member keeps the age of its last fix.

E1 honesty round 2 F7: member_status() returned MemberStatus(..., "stale",
None, None, None, ...), discarding last_observed_at and age_minutes for exactly
the members the UI has to age. _status_to_dict serialised age_minutes: null, so
every stale row in the dashboard and the widget read "no fix for unknown" --
always -- while the engine held the answer one line earlier. honesty.md's
presence_stale sentence is about not claiming a stale member's POSITION; the
place and the coordinates still stay None.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from findplus.groups.presence import member_status

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class _Fix:
    def __init__(self, observed_at, lat=411000000, lon=-806400000):
        self.observed_at = observed_at
        self.latitude_e7 = lat
        self.longitude_e7 = lon
        self.accuracy_meters = 10.0


class _Member:
    def __init__(self, last_fix):
        self.device_id = "dev1"
        self.name = "Backpack"
        self.last_fix = last_fix
        self.prev_fix = None


def _status(last_fix, stale_after=60):
    return member_status(_Member(last_fix), NOW, stale_after, 50, 30)


def test_a_stale_member_reports_when_it_was_last_heard_from() -> None:
    status = _status(_Fix(NOW - timedelta(hours=5)))

    assert status.status == "stale"
    assert status.age_minutes == 300
    assert status.last_observed_at == NOW - timedelta(hours=5)


def test_a_stale_member_still_claims_no_position() -> None:
    """The honesty part: where they are stays unknown, only the when is kept."""
    status = _status(_Fix(NOW - timedelta(days=3)))

    assert status.status == "stale"
    assert status.place is None
    assert status.latitude is None and status.longitude is None
    assert status.accuracy_meters is None
    assert status.age_minutes == 3 * 24 * 60


def test_a_member_that_never_reported_has_no_age() -> None:
    """ "unknown" stays meaningful: it is for a member with no fix at all."""
    status = _status(None)

    assert status.status == "stale"
    assert status.age_minutes is None
    assert status.last_observed_at is None
