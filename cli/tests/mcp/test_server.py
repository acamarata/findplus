"""MCP server: lock/unlock mapping, write-tool gating, daemon-down, export cap.

StubClient replaces DaemonClient's HTTP layer with a dict lookup — no real
httpx or network calls (invariant rule 3: tests never touch the network).
"""

from __future__ import annotations

import asyncio

from findplus.mcp.client import DaemonClient
from findplus.mcp.server import create_mcp_server


class StubClient(DaemonClient):
    def __init__(
        self, responses: dict[tuple[str, str], dict], cookies: dict[str, str] | None = None
    ):
        super().__init__()
        self._responses = responses
        self._cookies = cookies or {}

    async def _request(self, method, path, *, params=None, json_body=None):
        return self._responses.get(
            (method.upper(), path), {"error": {"code": "not_found", "message": path}}
        )

    async def post_with_cookie(self, path, body=None):
        resp = self._responses.get(("POST", path), {})
        return resp, self._cookies.get(path)


def test_locked_returns_hint():
    client = StubClient(
        {
            ("GET", "/api/status"): {
                "error": {
                    "code": "locked",
                    "message": "Find+ is locked",
                    "hint": "call unlock(pin)",
                }
            }
        }
    )
    mcp = create_mcp_server()
    mcp._daemon_client = client
    result = asyncio.run(mcp.call_tool("get_status", {}))
    assert result.structured_content["error"]["code"] == "locked"
    assert "unlock" in result.structured_content["error"]["hint"]


def test_unlock_then_data():
    client = StubClient(
        {
            ("GET", "/api/status"): {"uptime": 1, "notices": {}},
            ("GET", "/api/config"): {"notices": {"find_hub": "NOTICE"}},
        },
        cookies={"/api/lock/unlock": "test-token"},
    )
    mcp = create_mcp_server()
    mcp._daemon_client = client
    asyncio.run(mcp.call_tool("unlock", {"pin": "1234"}))
    assert client.session_cookie == "test-token"


def test_writes_absent_without_flag():
    mcp = create_mcp_server(allow_writes=False)
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "poll_now" not in names
    assert "add_place" not in names


def test_daemon_down():
    client = StubClient(
        {
            ("GET", "/api/status"): {
                "error": {
                    "code": "daemon_down",
                    "message": "daemon not running",
                    "hint": "run findplus start",
                }
            },
            ("GET", "/api/config"): {"notices": {"find_hub": "NOTICE"}},
        }
    )
    mcp = create_mcp_server()
    mcp._daemon_client = client
    result = asyncio.run(mcp.call_tool("get_status", {}))
    assert result.structured_content["error"]["code"] == "daemon_down"


def test_export_truncation():
    long_text = "x" * 5_000_001

    class ExportClient(StubClient):
        async def get_text(self, path, params=None):
            return long_text, 200

        async def get_notice(self):
            return "NOTICE"

    client = ExportClient({})
    mcp = create_mcp_server()
    mcp._daemon_client = client
    result = asyncio.run(
        mcp.call_tool("export", {"format": "csv", "start": "2026-01-01", "end": "2026-01-31"})
    )
    assert result.structured_content["truncated"] is True
    assert len(result.structured_content["text"]) == 5_000_000


def test_unlock_wrong_pin_keeps_no_cookie():
    client = StubClient({("POST", "/api/lock/unlock"): {"unlocked": False}})
    mcp = create_mcp_server()
    mcp._daemon_client = client
    result = asyncio.run(mcp.call_tool("unlock", {"pin": "0000"}))
    assert client.session_cookie is None
    assert "cookie" not in result.structured_content


def test_instructions_name_both_providers_verbatim():
    """An agent querying Apple accessories was told the data came from Find Hub (E1 F2).

    Both sentences must appear byte-for-byte: honesty.py is the one source, so a
    paraphrase here would be a second copy that drifts.
    """
    from findplus import honesty

    instructions = create_mcp_server().instructions

    assert honesty.FIND_HUB in instructions
    assert honesty.APPLE in instructions
