"""Read tools for the Find+ MCP server — always registered.

Purpose    : Expose the daemon's read surface (status, devices, groups,
             places, timeline, export, unlock) to MCP clients.
Inputs     : An MCPServer instance and a DaemonClient, from create_mcp_server.
Outputs    : Tool responses, each carrying the find_hub notice.
Constraints: export is capped at 5,000,000 chars. Every docstring here is the
             tool description an MCP client shows its user, so keep them
             one line and factual. Tool bodies read
             mcp._daemon_client at call time (not a closed-over client) so
             tests can swap it after construction — per specs/mcp-tools.md
             §Tests, "dependency-injected base client" (deviation recorded
             P1-E9-W6-S1-T4: a closure over the constructor's client made
             swapping mcp._daemon_client a no-op, verified by reproduction).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from findplus import honesty
from findplus.mcp import errors
from findplus.mcp.client import UNREACHABLE, DaemonClient


def _params(**kwargs: object) -> dict[str, object]:
    return {k: v for k, v in kwargs.items() if v is not None}


async def _with_notice(
    data: dict | list, client: DaemonClient, *, caveats: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Stamp a tool response with the sentences its data needs.

    `notice` names the provider. `caveats` carries the sentences that belong to
    a particular SHAPE of answer: presence_stale wherever a missing fix could be
    read as a location, alerts_latency wherever an arrival time is served. An
    agent paraphrases rather than quotes, so it gets them verbatim and beside
    the data, not only in the server instructions (E1 honesty round 3 F5).
    """
    notice = await client.get_notice()
    if isinstance(data, list):
        data = {"data": data}
    data["notice"] = notice
    # An error response carries no data, so it needs no caveats about data;
    # a locked daemon's reply stays exactly {error, notice}, which
    # test_server_locked.py pins as the no-leak shape.
    if caveats and "error" not in data:
        data["caveats"] = list(caveats)
    return data


async def _status_raw(client: DaemonClient) -> dict | list:
    return await client.get("/api/status")


async def _devices_raw(client: DaemonClient) -> dict | list:
    return await client.get("/api/devices")


async def _groups_raw(client: DaemonClient) -> dict | list:
    return await client.get("/api/groups")


async def _places_raw(client: DaemonClient) -> dict | list:
    return await client.get("/api/places")


async def _latest_raw(client: DaemonClient, device_id: str | None) -> dict | list:
    return await client.get("/api/latest", _params(device_id=device_id))


async def _timeline_raw(
    client: DaemonClient,
    day: str,
    device_id: str | None,
    group_id: int | None,
    timezone: str | None,
) -> dict | list:
    params = _params(day=day, device_id=device_id, group_id=group_id, timezone=timezone)
    return await client.get("/api/timeline", params)


async def _place_events_raw(
    client: DaemonClient,
    place_id: int | None,
    device_id: str | None,
    group_id: int | None,
    since: str | None,
    until: str | None,
    limit: int,
) -> dict | list:
    params = _params(
        place_id=place_id,
        device_id=device_id,
        group_id=group_id,
        since=since,
        until=until,
        limit=limit,
    )
    return await client.get("/api/places/events", params)


async def _group_presence_raw(
    client: DaemonClient, group_id: int, window_minutes: int
) -> dict | list:
    return await client.get(f"/api/groups/{group_id}/presence", {"window": window_minutes})


async def _export_data(
    client: DaemonClient,
    format: str,
    start: str,
    end: str,
    device_id: str | None,
    group_id: int | None,
) -> dict[str, Any]:
    params = _params(format=format, start=start, end=end, device_id=device_id, group_id=group_id)
    text, status = await client.get_text("/api/export", params)
    if status == UNREACHABLE:
        return await _with_notice(errors.daemon_down(), client)
    failure = errors.from_status(status, text)
    if failure is not None:
        return await _with_notice(failure, client)
    truncated = len(text) > 5_000_000
    capped = text[:5_000_000]
    notice = await client.get_notice()
    return {"format": format, "text": capped, "truncated": truncated, "notice": notice}


