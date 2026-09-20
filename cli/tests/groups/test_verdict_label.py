"""One verdict phrase, served by the API, shown by every surface.

E1 honesty round 3:
  F3 - `all_together` means everyone who REPORTED is together, and both
       verdict labels headlined that as plain "Together" while part of the
       group was silent. That is the overstating direction, and the mirror of
       the `partial`-with-nobody-diverged case that was already guarded.
  F4 - the CLI printed the raw enum, the dashboard said "Diverged" and the
       widget said "Partial" for the same state.
"""

from __future__ import annotations

import pytest

from findplus.groups.presence import verdict_label


def _label(verdict, diverged=(), reporting=2, considered=2):
    return verdict_label(
        verdict,
        diverged=list(diverged),
        reporting_count=reporting,
        considered_count=considered,
    )


def test_together_says_how_many_reported_when_a_member_is_silent() -> None:
    assert _label("all_together", reporting=2, considered=3) == "Together (2 of 3 reporting)"


def test_together_is_plain_when_the_whole_group_reported() -> None:
    assert _label("all_together", reporting=3, considered=3) == "Together"


def test_real_divergence_keeps_the_word() -> None:
    assert _label("partial", diverged=["Away"]) == "Diverged"


def test_a_lone_reporter_is_not_divergence() -> None:
    assert _label("partial", reporting=1, considered=3) == "Only 1 reporting"


def test_partial_without_divergence_or_a_lone_reporter() -> None:
    assert _label("partial", reporting=2, considered=4) == "Partial"


def test_unknown_stays_unknown() -> None:
    assert _label("unknown", reporting=0, considered=3) == "Unknown"


@pytest.mark.parametrize("verdict", ["all_together", "partial", "unknown"])
def test_no_surface_ever_sees_the_raw_enum(verdict: str) -> None:
    assert "_" not in _label(verdict, reporting=1, considered=2)


def test_the_api_serves_the_label_beside_the_verdict(tmp_db) -> None:
    from fastapi.testclient import TestClient

    from findplus.api import create_app
    from findplus.db.session import session_scope
    from findplus.groups.repo import create_group

    with session_scope() as session:
        group = create_group(session, name="Family")
        group_id = group.id

    client = TestClient(create_app())
    body = client.get(f"/api/groups/{group_id}/presence").json()

    assert "verdict_label" in body, "every surface reads this, so it must be served"
    assert body["verdict_label"] == verdict_label(
        body["verdict"],
        diverged=body["diverged"],
        reporting_count=body["reporting_count"],
        considered_count=body["considered_count"],
    )
