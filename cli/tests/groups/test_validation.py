"""groups/repo.py._validate_group_fields — cluster_radius_meters, stale_after_minutes, quorum.

Purpose : Guard the CHECK-constraint ranges (specs/data-model.md § Migration 0005) and the
          quorum grammar (specs/engines.md § quorum) at the repo layer, since SQLite enforces
          the CHECK constraints but never validated quorum and both create/update previously
          let an out-of-range value reach the DB as an unhandled 500.
Inputs  : A `session` fixture (migrated, empty, throwaway DB per test).
Outputs : None (pytest assertions).
Constraints: Never touches the real DB or network (per conftest.py).
"""

from __future__ import annotations

import pytest

from findplus.groups.quorum import quorum_needed
from findplus.groups.repo import create_group, update_group


def test_create_rejects_radius_too_low(session) -> None:
    with pytest.raises(ValueError, match="cluster_radius_meters"):
        create_group(session, name="G1", cluster_radius_meters=5)


def test_create_rejects_radius_too_high(session) -> None:
    with pytest.raises(ValueError, match="cluster_radius_meters"):
        create_group(session, name="G1", cluster_radius_meters=2001)


def test_create_rejects_stale_too_low(session) -> None:
    with pytest.raises(ValueError, match="stale_after_minutes"):
        create_group(session, name="G1", stale_after_minutes=1)


def test_create_rejects_stale_too_high(session) -> None:
    with pytest.raises(ValueError, match="stale_after_minutes"):
        create_group(session, name="G1", stale_after_minutes=1441)


def test_create_rejects_quorum_zero(session) -> None:
    with pytest.raises(ValueError, match="quorum"):
        create_group(session, name="G1", quorum="0")


def test_create_rejects_quorum_non_numeric(session) -> None:
    with pytest.raises(ValueError, match="quorum"):
        create_group(session, name="G1", quorum="banana")


def test_create_rejects_quorum_above_20(session) -> None:
    with pytest.raises(ValueError, match="quorum"):
        create_group(session, name="G1", quorum="21")


def test_create_accepts_boundary_values(session) -> None:
    g = create_group(
        session,
        name="G1",
        quorum="20",
        cluster_radius_meters=2000,
        stale_after_minutes=1440,
    )
    assert g.quorum == "20"
    assert g.cluster_radius_meters == 2000
    assert g.stale_after_minutes == 1440


def test_create_accepts_named_quorum_values(session) -> None:
    for quorum in ("any", "majority", "all"):
        g = create_group(session, name=f"G-{quorum}", quorum=quorum)
        assert g.quorum == quorum


def test_update_rejects_invalid_quorum(session) -> None:
    group = create_group(session, name="G1")
    with pytest.raises(ValueError, match="quorum"):
        update_group(session, group.id, quorum="0")


def test_update_rejects_radius_out_of_range(session) -> None:
    group = create_group(session, name="G1")
    with pytest.raises(ValueError, match="cluster_radius_meters"):
        update_group(session, group.id, cluster_radius_meters=5)


def test_update_ignores_unset_fields(session) -> None:
    group = create_group(session, name="G1")
    updated = update_group(session, group.id, name="G2")
    assert updated.quorum == "majority"
    assert updated.name == "G2"


def test_quorum_zero_can_no_longer_reach_evaluate_quorum(session) -> None:
    """quorum_needed('0', N) is still 0 (the pure engine is unchanged) — the repo
    boundary is what must stop a stored quorum of '0' from ever reaching it."""
    assert quorum_needed("0", 3) == 0
    with pytest.raises(ValueError, match="quorum"):
        create_group(session, name="G1", quorum="0")
