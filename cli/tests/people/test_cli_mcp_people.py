"""`findplus people ...` and the people MCP tools (spec § 7.2)."""

from __future__ import annotations

import asyncio
import json

from click.testing import CliRunner

from findplus.cli.main import main
from findplus.db.session import session_scope
from findplus.honesty import ALERTS_LATENCY, PRESENCE_STALE
from findplus.ingest import upsert_device
from findplus.mcp.server import create_mcp_server
from findplus.state import track_devices
from tests.mcp.test_server import StubClient


def _seed():
    with session_scope() as s:
        for device_id, name in (
            ("zb", "Sam Bag"),
            ("zr", "Sam Shoes Red"),
            ("p", "Pixel 11 Pro"),
        ):
            upsert_device(s, device_id, name, provider="test-fake")
        track_devices(s, ["zb", "zr", "p"])
        s.commit()


def test_cli_suggest_accept_list_and_set_role(tmp_db):
    _seed()
    runner = CliRunner()
    out = runner.invoke(main, ["people", "suggest", "--json"])
    assert out.exit_code == 0, out.output
    preview = json.loads(out.output)
    key = preview["suggestions"][0]["key"]
    assert preview["unassigned"][0]["name"] == "Pixel 11 Pro"
    text = runner.invoke(main, ["people", "suggest"]).output
    assert 'Person "Sam": bag, shoes' in text and "Pixel 11 Pro: Whose is this?" in text
    done = runner.invoke(main, ["people", "accept", "--key", key])
    assert done.exit_code == 0 and "Saved person Sam" in done.output
    listed = json.loads(runner.invoke(main, ["people", "list", "--json"]).output)
    assert listed[0]["name"] == "Sam" and listed[0]["now"]["text"] == "No recent sightings."
    role = runner.invoke(main, ["people", "set-role", "zb", "jacket", "--weight", "0.3"])
    assert role.exit_code == 0 and "role jacket, weight 0.3" in role.output
    bad = runner.invoke(main, ["people", "set-role", "zb", "rocket"])
    assert bad.exit_code == 1 and "role must be one of" in bad.output


def test_cli_accept_needs_a_choice(tmp_db):
    out = CliRunner().invoke(main, ["people", "accept"])
    assert out.exit_code == 1


def test_mcp_people_tools_carry_the_caveats():
    client = StubClient(
        {
            ("GET", "/api/config"): {"notices": {"find_hub": "NOTICE"}},
            ("GET", "/api/people"): [{"id": 1, "name": "Sam", "trackers": []}],
            ("GET", "/api/people/1/now"): {"confidence": "likely", "text": "Likely at School"},
        }
    )
    mcp = create_mcp_server()
    mcp._daemon_client = client
    body = asyncio.run(mcp.call_tool("list_people", {})).structured_content
    assert body["data"][0]["now"]["text"] == "Likely at School"
    assert body["caveats"] == [PRESENCE_STALE, ALERTS_LATENCY]
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "get_people_suggestions" in names and "accept_people_suggestions" not in names
    writer = create_mcp_server(allow_writes=True)
    names = {t.name for t in asyncio.run(writer.list_tools())}
    assert {"accept_people_suggestions", "set_tracker_role"} <= names
