"""specs/mcp-tools.md §Tests: the SDK's in-memory client against the real app.

test_server.py stubs DaemonClient._request, so it never exercises the daemon's
own 401 -> locked mapping. These cases run the MCP server against a real
create_app() over an ASGI transport, with the app lock engaged, and assert that
EVERY tool (read and write) returns the documented error and never data.

No network: httpx.ASGITransport calls the app in-process (invariant 3).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client

from findplus.api import create_app
from findplus.mcp.client import DaemonClient
from findplus.mcp.server import create_mcp_server

#: Every read tool plus the arguments the spec marks required.
READ_TOOLS: dict[str, dict] = {
    "get_status": {},
    "list_devices": {},
    "list_groups": {},
    "list_places": {},
    "get_latest": {},
    "get_timeline": {"day": "2026-09-19"},
    "get_place_events": {},
    "get_group_presence": {"group_id": 1},
    "export": {"format": "csv", "start": "2026-09-01", "end": "2026-09-19"},
}
WRITE_TOOLS: dict[str, dict] = {
    "poll_now": {},
    "add_place": {"name": "x", "latitude": 1.0, "longitude": 2.0, "radius_meters": 100.0},
    "remove_place": {"place_id": 1},
    "add_group": {"name": "g", "member_ids": ["TAG-001"]},
    "set_group_members": {"group_id": 1, "member_ids": ["TAG-001"]},
}


class AsgiDaemonClient(DaemonClient):
    """DaemonClient whose transport is the app itself, not a socket."""

    def __init__(self, app) -> None:
        super().__init__(base_url="http://127.0.0.1:8647")
        self._app = app

    async def _send(self, method: str, path: str, timeout: float, **kw: object) -> httpx.Response:
        transport = httpx.ASGITransport(app=self._app)
        async with httpx.AsyncClient(transport=transport, base_url=self._base_url) as c:
            return await c.request(method, path, headers=self._headers(), timeout=timeout, **kw)


@pytest.fixture
def locked_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    from findplus.config import get_settings, reset_settings_cache
    from findplus.db.migrate import upgrade_to_head
    from findplus.db.session import get_engine

    monkeypatch.setenv("FINDPLUS_DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("FINDPLUS_STATE_DIR", str(tmp_path / "state"))
    reset_settings_cache()
    get_engine.cache_clear()
    get_settings()
    upgrade_to_head()
    app = create_app()
    with TestClient(app) as tc:
        assert tc.post("/api/settings/pin", json={"new_pin": "000000"}).status_code == 200
        tc.cookies.clear()
        assert tc.get("/api/lock/status").json()["locked"] is True
        yield app
    reset_settings_cache()
    get_engine.cache_clear()


def _server(app, *, allow_writes: bool = True):
    server = create_mcp_server(allow_writes=allow_writes)
    server._daemon_client = AsgiDaemonClient(app)
    return server


@pytest.mark.parametrize("tool", sorted(READ_TOOLS))
async def test_read_tool_locked_returns_error_not_data(locked_app, tool: str) -> None:
    async with Client(_server(locked_app)) as client:
        body = (await client.call_tool(tool, READ_TOOLS[tool])).structured_content
    assert body["error"] == {
        "code": "locked",
        "message": "Find+ is locked",
        "hint": "call unlock(pin)",
    }
    assert set(body) == {"error", "notice"}, f"{tool} returned data while locked: {sorted(body)}"


@pytest.mark.parametrize("tool", sorted(WRITE_TOOLS))
async def test_write_tool_locked_returns_error(locked_app, tool: str) -> None:
    async with Client(_server(locked_app)) as client:
        body = (await client.call_tool(tool, WRITE_TOOLS[tool])).structured_content
    assert body["error"]["code"] == "locked"


async def test_no_tool_leaks_coordinates_while_locked(locked_app) -> None:
    async with Client(_server(locked_app)) as client:
        for tool, args in {**READ_TOOLS, **WRITE_TOOLS}.items():
            text = str((await client.call_tool(tool, args)).structured_content)
            for key in ("latitude", "longitude", "device_id", '"places"'):
                assert key not in text, f"{tool} leaked {key} while locked"


async def test_unlock_then_data_and_validation_mapping(locked_app) -> None:
    async with Client(_server(locked_app)) as client:
        assert (await client.call_tool("unlock", {"pin": "000000"})).structured_content["unlocked"]
        assert "tracked_count" in (await client.call_tool("get_status", {})).structured_content

        bad_radius = await client.call_tool(
            "add_place", {"name": "y", "latitude": 1.0, "longitude": 2.0, "radius_meters": -5.0}
        )
        assert bad_radius.structured_content["error"]["code"] == "validation"

        bad_quorum = await client.call_tool(
            "add_group", {"name": "g2", "member_ids": [], "quorum": "bogus"}
        )
        assert bad_quorum.structured_content["error"]["code"] == "validation"

        missing = await client.call_tool("remove_place", {"place_id": 999})
        assert missing.structured_content["error"]["code"] == "not_found"


async def test_daemon_down_is_an_error_not_a_traceback() -> None:
    server = create_mcp_server(base_url="http://127.0.0.1:9", allow_writes=True)
    async with Client(server) as client:
        for tool in ("get_status", "export", "unlock", "poll_now"):
            args = {"pin": "0"} if tool == "unlock" else READ_TOOLS.get(tool, {})
            body = (await client.call_tool(tool, args)).structured_content
            assert body["error"]["code"] == "daemon_down", tool


async def test_every_tool_has_a_description() -> None:
    async with Client(create_mcp_server(allow_writes=True)) as client:
        tools = (await client.list_tools()).tools
    assert len(tools) == 16
    missing = [t.name for t in tools if not (t.description or "").strip()]
    assert not missing, f"tools with no description: {missing}"


async def test_findplus_pin_unlocks_at_startup(locked_app, monkeypatch) -> None:
    """specs/mcp-tools.md: FINDPLUS_PIN, if set, is used once at startup."""
    from findplus.cli.cmd_mcp import _unlock_at_startup

    monkeypatch.setenv("FINDPLUS_PIN", "000000")
    server = _server(locked_app)
    assert server._startup_pin == "000000"
    assert await _unlock_at_startup(server) is None
    assert server._daemon_client.session_cookie
    async with Client(server) as client:
        assert "tracked_count" in (await client.call_tool("get_status", {})).structured_content


async def test_findplus_pin_wrong_reports_and_does_not_unlock(locked_app, monkeypatch) -> None:
    from findplus.cli.cmd_mcp import _unlock_at_startup

    monkeypatch.setenv("FINDPLUS_PIN", "9999")
    server = _server(locked_app)
    assert await _unlock_at_startup(server) is not None
    assert server._daemon_client.session_cookie is None


def test_test_package_cannot_shadow_the_mcp_sdk() -> None:
    """cli/tests/mcp/ must stay a plain directory, never a package.

    With an __init__.py, pytest's default prepend import mode registers this
    directory as the top-level module `mcp`, which shadows the installed SDK
    for the rest of the process (reproduced 2026-09-19, P1-E9-W6-S1-T4).
    """
    import mcp.server.mcpserver as sdk

    assert not (Path(__file__).parent / "__init__.py").exists()
    assert "site-packages" in sdk.__file__
