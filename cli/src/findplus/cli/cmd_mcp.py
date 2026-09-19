"""The `findplus mcp` command: start the MCP server over stdio.

Purpose    : Register findplus as a Model Context Protocol server so MCP
             clients (Claude Desktop, Claude Code) can query the daemon.
Inputs     : --allow-writes flag, --url base URL of the running daemon.
Outputs    : Runs the stdio transport until the client disconnects.
Constraints: The MCP server itself is a thin client of the local API
             (ADR-P1-06) — it imports findplus.mcp only when this command
             actually runs, so `findplus --help` never pays the mcp SDK's
             import cost. FINDPLUS_PIN, if set, is spent once here and never
             echoed, logged or stored on disk.
"""

from __future__ import annotations

import asyncio

import click


async def _unlock_at_startup(server: object) -> str | None:
    """Spend FINDPLUS_PIN once, per specs/mcp-tools.md. Returns an error message."""
    client = server._daemon_client
    result, cookie = await client.post_with_cookie("/api/lock/unlock", {"pin": server._startup_pin})
    if cookie:
        client.set_session_cookie(cookie)
        return None
    if isinstance(result, dict) and "error" in result:
        return str(result["error"].get("message", "unlock failed"))
    return "FINDPLUS_PIN was rejected"


@click.command()
@click.option(
    "--allow-writes",
    is_flag=True,
    default=False,
    help="Register write tools (poll, places, groups, lock).",
)
@click.option(
    "--url",
    default="http://127.0.0.1:8647",
    show_default=True,
    help="Base URL of the local Find+ daemon.",
)
def mcp(allow_writes: bool, url: str) -> None:
    """Start the Find+ MCP server (stdio transport)."""
    from findplus.mcp.server import create_mcp_server

    server = create_mcp_server(base_url=url, allow_writes=allow_writes)
    if server._startup_pin:
        problem = asyncio.run(_unlock_at_startup(server))
        if problem:
            # stderr only: stdout is the MCP transport, and the PIN is never echoed.
            click.echo(f"findplus mcp: startup unlock failed ({problem})", err=True)
    server.run(transport="stdio")
