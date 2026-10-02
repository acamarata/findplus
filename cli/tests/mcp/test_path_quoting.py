"""MCP tools quote caller input in API paths; add_place does not opt in to alerts."""

from __future__ import annotations

import asyncio

import pytest

from findplus.mcp.client import DaemonClient
from findplus.mcp.server import create_mcp_server


class Recorder(DaemonClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str, object]] = []

    async def _request(self, method, path, *, params=None, json_body=None):
        self.calls.append((method, path, json_body))
        if path == "/api/people":
            return [{"id": 1, "name": "Sam", "trackers": []}]
        return {}


def _call(tool: str, args: dict) -> Recorder:
    rec = Recorder()
    mcp = create_mcp_server(allow_writes=True)
    mcp._daemon_client = rec
    asyncio.run(mcp.call_tool(tool, args))
    return rec


@pytest.mark.parametrize("evil", ["../..", "..", "a/b", "x?y=1", "x#z"])
def test_set_tracker_role_quotes_the_device_id(evil):
    rec = _call("set_tracker_role", {"device_id": evil, "role": "bag"})
    puts = [c for c in rec.calls if c[0] == "PUT"]
    assert len(puts) == 1
    path = puts[0][1]
    assert path.startswith("/api/people/trackers/")
    tail = path[len("/api/people/trackers/") :]
    assert "/" not in tail and "?" not in tail and "#" not in tail
    assert tail not in (".", "..")


def test_numeric_ids_pass_through_unchanged():
    rec = _call("get_person_day", {"person": "1"})
    assert "/api/people/1/day" in [c[1] for c in rec.calls]
    rec = _call("remove_place", {"place_id": 7})
    assert ("DELETE", "/api/places/7", None) in rec.calls


def test_the_helper_quotes_dot_segments_and_slashes():
    from findplus.mcp.client import seg

    assert seg("../..") == "..%2F.."
    assert seg("..") == "%2E%2E"
    assert seg(".") == "%2E"
    assert seg(42) == "42"
    assert seg("TAG-001") == "TAG-001"


def _post(rec: Recorder):
    return next(c[2] for c in rec.calls if c[0] == "POST")


def test_add_place_does_not_create_an_alert_rule_unless_asked():
    base = {"name": "x", "latitude": 1.0, "longitude": 2.0, "radius_meters": 100.0}
    body = _post(_call("add_place", base))
    assert body["notify"] is False
    body = _post(_call("add_place", {**base, "notify": True}))
    assert body["notify"] is True
    tool = next(
        t
        for t in asyncio.run(create_mcp_server(allow_writes=True).list_tools())
        if t.name == "add_place"
    )
    assert "notify" in tool.description.lower() and "false" in tool.description.lower()
