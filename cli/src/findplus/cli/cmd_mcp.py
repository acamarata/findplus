"""The `findplus mcp` command: start the MCP server over stdio.

Purpose    : Register findplus as a Model Context Protocol server so MCP
             clients (Claude Desktop, Claude Code) can query the daemon.
Inputs     : --allow-writes flag, --url base URL of the running daemon.
Outputs    : Runs the stdio transport until the client disconnects.
Constraints: The MCP server itself is a thin client of the local API
             (ADR-P1-06) — it imports findplus.mcp only when this command
             actually runs, so `findplus --help` never pays the mcp SDK's
             import cost.
"""

from __future__ import annotations

import click


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
    server.run(transport="stdio")
