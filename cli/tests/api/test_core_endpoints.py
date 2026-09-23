"""GET /api/version and /api/widget.

Split (E13 stage 2, size cap): /api/status, /api/config and the
`_widget_state` unit tests moved to test_core_endpoints_status.py.
"""

from __future__ import annotations

import importlib.metadata
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from findplus import honesty


def test_version(client: TestClient) -> None:
    body = client.get("/api/version").json()
    assert set(body) >= {"version", "python", "platform", "providers", "apple_extra_installed"}
    assert body["version"] == importlib.metadata.version("findplus")


def test_widget_unlocked(client: TestClient) -> None:
    body = client.get("/api/widget").json()
    for key in (
        "state",
        "version",
        "last_poll_at",
        "next_poll_at",
        "tracked_count",
        "stale_after_minutes",
        "devices",
        "groups",
        "places",
        "show_map",
        "notice",
    ):
        assert key in body, key
    # The verbatim honesty.md sentence, never the old paraphrase.
    assert body["notice"] == honesty.ALERTS_LATENCY
    assert body["stale_after_minutes"] == 90  # D18
    assert body["state"] in {"ok", "stale", "error"}


def test_widget_hides_the_place_of_a_stale_device(session, monkeypatch) -> None:
    """honesty.md presence_stale: a tag with no recent fix is not at a place.

    The last known place must not be served as if the tag were still there, so
    a device past `stale_after_minutes` comes back with `place: null`.
    """
    from findplus.api import _widget
    from findplus.ingest import ingest_observations
    from findplus.state import track_all
    from tests.conftest import make_observation

    observed = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    ingest_observations(session, [make_observation(observed_at=observed)])
    track_all(session)
    monkeypatch.setattr(_widget, "_place_by_device", lambda s, now, mins: {"TAG-001": "Home"})

    fresh = _widget._widget_devices(session, observed + timedelta(minutes=90), 90)
    assert fresh[0]["age_minutes"] == 90
    assert fresh[0]["place"] == "Home"

    stale = _widget._widget_devices(session, observed + timedelta(minutes=91), 90)
    assert stale[0]["age_minutes"] == 91
    assert stale[0]["place"] is None
    # Everything else still reports honestly: the tag is known, just not placed.
    assert stale[0]["device_id"] == "TAG-001"


def _home_with_tag_001_inside(session, at):
    """A "Home" place with TAG-001 already marked `inside` it, since `at`."""
    from findplus.db.models import Place, PlaceState

    place = Place(
        name="Home",
        latitude_e7=411234560,
        longitude_e7=-801234560,
        radius_meters=100,
        color="#2f80ed",
        enter_confirmations=1,
        exit_confirmations=2,
        created_at=at,
        updated_at=at,
    )
    session.add(place)
    session.flush()
    session.add(
        PlaceState(
            place_id=place.id,
            device_id="TAG-001",
            state="inside",
            since_observed_at=at,
            streak=1,
            streak_side="inside",
            last_observation_id=None,
            updated_at=at,
        )
    )
    session.flush()


def test_widget_device_row_and_places_array_agree_on_a_75_minute_fix(session) -> None:
    """UAT2 N4: one staleness cutoff everywhere, not two.

    `_place_by_device` used to call `current_presence()` with no threshold,
    which fell back to `Settings.presence_window_minutes` (60) while the
    places array used the widget's own `WIDGET_STALE_AFTER_MINUTES` (90,
    D18). A 75-minute-old fix is stale at 60 but fresh at 90, so a device row
    read `place: null` while the very same payload's `places` array still
    counted that device as inside -- and a full group's place badge with it.
    """
    from findplus.api._widget import WIDGET_STALE_AFTER_MINUTES, _place_by_device, _widget_places
    from findplus.ingest import ingest_observations
    from findplus.state import track_all
    from tests.conftest import make_observation

    now = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)
    observed = now - timedelta(minutes=75)
    ingest_observations(session, [make_observation(observed_at=observed)])
    track_all(session)
    _home_with_tag_001_inside(session, observed)

    device_places = _place_by_device(session, now, WIDGET_STALE_AFTER_MINUTES)
    place_rows = _widget_places(session, now, WIDGET_STALE_AFTER_MINUTES)

    assert device_places.get("TAG-001") == "Home"
    assert place_rows[0]["device_ids"] == ["TAG-001"]


def _widget_group(session, *, name: str):
    from findplus.db.models import Group

    now = datetime.now(UTC)
    group = Group(
        name=name,
        color="#27ae60",
        quorum="majority",
        cluster_radius_meters=150,
        stale_after_minutes=90,
        created_at=now,
    )
    session.add(group)
    session.flush()
    return group


