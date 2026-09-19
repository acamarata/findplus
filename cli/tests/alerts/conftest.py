"""Shared fixtures for the alerts dispatch test suite (test_dispatch*.py).

Purpose    : `settings_enabled` and `rule_row` were previously redefined
             identically in test_dispatch.py and test_dispatch_cooldown.py;
             pytest auto-discovers fixtures from a directory's conftest.py,
             so this is the one definition every sibling test module shares.
Inputs     : `rule_row` depends on the tmp_db-backed `session` fixture from
             cli/tests/conftest.py.
Outputs    : n/a (pytest fixtures).
Constraints: test-only; never imported by cli/src.
"""

from __future__ import annotations

import types

import pytest

from findplus.db.models_alerts import AlertRule

from ._helpers import NOW, _seed_place_and_device


@pytest.fixture
def settings_enabled():
    return types.SimpleNamespace(alerts_enabled=True)


@pytest.fixture
def rule_row(tmp_db, session):
    _seed_place_and_device(session)
    rule = AlertRule(
        name="r1",
        place_id=1,
        device_id="dev1",
        on_enter=True,
        on_exit=True,
        channel="telegram",
        cooldown_minutes=30,
        enabled=True,
        also_notify_members=False,
        created_at=NOW,
    )
    session.add(rule)
    session.commit()
    return rule
