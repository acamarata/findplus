"""Write tools for the Find+ MCP server — registered only with --allow-writes.

Purpose    : Let an opted-in MCP client mutate daemon state: poll, places,
             groups, lock. Never PIN changes, history deletion or alert
             credentials (per specs/mcp-tools.md §Write tools).
Inputs     : An MCPServer instance and a DaemonClient.
Outputs    : Tool responses, each carrying the find_hub notice.
Constraints: register_write_tools is called only when allow_writes is True.
             Tool bodies read mcp._daemon_client at call time, matching the
             fix applied to tools_read.py in P1-E9-W6-S1-T4.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from findplus.mcp.client import DaemonClient
from findplus.mcp.tools_read import _params, _with_notice


def register_write_tools(mcp: MCPServer, client: DaemonClient) -> None:
    def _c() -> DaemonClient:
        return mcp._daemon_client

    @mcp.tool(structured_output=True)
    async def poll_now() -> dict[str, Any]:
        """Ask the daemon to poll every tracked device now."""
        return await _with_notice(await _c().post("/api/poll-now"), _c())

    @mcp.tool(structured_output=True)
    async def add_place(
        name: str, latitude: float, longitude: float, radius_meters: float, color: str | None = None
    ) -> dict[str, Any]:
        """Create a place: a named circle that devices enter and leave."""
        body = _params(
            name=name,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
            color=color,
        )
        return await _with_notice(await _c().post("/api/places", body), _c())

    @mcp.tool(structured_output=True)
    async def remove_place(place_id: int) -> dict[str, Any]:
        """Delete a place and stop its events."""
        return await _with_notice(await _c().delete(f"/api/places/{place_id}"), _c())

    @mcp.tool(structured_output=True)
    async def add_group(
        name: str, member_ids: list[str], quorum: str | None = None
    ) -> dict[str, Any]:
        """Create a group of devices with a quorum rule for presence."""
        body = _params(name=name, member_ids=member_ids, quorum=quorum)
        return await _with_notice(await _c().post("/api/groups", body), _c())

    @mcp.tool(structured_output=True)
    async def set_group_members(group_id: int, member_ids: list[str]) -> dict[str, Any]:
        """Replace a group's member list with the given device ids."""
        body = {"member_ids": member_ids}
        return await _with_notice(await _c().put(f"/api/groups/{group_id}/members", body), _c())

    @mcp.tool(structured_output=True)
    async def lock() -> dict[str, Any]:
        """Lock the app again; every later call needs unlock(pin)."""
        result = await _c().post("/api/lock/lock")
        notice = await _c().get_notice()
        if isinstance(result, dict):
            result["notice"] = notice
        return result
