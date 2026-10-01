"""`findplus trips` and the MCP `get_trips` tool mirror the API."""

from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner

from findplus import honesty
from findplus.cli.main import main
from findplus.mcp.server import create_mcp_server
from tests.mcp.test_server import StubClient
from tests.trips._db import DEVICE, seed_school_day


@pytest.fixture
def seeded(tmp_db) -> None:
    seed_school_day()


def _run(*args: str):
    return CliRunner().invoke(main, ["trips", "--timezone", "UTC", *args])


def test_cli_table_lists_stays_trips_and_the_honesty_line(seeded) -> None:
    result = _run("--date", "2026-09-18")  # one tracked device: no --device-id needed
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Home" in out and "School" in out and "Stays" in out and "Trips" in out
    assert "Home -> School" in out and "~" in out  # approximate distance marker
    assert honesty.TRIPS_APPROXIMATE in out


def test_cli_json_is_the_api_payload(seeded) -> None:
    result = _run("--device-id", DEVICE, "--date", "2026-09-18", "--json")
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["label"] == honesty.TRIPS_APPROXIMATE
    assert [s["label"] for s in body["stays"]] == ["Home", "School", "Home"]
    assert len(body["trips"]) == 2


def test_cli_empty_day_and_errors(seeded) -> None:
    empty = _run("--date", "2026-01-01")
    assert empty.exit_code == 0 and "No sightings in this range." in empty.output
    assert _run("--device-id", "nope").exit_code != 0
    assert _run("--date", "yesterday").exit_code != 0


def test_mcp_get_trips_mirrors_the_api_with_caveat() -> None:
    payload = {"stays": [], "trips": [], "gaps": [], "label": honesty.TRIPS_APPROXIMATE}
    client = StubClient(
        {
            ("GET", "/api/trips"): payload,
            ("GET", "/api/config"): {"notices": {"find_hub": "NOTICE"}},
        }
    )
    mcp = create_mcp_server()
    mcp._daemon_client = client
    out = asyncio.run(mcp.call_tool("get_trips", {"device_id": "TAG-1", "date": "2026-09-18"}))
    data = out.structured_content
    assert data["label"] == honesty.TRIPS_APPROXIMATE
    assert data["caveats"] == [honesty.TRIPS_APPROXIMATE]
    assert "get_trips" in {t.name for t in asyncio.run(mcp.list_tools())}
