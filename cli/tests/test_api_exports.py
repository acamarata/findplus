"""Local API contract: the export formats and safe deletion.

Split out of test_api.py (PRI rule 7, <=300 lines/file); both files share the
seeded client fixtures in _api_client.py.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from findplus.db.session import session_scope
from findplus.exporters import csv_table


def test_csv_export_downloads_with_a_filename(client: TestClient) -> None:
    res = client.get("/api/export?fmt=csv&day=2026-09-18&timezone=UTC")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(csv_table(res.text))))
    assert len(rows) == 3


def test_gpx_export_is_valid_xml_with_trackpoints(client: TestClient) -> None:
    res = client.get("/api/export?fmt=gpx&day=2026-09-18&timezone=UTC")
    root = ElementTree.fromstring(res.text)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    assert len(root.findall(".//g:trkpt", ns)) == 3


@pytest.mark.parametrize("fmt", ["csv", "json", "gpx", "kml"])
def test_all_export_formats_respond(client: TestClient, fmt: str) -> None:
    assert client.get(f"/api/export?fmt={fmt}&day=2026-09-18&timezone=UTC").status_code == 200


def test_export_all_history_works(client: TestClient) -> None:
    rows = list(csv.DictReader(io.StringIO(csv_table(client.get("/api/export?fmt=csv").text))))
    assert len(rows) == 3


def test_export_rejects_unknown_formats(client: TestClient) -> None:
    assert client.get("/api/export?fmt=shapefile").status_code == 422


def test_delete_before_is_a_dry_run_without_confirmation(client: TestClient) -> None:
    res = client.post("/api/history/delete-before", json={"before": "2026-09-19"})
    body = res.json()
    assert body["deleted"] == 0
    assert body["would_delete"] == 3
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 3


def test_delete_before_removes_only_older_rows_when_confirmed(client: TestClient) -> None:
    res = client.post("/api/history/delete-before", json={"before": "2026-09-19", "confirm": True})
    assert res.json()["deleted"] == 3
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 0


def test_delete_before_keeps_newer_history(client: TestClient) -> None:
    res = client.post("/api/history/delete-before", json={"before": "2026-09-18", "confirm": True})
    assert res.json()["deleted"] == 0
    assert client.get("/api/status?timezone=UTC").json()["observations_total"] == 3


def test_delete_before_cascades_place_events(client: TestClient) -> None:
    """A place_event anchored to a pruned observation is deleted, not orphaned."""
    from sqlalchemy import func, select

    from findplus.db.models import LocationObservation, Place, PlaceEvent

    with session_scope() as session:
        obs = session.scalars(
            select(LocationObservation).order_by(LocationObservation.observed_at)
        ).first()
        place = Place(
            name="P1",
            latitude_e7=411000000,
            longitude_e7=-806400000,
            radius_meters=100,
            color="#2f80ed",
            enter_confirmations=1,
            exit_confirmations=2,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(place)
        session.flush()
        session.add(
            PlaceEvent(
                place_id=place.id,
                device_id="TAG-001",
                event_type="ENTER",
                observed_at=obs.observed_at,
                fetched_at=obs.last_fetched_at,
                observation_id=obs.id,
                confidence="high",
                distance_meters=42.0,
            )
        )
        place_id = place.id

    res = client.post("/api/history/delete-before", json={"before": "2026-09-19", "confirm": True})
    assert res.status_code == 200
    assert res.json()["deleted"] == 3

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(PlaceEvent)) == 0
        assert session.get(Place, place_id) is not None
