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


def test_a_single_stale_member_gets_a_singular_verb() -> None:
    """honesty round 3 F6: one member read "Backpack have no recent fix"."""
    from findplus.groups.presence import _build_stale_clause, _stale_suffix

    one = _build_stale_clause(["Backpack"])
    assert "Backpack has no recent fix" in one
    assert "it was left behind" in one
    assert _stale_suffix(["Backpack"]) == "; Backpack has no recent fix."


def test_several_stale_members_keep_the_plural() -> None:
    from findplus.groups.presence import _build_stale_clause, _stale_suffix

    many = _build_stale_clause(["Backpack", "Bike"])
    assert "Backpack and Bike have no recent fix" in many
    assert "they were left behind" in many
    assert _stale_suffix(["Backpack", "Bike"]).endswith("have no recent fix.")


def test_the_caveat_survives_in_both_forms() -> None:
    """The clause exists to say a missing fix is not evidence; never drop it."""
    from findplus.groups.presence import _build_stale_clause

    for names in (["A"], ["A", "B"], ["A", "B", "C"]):
        assert "does not mean" in _build_stale_clause(names)