async def _unlock_data(client: DaemonClient, pin: str) -> dict[str, Any]:
    result, cookie = await client.post_with_cookie("/api/lock/unlock", {"pin": pin})
    if cookie:
        client.set_session_cookie(cookie)
    notice = await client.get_notice()
    if isinstance(result, dict):
        result["notice"] = notice
    return result


def _register_listing_tools(mcp: MCPServer, _c) -> None:
    """status/devices/groups/places: the four whole-collection reads."""

    @mcp.tool(structured_output=True)
    async def get_status() -> dict[str, Any]:
        """Daemon status, poll schedule and provider health."""
        return await _with_notice(await _status_raw(_c()), _c())

    @mcp.tool(structured_output=True)
    async def list_devices() -> dict[str, Any]:
        """Every tracked device with its provider, groups and presence."""
        return await _with_notice(await _devices_raw(_c()), _c(), caveats=(honesty.PRESENCE_STALE,))

    @mcp.tool(structured_output=True)
    async def list_groups() -> dict[str, Any]:
        """Every device group with its quorum settings and members."""
        return await _with_notice(await _groups_raw(_c()), _c())

    @mcp.tool(structured_output=True)
    async def list_places() -> dict[str, Any]:
        """Every saved place with its radius and the devices inside it."""
        return await _with_notice(await _places_raw(_c()), _c(), caveats=(honesty.PRESENCE_STALE,))


def _register_query_tools(mcp: MCPServer, _c) -> None:
    """latest/timeline/place_events/group_presence: the filtered reads."""

    @mcp.tool(structured_output=True)
    async def get_latest(device_id: str | None = None) -> dict[str, Any]:
        """The most recent fix per device, or for one device."""
        data = await _latest_raw(_c(), device_id)
        return await _with_notice(data, _c(), caveats=(honesty.PRESENCE_STALE,))

    @mcp.tool(structured_output=True)
    async def get_timeline(
        day: str,
        device_id: str | None = None,
        group_id: int | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Location history for one day, per device or per group member."""
        data = await _timeline_raw(_c(), day, device_id, group_id, timezone)
        return await _with_notice(data, _c())

    @mcp.tool(structured_output=True)
    async def get_place_events(
        place_id: int | None = None,
        device_id: str | None = None,
        group_id: int | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """The place ENTER and EXIT event log, newest first."""
        data = await _place_events_raw(_c(), place_id, device_id, group_id, since, until, limit)
        caveats = (honesty.ALERTS_LATENCY, honesty.PRESENCE_STALE)
        return await _with_notice(data, _c(), caveats=caveats)

    @mcp.tool(structured_output=True)
    async def get_group_presence(group_id: int, window_minutes: int = 60) -> dict[str, Any]:
        """A group's presence verdict over the last window_minutes."""
        data = await _group_presence_raw(_c(), group_id, window_minutes)
        return await _with_notice(data, _c(), caveats=(honesty.PRESENCE_STALE,))


def _register_action_tools(mcp: MCPServer, _c) -> None:
    """export/unlock: the two tools with side effects or a non-JSON payload."""

    @mcp.tool(structured_output=True)
    async def export(
        format: str, start: str, end: str, device_id: str | None = None, group_id: int | None = None
    ) -> dict[str, Any]:
        """Export history as csv, json, gpx or kml text (capped at 5 MB)."""
        return await _export_data(_c(), format, start, end, device_id, group_id)

    @mcp.tool(structured_output=True)
    async def unlock(pin: str) -> dict[str, Any]:
        """Unlock the daemon with the app PIN for the rest of this session."""
        return await _unlock_data(_c(), pin)


def register_read_tools(mcp: MCPServer, client: DaemonClient) -> None:
    """Wire each MCP tool to its `_*_raw` fetch helper and `_with_notice`.

    Every wrapper reads `mcp._daemon_client` at call time (not the `client`
    parameter, which only satisfies the registration signature) so tests can
    swap the client after construction — see the module docstring. Split into
    three `_register_*_tools` groups (E13 loop2 A3) purely to stay under the
    50-line function cap; registration order and every tool's behavior
    (including which caveats each response carries) is unchanged.
    """

    def _c() -> DaemonClient:
        return mcp._daemon_client

    _register_listing_tools(mcp, _c)
    _register_query_tools(mcp, _c)
    _register_action_tools(mcp, _c)
