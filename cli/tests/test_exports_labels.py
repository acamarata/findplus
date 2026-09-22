"""Export label and unknown-accuracy variants, split from test_exports.py
(E13 stage 2, size cap): device-label columns/fields across every format
(P2-E2), and the CF-P2-6 "never invent an accuracy figure" behaviour for
Apple Find My rows with no measured accuracy.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from findplus.db.models import LocationObservation
from findplus.exporters import CSV_COLUMNS, csv_table, export, to_csv, to_gpx, to_json, to_kml
from findplus.ingest import ingest_observations
from tests.conftest import make_observation

EASTERN = ZoneInfo("America/New_York")


def _parsed(body: str) -> list[dict[str, str]]:
    """Rows of a CSV export, past its leading `#` disclaimer comment."""
    return list(csv.DictReader(io.StringIO(csv_table(body))))


@pytest.fixture
def rows(session):
    ingest_observations(
        session,
        [
            make_observation(minutes=0, lat=41.100000, lon=-80.100000),
            make_observation(minutes=17, lat=41.110000, lon=-80.110000),
            make_observation(minutes=46, lat=41.130000, lon=-80.130000),
        ],
        fetched_at=datetime(2026, 9, 18, 12, 47, tzinfo=UTC),
    )
    return list(
        session.scalars(select(LocationObservation).order_by(LocationObservation.observed_at))
    )


# ------------------------------------------------------ device labels (P2-E2)
def test_csv_label_column_present_when_devices_have_labels(rows) -> None:
    body = to_csv(rows, EASTERN, labels={"TAG-001": "Mom's Keys"})
    table = list(csv.DictReader(io.StringIO(body.split("\n", 1)[1])))
    assert table[0]["label"] == "Mom's Keys"


def test_csv_label_column_empty_when_absent(rows) -> None:
    body = to_csv(rows, EASTERN)
    table = list(csv.DictReader(io.StringIO(body.split("\n", 1)[1])))
    assert CSV_COLUMNS[CSV_COLUMNS.index("device_name") + 1] == "label"
    assert table[0]["label"] == ""


def test_json_label_field_is_null_when_absent(rows) -> None:
    payload = json.loads(to_json(rows, EASTERN))
    assert payload["observations"][0]["label"] is None


def test_json_label_field_present(rows) -> None:
    payload = json.loads(to_json(rows, EASTERN, labels={"TAG-001": "Mom's Keys"}))
    assert payload["observations"][0]["label"] == "Mom's Keys"


def test_export_forwards_labels_to_every_format(rows) -> None:
    """`export()` is the only entry point the route and the CLI call."""
    labels = {"TAG-001": "Mom's Keys"}
    assert "Mom's Keys" in export("csv", rows, EASTERN, labels=labels)
    assert "Mom's Keys" in export("json", rows, EASTERN, labels=labels)
    for fmt in ("gpx", "kml"):
        assert "Mom's Keys" in export(fmt, rows, EASTERN, name="Find+ history", labels=labels)


def test_gpx_track_points_use_the_device_label(rows) -> None:
    """R-P2-27-1: the GPX `<trkpt><name>`/`<desc>` must carry the device label."""
    body = to_gpx(rows, EASTERN, labels={"TAG-001": "Mom's Keys"})
    root = ElementTree.fromstring(body)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    trkpts = root.findall(".//g:trkpt", ns)
    assert trkpts, "fixture must produce at least one track point"
    for pt in trkpts:
        assert pt.find("g:name", ns).text == "Mom's Keys"
        assert pt.find("g:desc", ns).text == "Mom's Keys"


def test_gpx_track_points_fall_back_to_device_id_without_a_label(rows) -> None:
    body = to_gpx(rows, EASTERN)
    root = ElementTree.fromstring(body)
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    trkpts = root.findall(".//g:trkpt", ns)
    assert trkpts
    for pt in trkpts:
        assert pt.find("g:name", ns).text == "TAG-001"


def test_kml_placemarks_use_the_device_label(rows) -> None:
    """R-P2-27-1: each observation Placemark's `<name>` must carry the device label."""
    body = to_kml(rows, EASTERN, labels={"TAG-001": "Mom's Keys"})
    root = ElementTree.fromstring(body)
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    names = [
        pm.find("k:name", ns).text
        for pm in root.findall(".//k:Placemark", ns)
        if pm.find("k:name", ns).text != "Observed path"
    ]
    assert names, "fixture must produce at least one observation placemark"
    assert all(name.startswith("Mom's Keys (") for name in names)


def test_kml_placemarks_fall_back_to_device_id_without_a_label(rows) -> None:
    body = to_kml(rows, EASTERN)
    root = ElementTree.fromstring(body)
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    names = [
        pm.find("k:name", ns).text
        for pm in root.findall(".//k:Placemark", ns)
        if pm.find("k:name", ns).text != "Observed path"
    ]
    assert names
    assert all(name.startswith("TAG-001 (") for name in names)


# ------------------------------------------------- unknown accuracy (CF-P2-6)
@pytest.fixture
def apple_row(session) -> LocationObservation:
    """One Apple Find My observation with no accuracy: `accuracy=None` is what
    the provider always writes (CF-P2-6) -- never an invented metres figure.
    """
    ingest_observations(
        session,
        [make_observation(device_id="apple:abc", source="apple-find-my", accuracy=None)],
    )
    return session.scalar(select(LocationObservation))


def test_csv_accuracy_column_is_empty_not_zero(apple_row) -> None:
    parsed = _parsed(to_csv([apple_row], EASTERN))
    assert parsed[0]["accuracy_meters"] == ""


def test_json_accuracy_field_is_null_not_a_guessed_number(apple_row) -> None:
    payload = json.loads(to_json([apple_row], EASTERN))
    assert payload["observations"][0]["accuracy_meters"] is None


def test_gpx_omits_hdop_when_accuracy_is_unknown(apple_row) -> None:
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    root = ElementTree.fromstring(to_gpx([apple_row], EASTERN))
    point = root.find(".//g:trkpt", ns)
    assert point.find("g:hdop", ns) is None


def test_kml_omits_the_accuracy_detail_when_unknown(apple_row) -> None:
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    root = ElementTree.fromstring(to_kml([apple_row], EASTERN))
    descriptions = [pm.find("k:description", ns).text for pm in root.findall(".//k:Placemark", ns)]
    assert not any(d and "accuracy" in d for d in descriptions)
