"""SELECT-count guards: list endpoints must not go per-device (E1-CF-P2-5).

`GET /api/devices`, `findplus devices --json` and the CLI device table each
showed an observation total per device, issued as one COUNT per device — N
trackers meant N+1 selects per page load. The fix batches them through
state.observation_counts(); these tests hold that line by counting the SQL a
request actually issues at two device-list sizes and asserting the counts do
not grow with the list.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from findplus.db.models import Device
from findplus.db.session import session_scope
from findplus.ingest import ingest_observations, upsert_device
from tests.conftest import make_observation


def _seed_devices(n: int) -> None:
    with session_scope() as session:
        for i in range(n):
            device_id = f"dev-{i}"
            upsert_device(session, device_id, f"Tag {i}", provider="query-count")
            ingest_observations(
                session,
                [
                    make_observation(
                        device_id=device_id, device_name=f"Tag {i}", lat=41.0 + i, minutes=10 * j
                    )
                    for j in range(3)
                ],
                fetched_at=datetime(2026, 9, 18, 13, 0, tzinfo=UTC),
            )


def _selects_while(callback) -> int:
    """Run callback, returning how many SELECT statements the engine issued.

    The engine is taken from a session_scope's bind, not from get_engine():
    get_engine is lru_cache'd and `get_engine()` / `get_engine(None)` are
    DIFFERENT cache keys (a call with no args is not the same key as a call
    with an explicit None), so session_scope() can hold a second Engine
    object for the same URL. Binding to the session's engine counts what
    actually executes either way.
    """
    counter = {"n": 0}

    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counter["n"] += 1

    with session_scope() as probe:
        engine = probe.bind
    event.listen(engine, "before_cursor_execute", _record)
    try:
        callback()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return counter["n"]


def test_devices_page_selects_do_not_grow_with_the_device_list(tmp_db) -> None:
    """2 and 8 devices must issue the SAME number of SELECTs per /api/devices."""
    from findplus.api import create_app

    counts = []
    for device_count in (2, 8):
        # Each size needs its own database, so the devices from the previous
        # one are cleared before seeding again.
        with session_scope() as session:
            for device in session.scalars(select(Device)):
                from findplus.db.models import LocationObservation

                session.query(LocationObservation).filter(
                    LocationObservation.device_id == device.device_id
                ).delete()
                session.delete(device)

        _seed_devices(device_count)
        client = TestClient(create_app())
        body: dict = {}

        def _get(client=client) -> None:
            nonlocal body
            body = client.get("/api/devices").json()

        selects = _selects_while(_get)
        assert len(body["devices"]) == device_count
        assert all(d["observation_count"] == 3 for d in body["devices"])
        counts.append(selects)

    assert counts[0] == counts[1], (
        f"SELECTs grew with the device list ({counts[0]} at 2 devices vs {counts[1]} at 8): "
        "the device page has regressed to per-device queries"
    )


def test_devices_json_uses_the_batched_counts(tmp_db) -> None:
    """`findplus devices --json` reads every total from one grouped query."""
    from findplus.cli.cmd_devices import _devices_as_json

    _seed_devices(4)

    rendered: list[str] = []

    def _render() -> None:
        with session_scope() as session:
            rows = list(session.scalars(select(Device).order_by(Device.name)))
            rendered.append(_devices_as_json(session, rows))

    _selects_while(_render)
    assert rendered[0].count('"observation_count": 3') == 4


def test_cli_table_uses_the_batched_counts(tmp_db) -> None:
    """The `findplus devices` table reads every total from one grouped query."""
    from findplus.cli._fmt import _print_device_table

    _seed_devices(3)

    def _print() -> None:
        with session_scope() as session:
            _print_device_table(session)

    # One SELECT for the device rows, one grouped count, nothing per device.
    assert _selects_while(_print) == 2
