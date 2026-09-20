"""The per-response notice names the provider the data actually came from.

E1 honesty round 2 F2: DaemonClient.get_notice() returned notices["find_hub"]
unconditionally and tools_read._with_notice stamps it on every read tool's
response, so an Apple-only user's agent was told its accessory fixes were
"reported through Google's Find Hub network" and would quote it. The MCP
server's `instructions` had already been fixed this way (c21fc63); this field
had not.
"""

from __future__ import annotations

import pytest

from findplus.honesty import APPLE, FIND_HUB
from findplus.mcp.client import DaemonClient, _notice_for


def _rows(*providers: str) -> dict:
    return {
        "devices": [
            {"device_id": f"d{i}", "provider": p, "is_tracked": True}
            for i, p in enumerate(providers)
        ]
    }


def test_apple_only_gets_the_apple_sentence_alone() -> None:
    out = _notice_for(_rows("apple-find-my"), FIND_HUB, APPLE)
    assert out == APPLE
    assert "Find Hub" not in out


def test_google_only_gets_the_find_hub_sentence_alone() -> None:
    assert _notice_for(_rows("google-find-hub"), FIND_HUB, APPLE) == FIND_HUB


def test_a_mixed_set_gets_both() -> None:
    out = _notice_for(_rows("google-find-hub", "apple-find-my"), FIND_HUB, APPLE)
    assert FIND_HUB in out and APPLE in out


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"devices": []},
        {"error": {"code": "locked"}},
        None,
        "not a dict",
        {"devices": [{"device_id": "d0", "provider": "apple-find-my", "is_tracked": False}]},
    ],
)
def test_an_unreadable_device_list_never_claims_find_hub_alone(payload) -> None:
    """A locked daemon must not make the fallback a false statement."""
    out = _notice_for(payload, FIND_HUB, APPLE)
    assert FIND_HUB in out and APPLE in out


@pytest.mark.asyncio
async def test_get_notice_uses_the_device_list(monkeypatch) -> None:
    client = DaemonClient()
    calls: list[str] = []

    async def _get(path: str, **kw):
        calls.append(path)
        if path == "/api/config":
            return {"notices": {"find_hub": FIND_HUB, "apple": APPLE}}
        return _rows("apple-find-my")

    monkeypatch.setattr(client, "get", _get)

    assert await client.get_notice() == APPLE
    assert calls == ["/api/config", "/api/devices"]
    # Cached for the process: a second call issues no further HTTP.
    assert await client.get_notice() == APPLE
    assert calls == ["/api/config", "/api/devices"]
