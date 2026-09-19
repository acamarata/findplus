# Import path confirmed: from mcp.server.mcpserver import MCPServer (mcp 2.2.0, verified 2026-09-19)
"""Factory for the Find+ MCP server (stdio transport, thin client of the daemon).

Purpose    : Build the MCPServer instance, wire it to a DaemonClient, and
             register read/write tools per ADR-P1-06.
Inputs     : base_url of the running daemon; allow_writes flag.
Outputs    : A configured MCPServer, not yet run.
Constraints: Write tools are registered only when allow_writes is True.
             The startup PIN is read once from FINDPLUS_PIN or the 0600 file
             named by FINDPLUS_PIN_FILE, then removed from the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from findplus.honesty import FIND_HUB
from findplus.mcp.client import DaemonClient
from findplus.mcp.tools_read import register_read_tools
from findplus.mcp.tools_write import register_write_tools


def read_startup_pin() -> str | None:
    """The PIN to spend once at startup, taken from the environment.

    `FINDPLUS_PIN_FILE` points at a 0600 file holding nothing but the PIN and
    is the preferred form: an MCP client config is usually world-readable and
    often lands in a git repository, while the environment of a running
    process is visible to anything the user runs. Both variables are removed
    from `os.environ` once read, so a child process (the daemon, a shell the
    tool layer starts) never inherits the PIN.
    """
    pin = os.environ.pop("FINDPLUS_PIN", None)
    pin_file = os.environ.pop("FINDPLUS_PIN_FILE", None)
    if pin:
        return pin
    if not pin_file:
        return None
    try:
        return Path(pin_file).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def create_mcp_server(
    base_url: str = "http://127.0.0.1:8647",
    allow_writes: bool = False,
) -> MCPServer:
    from findplus import __version__

    mcp = MCPServer("findplus", version=__version__, instructions=FIND_HUB)
    client = DaemonClient(base_url=base_url)
    mcp._daemon_client = client
    mcp._allow_writes = allow_writes
    mcp._startup_pin = read_startup_pin()
    register_read_tools(mcp, client)
    if allow_writes:
        register_write_tools(mcp, client)
    return mcp
