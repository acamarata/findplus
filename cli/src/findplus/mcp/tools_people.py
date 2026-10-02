"""People tools for the Find+ MCP server: the twin of /api/people (spec § 7.2).

Purpose    : Read: list_people (each with where they likely are now),
             where_is (one person, by name), get_person_day (one local day in
             plain words, with the trackers behind each line) and
             get_people_suggestions (a preview, nothing saved). Write, only
             with --allow-writes (D16): accept_people_suggestions and
             set_tracker_role.
Inputs     : An MCPServer and a DaemonClient (read at call time, as tools_read).
Outputs    : Daemon JSON plus the notice and the caveats each answer needs.
Constraints: Every answer that places a person carries PRESENCE_STALE and
             ALERTS_LATENCY verbatim; an agent paraphrases, so it must get them.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from findplus import honesty
from findplus.mcp import errors
from findplus.mcp.client import DaemonClient
from findplus.mcp.tools_read import _params, _with_notice

_PLACING = (honesty.PRESENCE_STALE, honesty.ALERTS_LATENCY)
_DAY = (honesty.PRESENCE_STALE, honesty.ALERTS_LATENCY, honesty.TRIPS_APPROXIMATE)


async def _resolve(client: DaemonClient, person: str | int) -> int | dict:
    """A person's id from an id or a name (any letter case); an error dict otherwise."""
    if isinstance(person, int) or str(person).isdigit():
        return int(person)
    people = await client.get("/api/people")
    if not isinstance(people, list):
        return people  # locked or daemon down: pass the error through
    key = str(person).casefold()
    hits = [p for p in people if p["name"].casefold() == key]
    hits = hits or [p for p in people if p["name"].casefold().startswith(key)]
    if len(hits) == 1:
        return hits[0]["id"]
    names = ", ".join(p["name"] for p in people) or "none yet"
    if hits:
        return errors.error("validation", f"{person!r} matches more than one person", names)
    return errors.error("not_found", f"no person named {person!r}", f"people: {names}")


async def _people_with_now(client: DaemonClient) -> dict | list:
    people = await client.get("/api/people")
    if not isinstance(people, list):
        return people  # an error dict (locked, daemon down) passes through untouched
    for person in people:
        person["now"] = await client.get(f"/api/people/{person['id']}/now")
    return people


def register_people_read_tools(mcp: MCPServer, _c) -> None:
    @mcp.tool(structured_output=True)
    async def list_people() -> dict[str, Any]:
        """List people and pets, their trackers, and where each likely is now."""
        return await _with_notice(await _people_with_now(_c()), _c(), caveats=_PLACING)

    @mcp.tool(structured_output=True)
    async def where_is(person: str) -> dict[str, Any]:
        """Where one person likely is now (name or id), with how sure and how old."""
        who = await _resolve(_c(), person)
        if isinstance(who, dict):
            return await _with_notice(who, _c())
        return await _with_notice(await _c().get(f"/api/people/{who}/now"), _c(), caveats=_PLACING)

    @mcp.tool(structured_output=True)
    async def get_person_day(
        person: str, date: str | None = None, timezone: str | None = None
    ) -> dict[str, Any]:
        """One person's local day in plain words: left, arrived, stops, gaps, left-behind."""
        who = await _resolve(_c(), person)
        if isinstance(who, dict):
            return await _with_notice(who, _c())
        data = await _c().get(f"/api/people/{who}/day", _params(date=date, timezone=timezone))
        return await _with_notice(data, _c(), caveats=_DAY)

    @mcp.tool(structured_output=True)
    async def get_people_suggestions() -> dict[str, Any]:
        """Preview people suggested from tracker names. Saves nothing."""
        return await _with_notice(await _c().get("/api/people/suggestions"), _c())


def register_people_write_tools(mcp: MCPServer, client: DaemonClient) -> None:
    def _c() -> DaemonClient:
        return mcp._daemon_client

    @mcp.tool(structured_output=True)
    async def accept_people_suggestions(
        accept: list[dict[str, Any]] | None = None, dismiss: list[str] | None = None
    ) -> dict[str, Any]:
        """Create people from suggestions (as edited) and/or dismiss suggestion keys."""
        body = {"accept": accept or [], "dismiss": dismiss or []}
        return await _with_notice(await _c().post("/api/people/suggestions/accept", body), _c())

    @mcp.tool(structured_output=True)
    async def set_tracker_role(
        device_id: str, role: str | None = None, carry_weight: float | None = None
    ) -> dict[str, Any]:
        """Set what a tracker is attached to (bag, shoes, phone...) and its carry weight."""
        body = _params(role=role, carry_weight=carry_weight)
        return await _with_notice(await _c().put(f"/api/people/trackers/{device_id}", body), _c())
