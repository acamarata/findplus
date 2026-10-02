"""A live Find+ server of its own for the day-story tests.

Purpose    : `findplus serve` against a throwaway database seeded by
             `_trips_seed.py` (two trackers, four saved places, five days).
Inputs     : pytest's tmp_path_factory; the shared `browser_session`.
Outputs    : `trips_server` -> {"base", "days", "env", "port"}; `trips_page`
             -> a Playwright page with OSM tiles stubbed.
Constraints: Module-scoped, so one file pays the ~3 s start once. TZ=UTC makes
             the server's local day the UTC day. Never the real ~/.findplus.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from ._offline_tiles import stub_osm_tiles
from ._trips_seed import SEED_SCRIPT

ROOT = Path(__file__).resolve().parents[2]


def _days() -> dict[str, str]:
    today = datetime.now(UTC).date()
    names = ("school", "gap", "noise", "empty", "single")
    return {n: (today - timedelta(days=i + 1)).isoformat() for i, n in enumerate(names)}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def trips_server(tmp_path_factory):
    state = tmp_path_factory.mktemp("trips-state")
    days = _days()
    env = dict(
        os.environ,
        FINDPLUS_DATABASE_PATH=str(state / "trips.sqlite"),
        FINDPLUS_STATE_DIR=str(state),
        FINDPLUS_TRIPS_DAYS=json.dumps(days),
        TZ="UTC",
    )
    subprocess.run([sys.executable, "-c", SEED_SCRIPT], check=True, env=env, cwd=ROOT)
    port = _free_port()
    args = ["serve", "--no-poller", "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(
        [sys.executable, "-m", "findplus.cli", *args],
        env=env,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                httpx.get(f"{base}/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("trips_server never became healthy")
        yield {"base": base, "days": days, "env": env, "port": port}
    finally:
        proc.terminate()
        proc.wait()


@pytest_asyncio.fixture(loop_scope="session")
async def trips_page(browser_session):
    browser, _ = browser_session
    ctx = await browser.new_context(bypass_csp=True, timezone_id="UTC")
    await stub_osm_tiles(ctx)
    pg = await ctx.new_page()
    yield pg
    await ctx.close()