def _widget_member(session, group, device_id: str, *, minutes_ago: float | None) -> None:
    """Add `device_id` to `group`; a fix `minutes_ago`, or none at all when `None`."""
    from findplus.db.models import Device, DeviceGroup, LocationObservation

    now = datetime.now(UTC)
    session.add(Device(device_id=device_id, name=device_id, first_seen_at=now, last_seen_at=now))
    session.flush()
    session.add(DeviceGroup(device_id=device_id, group_id=group.id))
    if minutes_ago is not None:
        session.add(
            LocationObservation(
                device_id=device_id,
                device_name=device_id,
                latitude_e7=411000000,
                longitude_e7=-806400000,
                observed_at=now - timedelta(minutes=minutes_ago),
                first_fetched_at=now,
                last_fetched_at=now,
            )
        )
    session.flush()


def test_widget_group_note_uses_label_over_raw_provider_name(session) -> None:
    """UAT2 N2 end-to-end: `/api/widget`'s group rows read the same
    label-first note groups/repo.py now builds, not a raw provider name."""
    from findplus.api._widget import _group_rows
    from findplus.db.models import Device

    group = _widget_group(session, name="family")
    _widget_member(session, group, "dev1", minutes_ago=2)
    session.get(Device, "dev1").label = "Omar's backpack"
    session.flush()

    rows = _group_rows(session)
    assert rows[0]["note"] == "Only Omar's backpack is reporting (2 min ago)."


def test_widget_group_verdict_all_together(session) -> None:
    """Both members reporting recently, at the same spot -> `all_together`.

    `GET /api/widget` must compute this from groups.repo.build_presence(),
    the same engine GET /api/groups/{id}/presence uses — not a hardcoded
    placeholder (widget.md § LargeView renders `verdict, note`).
    """
    from findplus.api._widget import _group_rows

    group = _widget_group(session, name="family")
    _widget_member(session, group, "dev1", minutes_ago=2)
    _widget_member(session, group, "dev2", minutes_ago=2)

    rows = _group_rows(session)
    assert len(rows) == 1
    assert rows[0]["id"] == group.id
    assert rows[0]["name"] == "family"
    assert rows[0]["verdict"] == "all_together"
    assert "together" in rows[0]["note"]


def test_widget_group_verdict_partial(session) -> None:
    """One member reporting, the other with no fix at all -> `partial`."""
    from findplus.api._widget import _group_rows

    group = _widget_group(session, name="split")
    _widget_member(session, group, "dev1", minutes_ago=2)
    _widget_member(session, group, "dev2", minutes_ago=None)

    rows = _group_rows(session)
    assert rows[0]["verdict"] == "partial"
    assert "dev1" in rows[0]["note"]


def test_widget_group_verdict_unknown(session) -> None:
    """No member has ever reported -> `unknown`, never a made-up placeholder."""
    from findplus.api._widget import _group_rows

    group = _widget_group(session, name="silent")
    _widget_member(session, group, "dev1", minutes_ago=None)

    rows = _group_rows(session)
    assert rows[0]["verdict"] == "unknown"
    # honesty round 3 F7: the note names the members now, not a row id.
    assert "has not reported" in rows[0]["note"]
    assert "group " not in rows[0]["note"]


def test_widget_locked(locked_client: TestClient) -> None:
    assert locked_client.get("/api/widget").status_code == 401


def test_widget_show_map_falls_back_to_config_env(tmp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """No settings-table row: `FINDPLUS_WIDGET_SHOW_MAP=1` (the config field) wins."""
    from findplus.api import create_app

    monkeypatch.setenv("FINDPLUS_WIDGET_SHOW_MAP", "1")
    body = TestClient(create_app()).get("/api/widget").json()
    assert body["show_map"] is True


def test_widget_show_map_table_row_wins_over_config_env(
    tmp_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A settings-table row always wins, even when the env disagrees."""
    from findplus.api import create_app
    from findplus.db.session import session_scope
    from findplus.state import set_setting

    monkeypatch.setenv("FINDPLUS_WIDGET_SHOW_MAP", "1")
    with session_scope() as session:
        set_setting(session, "widget.show_map", "0")
    body = TestClient(create_app()).get("/api/widget").json()
    assert body["show_map"] is False


def test_widget_device_rows_carry_icon_and_color(client: TestClient) -> None:
    from findplus.db.models import Device
    from findplus.db.session import session_scope

    with session_scope() as session:
        device = session.get(Device, "TAG-001")
        device.icon, device.color = "lucide:key", "#4f8cf7"
        device.label = "Mom's Keys"

    row = client.get("/api/widget").json()["devices"][0]
    assert row["label"] == "Mom's Keys"
    assert row["icon"] == "lucide:key"
    assert row["color"] == "#4f8cf7"


def test_widget_group_rows_carry_icon(client: TestClient) -> None:
    from findplus.db.session import session_scope
    from findplus.groups.repo import create_group

    with session_scope() as session:
        create_group(session, name="Family", icon="lucide:dog")

    assert client.get("/api/widget").json()["groups"][0]["icon"] == "lucide:dog"
