"""Export formatting for CSV, JSON, GPX and KML.

Split (E13 stage 2, size cap): label and unknown-accuracy variants moved to
test_exports_labels.py; this file keeps the base format + dispatcher tests.
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
from findplus.exporters import (
    CSV_COLUMNS,
    DISCLAIMER,
    csv_table,
    export,
    to_csv,
    to_gpx,
    to_json,
    to_kml,
)
from findplus.ingest import ingest_observations
from tests.conftest import make_observation

EASTERN = ZoneInfo("America/New_York")


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


# ------------------------------------------------------------------- CSV
def _parsed(body: str) -> list[dict[str, str]]:
    """Rows of a CSV export, past its leading `#` disclaimer comment."""
    return list(csv.DictReader(io.StringIO(csv_table(body))))


def test_csv_has_a_header_and_one_row_per_observation(rows) -> None:
    parsed = _parsed(to_csv(rows, EASTERN))
    assert len(parsed) == 3
    assert parsed[0]["device_name"] == "Moto Tag 2"


def test_csv_separates_observed_and_fetched_columns(rows) -> None:
    parsed = _parsed(to_csv(rows, EASTERN))
    first = parsed[0]
    assert first["observed_at_utc"] == "2026-09-18T12:00:00+00:00"
    assert first["observed_at_local"].startswith("2026-09-18T08:00:00")
    assert first["fetched_at_utc"] == "2026-09-18T12:47:00+00:00"


def test_csv_first_row_has_no_previous_distance(rows) -> None:
    parsed = _parsed(to_csv(rows, EASTERN))
    assert parsed[0]["approx_meters_from_previous"] == ""
    assert float(parsed[1]["approx_meters_from_previous"]) > 0


def test_csv_distance_column_says_it_is_approximate(rows) -> None:
    """Invariant 7: the export must not present a straight-line gap between
    two observed fixes as an exact distance."""
    header = csv_table(to_csv(rows, EASTERN)).splitlines()[0]
    assert "approx_meters_from_previous" in header
    assert ",meters_from_previous" not in header


def test_csv_opens_with_the_disclaimer_as_a_comment(rows) -> None:
    body = to_csv(rows, EASTERN)
    first_line = body.splitlines()[0]
    assert first_line == f"# {DISCLAIMER}"
    assert csv_table(body).splitlines()[0].startswith("observation_id,")


def test_disclaimer_names_both_networks_not_only_google() -> None:
    """A Find My observation exported under a Google-only disclaimer would
    misdescribe where the data came from."""
    assert "Find Hub and Find My networks" in DISCLAIMER
    assert "Google" not in DISCLAIMER
    # Every format carries the same sentence.
    assert DISCLAIMER in to_json([], EASTERN)
    assert DISCLAIMER in to_gpx([], EASTERN)
    assert DISCLAIMER in to_kml([], EASTERN)


def test_default_export_name_is_not_the_old_bike_wording() -> None:
    assert "<name>Find+ history</name>" in to_gpx([], EASTERN)
    assert "<name>Find+ history</name>" in to_kml([], EASTERN)
    assert "Bike" not in to_gpx([], EASTERN)
    assert "Bike" not in to_kml([], EASTERN)


def test_csv_preserves_seven_decimal_places(rows) -> None:
    parsed = _parsed(to_csv(rows, EASTERN))
    assert parsed[0]["latitude"] == "41.1000000"


def test_csv_of_empty_history_is_a_comment_and_a_header(session) -> None:
    body = to_csv([], EASTERN)
    assert body.splitlines() == [f"# {DISCLAIMER}", ",".join(CSV_COLUMNS)]


# ------------------------------------------------------------------ JSON
def test_json_is_valid_and_complete(rows) -> None:
    payload = json.loads(to_json(rows, EASTERN))
    assert payload["count"] == 3
    assert len(payload["observations"]) == 3
    assert "not the route actually travelled" in payload["disclaimer"]


def test_json_coordinates_are_numbers(rows) -> None:
    obs = json.loads(to_json(rows, EASTERN))["observations"][0]
    assert isinstance(obs["latitude"], float)
    assert obs["latitude"] == pytest.approx(41.1)


# ------------------------------------------------------------------- GPX
def test_gpx_is_well_formed_xml(rows) -> None:
    ElementTree.fromstring(to_gpx(rows, EASTERN))


def test_gpx_has_one_timestamped_trackpoint_per_observation(rows) -> None:
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    root = ElementTree.fromstring(to_gpx(rows, EASTERN))
    points = root.findall(".//g:trkpt", ns)
    assert len(points) == 3
    for point in points:
        assert point.find("g:time", ns) is not None


def test_gpx_times_are_observed_times_in_utc_zulu(rows) -> None:
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    root = ElementTree.fromstring(to_gpx(rows, EASTERN))
    first = root.find(".//g:trkpt/g:time", ns).text
    assert first == "2026-09-18T12:00:00Z", "GPX must carry observed time, not fetch time"


def test_gpx_coordinates_match(rows) -> None:
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    root = ElementTree.fromstring(to_gpx(rows, EASTERN))
    point = root.find(".//g:trkpt", ns)
    assert float(point.get("lat")) == pytest.approx(41.1)
    assert float(point.get("lon")) == pytest.approx(-80.1)


def test_gpx_of_empty_history_is_still_valid(session) -> None:
    ElementTree.fromstring(to_gpx([], EASTERN))


# ------------------------------------------------------------------- KML
def test_kml_is_well_formed_with_placemarks_and_a_path(rows) -> None:
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    root = ElementTree.fromstring(to_kml(rows, EASTERN))
    placemarks = root.findall(".//k:Placemark", ns)
    assert len(placemarks) == 4  # 3 points + 1 path
    assert root.find(".//k:LineString", ns) is not None


def test_kml_escapes_special_characters(session) -> None:
    ingest_observations(session, [make_observation(device_name="Bike <&> Tag")])
    row = session.scalar(select(LocationObservation))
    body = to_kml([row], EASTERN, doc_name="A & B <test>")
    ElementTree.fromstring(body)  # would raise if unescaped
    assert "&amp;" in body


# ------------------------------------------------------------ dispatcher
@pytest.mark.parametrize("fmt", ["csv", "json", "gpx", "kml"])
def test_dispatcher_supports_every_documented_format(rows, fmt: str) -> None:
    assert export(fmt, rows, EASTERN)


def test_dispatcher_rejects_unknown_formats(rows) -> None:
    with pytest.raises(ValueError, match="Unsupported export format"):
        export("shapefile", rows, EASTERN)
