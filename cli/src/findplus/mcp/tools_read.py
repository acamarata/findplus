"""Read tools for the Find+ MCP server — always registered.

Purpose    : Expose the daemon's read surface (status, devices, groups,
             places, timeline, export, unlock) to MCP clients.
Inputs     : An MCPServer instance and a DaemonClient, from create_mcp_server.
Outputs    : Tool responses, each carrying the find_hub notice.
Constraints: export is capped at 5,000,000 chars. Tool bodies read
             mcp._daemon_client at call time (not a closed-over client) so
             tests can swap it after construction — per specs/mcp-tools.md
             §Tests, "dependency-injected base client" (deviation recorded
             P1-E9-W6-S1-T4: a closure over the constructor's client made
             swapping mcp._daemon_client a no-op, verified by reproduction).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from findplus.mcp.client import DaemonClient


def _params(**kwargs: object) -> dict[str, object]:
    return {k: v for k, v in kwargs.items() if v is not None}


async def _with_notice(data: dict | list, client: DaemonClient) -> dict[str, Any]:
    notice = await client.get_notice()
    if isinstance(data, list):
        return {"data": data, "notice": notice}
    data["notice"] = notice
    return data


def register_read_tools(mcp: MCPServer, client: DaemonClient) -> None:
    def _c() -> DaemonClient:
        return mcp._daemon_client

    @mcp.tool(structured_output=True)
    async def get_status() -> dict[str, Any]:
        return await _with_notice(await _c().get("/api/status"), _c())

    @mcp.tool(structured_output=True)
    async def list_devices() -> dict[str, Any]:
        return await _with_notice(await _c().get("/api/devices"), _c())

    @mcp.tool(structured_output=True)
    async def list_groups() -> dict[str, Any]:
        return await _with_notice(await _c().get("/api/groups"), _c())

    @mcp.tool(structured_output=True)
    async def list_places() -> dict[str, Any]:
        return await _with_notice(await _c().get("/api/places"), _c())

    @mcp.tool(structured_output=True)
    async def get_latest(device_id: str | None = None) -> dict[str, Any]:
        data = await _c().get("/api/latest", _params(device_id=device_id))
        return await _with_notice(data, _c())

    @mcp.tool(structured_output=True)
    async def get_timeline(
        day: str,
        device_id: str | None = None,
        group_id: int | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        params = _params(day=day, device_id=device_id, group_id=group_id, timezone=timezone)
        return await _with_notice(await _c().get("/api/timeline", params), _c())

    @mcp.tool(structured_output=True)
    async def get_place_events(
        place_id: int | None = None,
        device_id: str | None = None,
        group_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        params = _params(
            place_id=place_id,
            device_id=device_id,
            group_id=group_id,
            since=since,
            until=until,
            limit=limit,
        )
        return await _with_notice(await _c().get("/api/places/events", params), _c())

    @mcp.tool(structured_output=True)
    async def get_group_presence(group_id: int, window_minutes: int = 60) -> dict[str, Any]:
        data = await _c().get(f"/api/groups/{group_id}/presence", {"window": window_minutes})
        return await _with_notice(data, _c())

    @mcp.tool(structured_output=True)
    async def export(
        format: str, start: str, end: str, device_id: str | None = None, group_id: int | None = None
    ) -> dict[str, Any]:
        params = _params(
            format=format, start=start, end=end, device_id=device_id, group_id=group_id
        )
        text, _status = await _c().get_text("/api/export", params)
        truncated = len(text) > 5_000_000
        capped = text[:5_000_000]
        notice = await _c().get_notice()
        return {"format": format, "text": capped, "truncated": truncated, "notice": notice}

    @mcp.tool(structured_output=True)
    async def unlock(pin: str) -> dict[str, Any]:
        result, cookie = await _c().post_with_cookie("/api/lock/unlock", {"pin": pin})
        if cookie:
            _c().set_session_cookie(cookie)
        notice = await _c().get_notice()
        if isinstance(result, dict):
            result["notice"] = notice
        return result
