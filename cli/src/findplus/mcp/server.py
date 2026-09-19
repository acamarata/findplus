# Import path confirmed: from mcp.server.mcpserver import MCPServer (mcp 2.2.0, verified 2026-09-19)
"""Factory for the Find+ MCP server (stdio transport, thin client of the daemon).

Purpose    : Build the MCPServer instance, wire it to a DaemonClient, and
             register read/write tools per ADR-P1-06.
Inputs     : base_url of the running daemon; allow_writes flag.
Outputs    : A configured MCPServer, not yet run.
Constraints: Write tools are registered only when allow_writes is True.
"""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from findplus.honesty import FIND_HUB
from findplus.mcp.client import DaemonClient
from findplus.mcp.tools_read import register_read_tools
from findplus.mcp.tools_write import register_write_tools


def create_mcp_server(
    base_url: str = "http://127.0.0.1:8647",
    allow_writes: bool = False,
) -> MCPServer:
    from findplus import __version__

    mcp = MCPServer("findplus", version=__version__, instructions=FIND_HUB)
    client = DaemonClient(base_url=base_url)
    mcp._daemon_client = client
    mcp._allow_writes = allow_writes
    mcp._startup_pin = os.environ.get("FINDPLUS_PIN")
    register_read_tools(mcp, client)
    if allow_writes:
        register_write_tools(mcp, client)
    return mcp
