"""Full-fidelity JSONL: export, import into an empty database, round trip, refusals."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import delete, func, select

from findplus.db import models as m
from findplus.db.models_alerts import AlertRule
from findplus.db.models_people import ObservationQuality
from findplus.db.portable import export_lines
from findplus.db.portable_import import PortableImportError, import_lines, is_empty
from findplus.state import set_setting
from tests.durability._seed import seed_everything


def _wipe(session) -> None:
    for model in (
        AlertRule,
        m.PlaceState,
        m.PlaceEvent,
        m.GroupPlaceEvent,
        ObservationQuality,
        m.DeviceGroup,
        m.Group,
        m.Place,
        m.LocationObservation,
        m.Device,
    ):
        session.execute(delete(model))
    session.flush()


def _atomic(session, lines):
    """import_lines inside a savepoint, as the CLI's transaction does: a failure leaves nothing."""
    with session.begin_nested():
        return import_lines(session, lines)


def _body(lines: list[str]) -> list[str]:
    """Export lines without the header (its exported_at differs run to run)."""
    return lines[1:]


def test_header_describes_the_file(session) -> None:
    seed_everything(session)
    head = json.loads(next(iter(export_lines(session))))
    assert head["t"] == "header" and head["format"] == "findplus-export" and head["version"] == 1
    assert head["counts"] == {
        "device": 3,
        "place": 2,
        "group": 2,
        "observation": 12,
        "alert_rule": 3,
    }
    assert head["schema_revision"]


def test_every_line_is_json_and_kinds_are_ordered(session) -> None:
    seed_everything(session)
    kinds = [json.loads(line)["t"] for line in export_lines(session)]
    order = ["header", "device", "place", "group", "observation", "alert_rule"]
    assert [k for i, k in enumerate(kinds) if i == 0 or k != kinds[i - 1]] == order


def test_round_trip_is_lossless(session) -> None:
    seed_everything(session)
    first = list(export_lines(session))
    _wipe(session)
    assert is_empty(session)
    result = import_lines(session, first)
    session.flush()
    assert result.counts == {
        "device": 3,
        "place": 2,
        "group": 2,
        "observation": 12,
        "alert_rule": 3,
    }
    assert _body(list(export_lines(session))) == _body(first)


def test_kinds_roles_members_and_rule_fields_survive(session) -> None:
    seed_everything(session)
    lines = list(export_lines(session))
    _wipe(session)
    import_lines(session, lines)
    session.flush()
    shoes = session.get(m.Device, "d-shoes")
    assert (shoes.role, shoes.carry_weight, shoes.label) == ("shoes", 0.9, "Red shoes")
    kinds = {g.name: g.kind for g in session.scalars(select(m.Group))}
    assert kinds == {"Zaid": "person", "Family": "set"}
    members = {
        g.name: sorted(
            d
            for (d,) in session.execute(
                select(m.DeviceGroup.device_id).where(m.DeviceGroup.group_id == g.id)
            )
        )
        for g in session.scalars(select(m.Group))
    }
    assert members == {"Zaid": ["d-bag", "d-shoes"], "Family": ["d-phone", "d-shoes"]}
    assert {p.name: p.kind for p in session.scalars(select(m.Place))} == {
        "Home": "home",
        "School": "school",
    }
    rules = {r.name: r for r in session.scalars(select(AlertRule))}
    assert rules["Shoes at home"].telegram_targets == "111,-100222"
    assert (
        rules["Shoes at home"].place_id is not None
        and rules["Shoes at home"].device_id == "d-shoes"
    )
    assert rules["Family arrives"].group_id is not None and rules["Family arrives"].on_exit is False
    assert rules["Everyone"].all_people is True and rules["Everyone"].group_id is None


def test_the_export_holds_no_secrets(session) -> None:
    seed_everything(session)
    set_setting(session, "lock_pin_hash", "HASH-SHOULD-NOT-LEAK")
    set_setting(session, "lock_pin_salt", "SALT-SHOULD-NOT-LEAK")
    text = "\n".join(export_lines(session))
    assert "SHOULD-NOT-LEAK" not in text
    for word in ("secrets", "token", "pin_hash"):
        assert word not in text.lower()


def test_import_refuses_a_database_that_has_data(session) -> None:
    seed_everything(session)
    lines = list(export_lines(session))
    with pytest.raises(PortableImportError, match="already has data"):
        import_lines(session, lines)


def test_import_refuses_foreign_and_newer_files(session) -> None:
    with pytest.raises(PortableImportError, match="not a Find\\+ export"):
        import_lines(session, ['{"t": "header", "format": "something-else"}'])
    newer = json.dumps({"t": "header", "format": "findplus-export", "version": 99})
    with pytest.raises(PortableImportError, match="newer Find\\+"):
        import_lines(session, [newer])
    with pytest.raises(PortableImportError, match="newer schema"):
        header = {
            "t": "header",
            "format": "findplus-export",
            "version": 1,
            "schema_revision": "9999",
        }
        import_lines(session, [json.dumps(header)])


def test_import_refuses_files_without_a_header_or_with_bad_lines(session) -> None:
    with pytest.raises(PortableImportError, match="header"):
        _atomic(session, ['{"t": "device"}'])
    with pytest.raises(PortableImportError, match="empty"):
        _atomic(session, ["", "  "])
    seed_everything(session)
    lines = list(export_lines(session))
    _wipe(session)
    with pytest.raises(PortableImportError, match="Line 3 is not valid JSON"):
        _atomic(session, [lines[0], lines[1], "{broken"])
    bad_rule = json.dumps(
        {"t": "alert_rule", "name": "x", "place": "Nowhere", "channels": "native"}
    )
    with pytest.raises(PortableImportError, match="Nowhere"):
        _atomic(session, [*lines[:4], bad_rule])
    assert is_empty(session)  # nothing from the failed attempts stayed


def test_unknown_fields_are_ignored_and_missing_ones_default(session) -> None:
    header = json.dumps({"t": "header", "format": "findplus-export", "version": 1})
    place = json.dumps(
        {
            "t": "place",
            "name": "Old",
            "latitude_e7": 1,
            "longitude_e7": 2,
            "radius_meters": 100,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "from_the_future": True,
        }
    )
    import_lines(session, [header, place])
    got = session.scalar(select(m.Place))
    assert got.kind == "other" and got.enter_confirmations == 1  # column defaults


def test_an_empty_database_exports_just_a_header(session) -> None:
    lines = list(export_lines(session))
    assert len(lines) == 1 and session.scalar(select(func.count()).select_from(m.Device)) == 0
