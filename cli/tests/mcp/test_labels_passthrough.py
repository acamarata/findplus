"""An MCP client sees the same label, icon and colour a human sees.

Purpose : `list_devices`/`list_groups` proxy `GET /api/devices` and
          `GET /api/groups` verbatim, so the P2 label fields need no MCP schema
          change. That is an assumption until something checks it; this is the
          check.
Constraints: StubClient stands in for the HTTP layer (invariant rule 3).
"""

from __future__ import annotations

import asyncio

from findplus.mcp.server import create_mcp_server
from tests.mcp.test_server import StubClient

_CONFIG = {("GET", "/api/config"): {"notices": {"find_hub": "NOTICE"}}}


def _server(responses: dict):
    mcp = create_mcp_server()
    mcp._daemon_client = StubClient({**_CONFIG, **responses})
    return mcp


def test_list_devices_passes_through_label_icon_color() -> None:
    mcp = _server(
        {
            ("GET", "/api/devices"): {
                "devices": [
                    {
                        "device_id": "d1",
                        "name": "Tag",
                        "label": "Mom",
                        "icon": "lucide:user-round",
                        "color": "#37c67a",
                    }
                ]
            }
        }
    )
    row = asyncio.run(mcp.call_tool("list_devices", {})).structured_content["devices"][0]
    assert row["label"] == "Mom"
    assert row["icon"] == "lucide:user-round"
    assert row["color"] == "#37c67a"


def test_list_groups_passes_through_icon() -> None:
    mcp = _server(
        {("GET", "/api/groups"): [{"id": 1, "name": "Family", "icon": "lucide:dog"}]},
    )
    body = asyncio.run(mcp.call_tool("list_groups", {})).structured_content
    assert body["data"][0]["icon"] == "lucide:dog"
