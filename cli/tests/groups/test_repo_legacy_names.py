"""update_group: name rules apply only to a name that changes (legacy rows stay editable)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from findplus.db.models import Group
from findplus.groups.repo import update_group

NOW = datetime.now(UTC)


def _seed(session, name: str) -> Group:
    group = Group(
        name=name,
        color="#27ae60",
        quorum="any",
        cluster_radius_meters=150,
        stale_after_minutes=90,
        created_at=NOW,
    )
    session.add(group)
    session.flush()
    return group


def test_unchanged_case_variant_legacy_name_can_be_edited(session) -> None:
    _seed(session, "Kids")
    twin = _seed(session, "kids")
    updated = update_group(session, twin.id, name="kids", color="#abcdef")
    assert updated.name == "kids"
    assert updated.color == "#abcdef"


def test_unchanged_overlong_legacy_name_can_be_edited(session) -> None:
    legacy = _seed(session, "x" * 70)
    updated = update_group(session, legacy.id, name="x" * 70, quorum="all")
    assert updated.name == "x" * 70
    assert updated.quorum == "all"


def test_a_real_rename_is_still_validated(session) -> None:
    _seed(session, "Kids")
    other = _seed(session, "Family")
    with pytest.raises(ValueError, match="already exists"):
        update_group(session, other.id, name="KIDS")
    with pytest.raises(ValueError, match="1-64"):
        update_group(session, other.id, name="y" * 65)
