"""The MCP surface carries presence_stale and alerts_latency, not just the provider.

E1 honesty round 3 F5: the server's instructions were FIND_HUB + APPLE only,
and _with_notice stamped just the provider sentence. get_group_presence returns
`stale` and a verdict, get_place_events returns arrivals with a lag, and
nothing said a missing fix is not "at home" or that an arrival may be hours
late — to the one consumer guaranteed to paraphrase rather than quote.
"""

from __future__ import annotations

import pytest

from findplus import honesty
from findplus.mcp.tools_read import _with_notice


class _Client:
    async def get_notice(self):
        return honesty.FIND_HUB


@pytest.mark.asyncio
async def test_a_data_response_carries_the_caveats_verbatim() -> None:
    out = await _with_notice({"places": []}, _Client(), caveats=(honesty.PRESENCE_STALE,))

    assert out["caveats"] == [honesty.PRESENCE_STALE]
    assert out["notice"] == honesty.FIND_HUB


@pytest.mark.asyncio
async def test_a_list_response_is_wrapped_and_still_carries_them() -> None:
    out = await _with_notice([1, 2], _Client(), caveats=(honesty.ALERTS_LATENCY,))

    assert out["data"] == [1, 2]
    assert out["caveats"] == [honesty.ALERTS_LATENCY]


@pytest.mark.asyncio
async def test_an_error_response_stays_exactly_error_and_notice() -> None:
    """A locked daemon must not grow keys; test_server_locked.py pins the shape."""
    out = await _with_notice({"error": {"code": "locked"}}, _Client(), caveats=(honesty.APPLE,))

    assert set(out) == {"error", "notice"}


def test_the_server_instructions_carry_all_four_sentences() -> None:
    from findplus.mcp.server import create_mcp_server

    instructions = create_mcp_server().instructions

    for sentence in (
        honesty.FIND_HUB,
        honesty.APPLE,
        honesty.PRESENCE_STALE,
        honesty.ALERTS_LATENCY,
    ):
        assert sentence in instructions, f"missing verbatim: {sentence[:40]}..."


def test_the_presence_and_event_tools_ask_for_caveats() -> None:
    """The wiring, not just the helper: these are the tools that need them."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "findplus" / "mcp" / "tools_read.py"
    text = src.read_text()

    for tool in ("get_group_presence", "get_place_events", "get_latest", "list_places"):
        start = text.index(f"async def {tool}(")
        body = text[
            start : text.index("@mcp.tool", start + 1) if "@mcp.tool" in text[start:] else len(text)
        ]
        assert "caveats" in body, f"{tool} serves location data with no caveat"
